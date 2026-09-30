"""STIP v3 backend tests. Run: .venv/bin/python -m pytest tests/ -q

Covers: v3 signup state machine, account recovery, username policy /
cooldown / tombstones, referrals, idempotent sends, message requests,
SSRF-guarded link previews, device trust + password OTP gate, new-device
login flags, cosmetic publishing lifecycle, event tier claims +
points accrual.
"""
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import os
import tempfile

# Mirror test_stip.py's pattern: env must be set before importing db.
# setdefault -> when the full suite runs, test_stip's values win; standalone,
# these apply.
os.environ.setdefault("STIP_DATA_DIR", tempfile.mkdtemp(prefix="stip_test_v3_"))
os.environ.setdefault("STIP_ADMINS", "superadmin")

import pytest
from fastapi.testclient import TestClient

import db  # noqa: E402
import models as m  # noqa: E402
from db import SessionLocal  # noqa: E402


@pytest.fixture(scope="session")
def v3client():
    db.init_db()
    from seed import seed
    s = SessionLocal()
    seed(s)
    s.close()
    import app as appmod
    with TestClient(appmod.app) as c:
        yield c


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def signup(client, username, password="secret123", **kw):
    r = client.post("/auth/signup", json={"username": username, "display_name": username.title(),
                                          "password": password, **kw})
    assert r.status_code == 200, r.text
    d = r.json()
    return d["access_token"], {"id": d["user_id"], "username": d["username"]}


@pytest.fixture(scope="session")
def admin2(v3client):
    tok, u = signup(v3client, "v3_superadmin2")
    s = SessionLocal()
    usr = s.get(m.User, u["id"])
    usr.is_admin = True
    s.commit()
    s.close()
    return tok, u


# ------------------------------------------------------- v3 signup machine

def test_v3_signup_flow(v3client):
    c = v3client
    # start (email)
    r = c.post("/auth/signup/start", json={"identifier": "v3flow1@example.com"})
    assert r.status_code == 200, r.text
    tok, code = r.json()["signup_token"], r.json()["dev_code"]
    assert tok and code
    # resend is fine
    r = c.post("/auth/signup/start", json={"identifier": "v3flow1@example.com"})
    assert r.status_code == 200
    # wrong code rejected
    r = c.post("/auth/signup/verify", json={"signup_token": tok, "code": "000000"})
    assert r.status_code == 400
    # right code
    r = c.post("/auth/signup/verify", json={"signup_token": tok, "code": code})
    assert r.status_code == 200 and r.json()["verified"] is True
    # username policy: too short / reserved
    r = c.post("/auth/signup/username", json={"signup_token": tok, "username": "ab"})
    assert r.status_code == 422
    r = c.post("/auth/signup/username", json={"signup_token": tok, "username": "Admin"})
    assert r.status_code == 422
    r = c.post("/auth/signup/username", json={"signup_token": tok, "username": "bad-name!"})
    assert r.status_code == 422
    # complete requires username first
    r = c.post("/auth/signup/complete", json={"signup_token": tok, "password": "secret123"})
    assert r.status_code == 400
    # reserve username
    r = c.post("/auth/signup/username", json={"signup_token": tok, "username": "v3_flow1"})
    assert r.status_code == 200, r.text
    # weak password rejected
    r = c.post("/auth/signup/complete", json={"signup_token": tok, "password": "short"})
    assert r.status_code == 400
    # complete
    r = c.post("/auth/signup/complete", json={"signup_token": tok, "password": "secret123",
                                               "display_name": "Flow One", "platform": "web"})
    assert r.status_code == 200, r.text
    d = r.json()
    atok = d["access_token"]
    # device that completed signup is trusted
    r = c.get("/auth/devices", headers=H(atok))
    assert r.status_code == 200
    assert r.json()[0]["trusted"] is True
    assert r.json()[0]["platform"] == "web"
    # starter kit granted
    r = c.get("/inventory", headers=H(atok))
    ids = {i["id"] for i in r.json()}
    assert "avatar_2d_sage" in ids and "avatar_2d_bloom" in ids
    # identifier now registered
    r = c.post("/auth/signup/start", json={"identifier": "v3flow1@example.com"})
    assert r.status_code == 400
    # login works
    r = c.post("/auth/login", json={"login": "v3_flow1", "password": "secret123"})
    assert r.status_code == 200


def test_v3_signup_phone(v3client):
    c = v3client
    r = c.post("/auth/signup/start", json={"identifier": "+15550001111"})
    assert r.status_code == 200, r.text
    tok, code = r.json()["signup_token"], r.json()["dev_code"]
    r = c.post("/auth/signup/verify", json={"signup_token": tok, "code": code})
    assert r.status_code == 200
    r = c.post("/auth/signup/username", json={"signup_token": tok, "username": "v3_phone1"})
    assert r.status_code == 200
    r = c.post("/auth/signup/complete", json={"signup_token": tok, "password": "secret123"})
    assert r.status_code == 200
    # shell usernames are not searchable / resolvable
    r = c.get("/users/me", headers=H(r.json()["access_token"]))
    assert r.json()["phone"] == "+15550001111"


def test_username_check_and_change(v3client):
    c = v3client
    tok, u = signup(c, "v3_nameuser")
    tok2, u2 = signup(c, "v3_nameuser2")
    # check endpoint: available
    r = c.get("/users/me/username/check", params={"username": "v3_brand_new"}, headers=H(tok))
    assert r.status_code == 200 and r.json()["available"] is True
    # taken by someone else
    r = c.get("/users/me/username/check", params={"username": "v3_nameuser2"}, headers=H(tok))
    assert r.status_code == 400
    # own username counts as available
    # change via dedicated endpoint
    r = c.post("/users/me/username", json={"username": "v3_renamed"}, headers=H(tok))
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "v3_renamed"
    # 30-day cooldown
    r = c.post("/users/me/username", json={"username": "v3_renamed2"}, headers=H(tok))
    assert r.status_code == 400
    # old name on 30-day hold
    r = c.get("/users/me/username/check", params={"username": "v3_nameuser"}, headers=H(tok))
    assert r.status_code == 400
    # PATCH /users/me uses the same v3 path (cooldown enforced)
    r = c.patch("/users/me", json={"username": "v3_renamed3"}, headers=H(tok))
    assert r.status_code == 400


# --------------------------------------------------------------- recovery

def test_recovery_flow(v3client):
    c = v3client
    tok, u = signup(c, "v3_recuser", email="rec@example.com")
    # start
    r = c.post("/auth/recovery/start", json={"identifier": "v3_recuser"})
    assert r.status_code == 200, r.text
    code = r.json()["dev_code"]
    # wrong code
    r = c.post("/auth/recovery/reset", json={"identifier": "v3_recuser",
                                              "code": "000000", "new_password": "newsecret1"})
    assert r.status_code == 400
    # right code -> new password, old devices revoked
    r = c.post("/auth/recovery/reset", json={"identifier": "v3_recuser",
                                              "code": code, "new_password": "newsecret1"})
    assert r.status_code == 200, r.text
    new_tok = r.json()["access_token"]
    # old token dead
    r = c.get("/users/me", headers=H(tok))
    assert r.status_code == 401
    # new password works, old doesn't
    r = c.post("/auth/login", json={"login": "v3_recuser", "password": "secret123"})
    assert r.status_code == 401
    r = c.post("/auth/login", json={"login": "v3_recuser", "password": "newsecret1"})
    assert r.status_code == 200
    r = c.get("/users/me", headers=H(new_tok))
    assert r.status_code == 200


def test_recovery_unknown_user_no_leak(v3client):
    c = v3client
    r = c.post("/auth/recovery/start", json={"identifier": "nobody_here_xyz"})
    assert r.status_code == 200
    assert "dev_code" not in r.json()


# --------------------------------------------------------------- referrals

def test_referral_flow(v3client):
    c = v3client
    ta, ua = signup(c, "v3_ref_a")
    tb, ub = signup(c, "v3_ref_b")
    r = c.get("/referrals/mine", headers=H(ta))
    assert r.status_code == 200
    code = r.json()["code"]
    assert code.startswith("STIP-")
    bal_a = c.get("/wallet", headers=H(ta)).json()["balances"]["shards"]
    bal_b = c.get("/wallet", headers=H(tb)).json()["balances"]["shards"]
    r = c.post("/referrals/apply", json={"code": code}, headers=H(tb))
    assert r.status_code == 200, r.text
    assert r.json()["rewarded_shards"] == 50
    assert c.get("/wallet", headers=H(ta)).json()["balances"]["shards"] == bal_a + 50
    assert c.get("/wallet", headers=H(tb)).json()["balances"]["shards"] == bal_b + 50
    # one code per account
    r = c.post("/referrals/apply", json={"code": code}, headers=H(tb))
    assert r.status_code == 400
    # no self-referral
    r = c.post("/referrals/apply", json={"code": code}, headers=H(ta))
    assert r.status_code == 400
    # bad code
    r = c.post("/referrals/apply", json={"code": "STIP-999-ZZZZ"}, headers=H(ta))
    assert r.status_code == 400


def test_referral_old_account_rejected(v3client):
    c = v3client
    ta, ua = signup(c, "v3_ref_c")
    code = c.get("/referrals/mine", headers=H(ta)).json()["code"]
    td, ud = signup(c, "v3_ref_old")
    # age the account 10 days
    s = SessionLocal()
    import datetime as dt
    u = s.get(m.User, ud["id"])
    u.created_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(days=10)
    s.commit()
    s.close()
    r = c.post("/referrals/apply", json={"code": code}, headers=H(td))
    assert r.status_code == 400


# ------------------------------------------------------- idempotent sending

@pytest.fixture(scope="session")
def idem_pair(v3client):
    ta, ua = signup(v3client, "v3_idem_a")
    tb, ub = signup(v3client, "v3_idem_b")
    r = v3client.post("/conversations", json={"username": "v3_idem_b"}, headers=H(ta))
    assert r.status_code == 200
    return ta, tb, r.json()["id"]


def test_idempotent_send(v3client, idem_pair):
    c = v3client
    ta, tb, conv = idem_pair
    cid = "12345678-1234-5678-1234-567812345678"
    r = c.post(f"/conversations/{conv}/messages",
               json={"body": "first", "client_msg_id": cid}, headers=H(ta))
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    assert r.json()["client_msg_id"] == cid
    assert r.json()["server_sequence"] >= 1
    # retry -> same message, duplicate flag, no double-send
    r = c.post(f"/conversations/{conv}/messages",
               json={"body": "first", "client_msg_id": cid}, headers=H(ta))
    assert r.status_code == 200
    assert r.json()["duplicate"] is True
    assert r.json()["id"] == mid
    msgs = c.get(f"/conversations/{conv}/messages?limit=100", headers=H(ta)).json()
    assert sum(1 for x in msgs if x.get("client_msg_id") == cid) == 1
    # invalid uuid rejected
    r = c.post(f"/conversations/{conv}/messages",
               json={"body": "x", "client_msg_id": "not-a-uuid"}, headers=H(ta))
    assert r.status_code == 400
    # sequences monotonic
    r1 = c.post(f"/conversations/{conv}/messages", json={"body": "s1"}, headers=H(ta)).json()
    r2 = c.post(f"/conversations/{conv}/messages", json={"body": "s2"}, headers=H(ta)).json()
    assert r2["server_sequence"] > r1["server_sequence"]


# --------------------------------------------------------- message requests

@pytest.fixture(scope="session")
def req_users(v3client):
    out = {}
    for name in ["v3_req_a", "v3_req_b", "v3_req_c", "v3_req_d", "v3_req_e", "v3_req_f"]:
        out[name] = signup(v3client, name)
    return out


def test_request_accept_flow(v3client, req_users):
    c = v3client
    ta, ua = req_users["v3_req_a"]
    tb, ub = req_users["v3_req_b"]
    # first contact -> pending request, not a visible conversation
    r = c.post("/requests", json={"username": "v3_req_b", "body": "hey, new here"}, headers=H(ta))
    assert r.status_code == 200, r.text
    assert r.json()["direct"] is False
    req_id = r.json()["request"]["id"]
    conv_id = r.json()["request"]["conversation_id"]
    # recipient inbox has it; conversation list does not
    inbox = c.get("/requests/inbox", headers=H(tb)).json()
    assert len(inbox) == 1 and inbox[0]["id"] == req_id
    conv_ids = [x["id"] for x in c.get("/conversations", headers=H(tb)).json()]
    assert conv_id not in conv_ids
    # sender sees their own hidden copy; recipient sees nothing
    assert len(c.get(f"/conversations/{conv_id}/messages", headers=H(ta)).json()) == 1
    assert c.get(f"/conversations/{conv_id}/messages", headers=H(tb)).json() == []
    # sender adds context while pending -> also hidden
    r = c.post(f"/conversations/{conv_id}/messages", json={"body": "one more thing"}, headers=H(ta))
    assert r.status_code == 200
    assert c.get(f"/conversations/{conv_id}/messages", headers=H(tb)).json() == []
    # accept -> revealed, friendship bumps fired (first_connection achievement)
    r = c.post(f"/requests/{req_id}/accept", headers=H(tb))
    assert r.status_code == 200, r.text
    assert r.json()["conversation_id"] == conv_id
    conv_ids = [x["id"] for x in c.get("/conversations", headers=H(tb)).json()]
    assert conv_id in conv_ids
    assert len(c.get(f"/conversations/{conv_id}/messages", headers=H(tb)).json()) == 2
    r = c.get("/achievements", headers=H(tb))
    fc = [a for a in r.json() if a["id"] == "first_connection"][0]
    assert fc["unlocked"] is True
    # second request to an existing contact -> 400
    r = c.post("/requests", json={"username": "v3_req_b", "body": "again"}, headers=H(ta))
    assert r.status_code == 400


def test_request_reject_flow(v3client, req_users):
    c = v3client
    tc, uc = req_users["v3_req_c"]
    td, ud = req_users["v3_req_d"]
    r = c.post("/requests", json={"username": "v3_req_d", "body": "spam?"}, headers=H(tc))
    req_id = r.json()["request"]["id"]
    conv_id = r.json()["request"]["conversation_id"]
    r = c.post(f"/requests/{req_id}/reject", json={"report": True, "reason": "spam"}, headers=H(td))
    assert r.status_code == 200, r.text
    assert c.get("/requests/inbox", headers=H(td)).json() == []
    # shadow conversation is gone
    r = c.get(f"/conversations/{conv_id}/messages", headers=H(tc))
    assert r.status_code in (403, 404)
    # a report was filed
    s = SessionLocal()
    rep = s.query(m.Report).filter_by(reporter_id=ud["id"], target_id=str(uc["id"])).first()
    s.close()
    assert rep is not None


def test_request_guards(v3client, req_users):
    c = v3client
    ta, ua = req_users["v3_req_a"]
    te, ue = req_users["v3_req_e"]
    # self
    r = c.post("/requests", json={"user_id": ua["id"], "body": "me"}, headers=H(ta))
    assert r.status_code == 400
    # blocked
    c.post("/users/block", json={"user_id": ua["id"]}, headers=H(te))
    r = c.post("/requests", json={"username": "v3_req_e", "body": "hi"}, headers=H(ta))
    assert r.status_code == 403
    c.post("/users/unblock", json={"user_id": ua["id"]}, headers=H(te))
    # empty body
    r = c.post("/requests", json={"username": "v3_req_e", "body": "  "}, headers=H(ta))
    assert r.status_code == 400


def test_request_opt_out_direct(v3client, req_users):
    c = v3client
    tc, uc = req_users["v3_req_c"]
    tf, uf = req_users["v3_req_f"]
    # recipient disables the request gate -> direct conversation
    r = c.put("/users/me/settings/message_requests", json={"value": False}, headers=H(tf))
    assert r.status_code == 200
    r = c.post("/requests", json={"username": "v3_req_f", "body": "direct hi"}, headers=H(tc))
    assert r.status_code == 200, r.text
    assert r.json()["direct"] is True
    conv_id = r.json()["conversation_id"]
    msgs = c.get(f"/conversations/{conv_id}/messages", headers=H(tf)).json()
    assert len(msgs) == 1 and msgs[0]["body"] == "direct hi"


# ------------------------------------------------------------- link preview

def test_preview_ssrf_blocked(v3client):
    c = v3client
    tok, u = signup(v3client, "v3_prev_u")
    for url in ["http://127.0.0.1/", "http://localhost:8772/", "http://169.254.169.254/",
                "http://10.0.0.1/", "ftp://example.com/x", "file:///etc/passwd"]:
        r = c.get("/preview", params={"url": url}, headers=H(tok))
        assert r.status_code == 400, (url, r.text)


class _Page(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (b"<html><head><title>Fallback Title</title>"
                b'<meta property="og:title" content="OG Title"/>'
                b'<meta property="og:description" content="A description."/>'
                b'<meta property="og:image" content="/img.png"/>'
                b"</head><body>hi</body></html>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_preview_parses_html(v3client, monkeypatch):
    import preview as preview_mod
    srv = HTTPServer(("127.0.0.1", 0), _Page)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    # bypass the IP guard (tested separately above) to exercise fetch+parse
    monkeypatch.setattr(preview_mod, "_guard_url",
                        lambda url: urllib.parse.urlparse(url))
    c = v3client
    tok, u = signup(v3client, "v3_prev_u2")
    url = f"http://127.0.0.1:{port}/page"
    r = c.get("/preview", params={"url": url}, headers=H(tok))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["title"] == "OG Title"
    assert d["description"] == "A description."
    assert d["image"] == f"http://127.0.0.1:{port}/img.png"
    # cached
    r2 = c.get("/preview", params={"url": url}, headers=H(tok))
    assert r2.json() == d
    srv.shutdown()


# ------------------------------------------------ device trust + password

def test_password_otp_gate(v3client):
    c = v3client
    tok, u = signup(v3client, "v3_devtrust", email="devtrust@example.com")
    # legacy login device is untrusted + account has email -> OTP required
    r = c.post("/auth/password", headers=H(tok),
               json={"current_password": "secret123", "new_password": "newsecret12"})
    assert r.status_code == 400
    assert "otp_code" in r.text
    # request OTP for the purpose
    r = c.post("/auth/otp/request", json={"channel": "email", "address": "devtrust@example.com",
                                          "purpose": "password_change"})
    assert r.status_code == 200
    code = r.json()["dev_code"]
    # someone else's address rejected (must match the account's own contact)
    r = c.post("/auth/password", headers=H(tok),
               json={"current_password": "secret123", "new_password": "newsecret12",
                     "otp_channel": "email", "otp_address": "other@example.com",
                     "otp_code": code})
    assert r.status_code == 400
    # correct flow -> password changed AND device trusted
    r = c.post("/auth/password", headers=H(tok),
               json={"current_password": "secret123", "new_password": "newsecret12",
                     "otp_channel": "email", "otp_address": "devtrust@example.com",
                     "otp_code": code})
    assert r.status_code == 200, r.text
    r = c.get("/auth/devices", headers=H(tok))
    assert r.json()[0]["trusted"] is True
    # now trusted -> no OTP needed
    r = c.post("/auth/password", headers=H(tok),
               json={"current_password": "newsecret12", "new_password": "secret123"})
    assert r.status_code == 200


def test_password_no_contact_fallback(v3client):
    c = v3client
    tok, u = signup(v3client, "v3_nocontact")  # no email/phone
    r = c.post("/auth/password", headers=H(tok),
               json={"current_password": "secret123", "new_password": "newsecret12"})
    assert r.status_code == 200, r.text


def test_device_verify_endpoint(v3client):
    c = v3client
    tok, u = signup(v3client, "v3_devverify", email="devverify@example.com")
    r = c.post("/auth/login", json={"login": "v3_devverify", "password": "secret123",
                                    "device_name": "fresh-laptop"})
    assert r.status_code == 200
    tok = r.json()["access_token"]
    r = c.get("/auth/devices", headers=H(tok))
    devs = [d for d in r.json() if d["device_name"] == "fresh-laptop"]
    assert devs and devs[0]["trusted"] is False
    r = c.post("/auth/otp/request", json={"channel": "email", "address": "devverify@example.com",
                                          "purpose": "device"})
    code = r.json()["dev_code"]
    r = c.post("/auth/devices/verify", json={"channel": "email", "address": "devverify@example.com",
                                             "code": code}, headers=H(tok))
    assert r.status_code == 200
    r = c.get("/auth/devices", headers=H(tok))
    devs = [d for d in r.json() if d["device_name"] == "fresh-laptop"]
    assert devs[0]["trusted"] is True


def test_new_device_login_flag(v3client):
    c = v3client
    tok, u = signup(v3client, "v3_newdev")
    r = c.post("/auth/login", json={"login": "v3_newdev", "password": "secret123",
                                    "device_name": "known-phone"})
    assert r.status_code == 200
    # known device -> not flagged
    r = c.post("/auth/login", json={"login": "v3_newdev", "password": "secret123",
                                    "device_name": "known-phone"})
    assert r.json()["new_device"] is False
    # unknown device -> flagged + security notification
    r = c.post("/auth/login", json={"login": "v3_newdev", "password": "secret123",
                                    "device_name": "strange-tablet"})
    assert r.status_code == 200
    assert r.json()["new_device"] is True
    ntok = r.json()["access_token"]
    r = c.get("/notifications", headers=H(ntok))
    assert any(n["title"] == "New sign-in" for n in r.json()["items"])


# --------------------------------------------------- publishing lifecycle

def test_publishing_lifecycle(v3client, admin2):
    c = v3client
    ah = H(admin2[0])
    payload = {"id": "test_bubble_v3", "category": "chat.bubble", "name": "V3 Bubble",
               "rarity": "rare", "acquisition": "purchase", "price_shards": 50,
               "asset": {"emoji": "🫧"}}
    r = c.post("/admin/cosmetics", json=payload, headers=ah)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "draft"  # new items start as draft
    # invisible in catalog/shop
    assert all(x["id"] != "test_bubble_v3" for x in c.get("/catalog", headers=ah).json())
    assert all(x["id"] != "test_bubble_v3"
               for items in c.get("/shop", headers=ah).json()["by_rarity"].values() for x in items)
    # invalid transition
    r = c.post("/admin/cosmetics/test_bubble_v3/transition", json={"to_status": "retired"}, headers=ah)
    assert r.status_code == 400
    # draft -> review -> scheduled (needs publish_at)
    r = c.post("/admin/cosmetics/test_bubble_v3/transition", json={"to_status": "review"}, headers=ah)
    assert r.status_code == 200
    r = c.post("/admin/cosmetics/test_bubble_v3/transition", json={"to_status": "scheduled"}, headers=ah)
    assert r.status_code == 400
    r = c.post("/admin/cosmetics/test_bubble_v3/transition",
               json={"to_status": "scheduled", "publish_at": "2999-01-01T00:00:00"}, headers=ah)
    assert r.status_code == 200
    assert all(x["id"] != "test_bubble_v3" for x in c.get("/catalog", headers=ah).json())
    # scheduled in the past -> lazily flips to live on read
    r = c.post("/admin/cosmetics", json={**payload, "id": "test_bubble_v3b",
                                        "status": "scheduled", "publish_at": "2020-01-01T00:00:00"},
               headers=ah)
    assert r.status_code == 200
    catalog = c.get("/catalog", headers=ah).json()
    assert any(x["id"] == "test_bubble_v3b" for x in catalog)
    # non-admin cannot transition
    tok, u = signup(v3client, "v3_notadmin")
    r = c.post("/admin/cosmetics/test_bubble_v3/transition", json={"to_status": "live"}, headers=H(tok))
    assert r.status_code == 403


def test_retire_keeps_owner_copy(v3client, admin2):
    c = v3client
    ah = H(admin2[0])
    tok, u = signup(v3client, "v3_retiree")
    r = c.post("/admin/cosmetics", json={"id": "test_bubble_v3c", "category": "chat.bubble",
                                         "name": "V3 Retire", "rarity": "common",
                                         "status": "live", "asset": {}}, headers=ah)
    assert r.status_code == 200
    r = c.post("/admin/economy/grant", json={"user_id": u["id"], "cosmetic_id": "test_bubble_v3c"},
               headers=ah)
    assert r.status_code == 200
    r = c.post("/admin/cosmetics/test_bubble_v3c/transition", json={"to_status": "retired"}, headers=ah)
    assert r.status_code == 200
    # gone from shop...
    shop_items = [x["id"] for items in c.get("/shop", headers=H(tok)).json()["by_rarity"].values()
                  for x in items]
    assert "test_bubble_v3c" not in shop_items
    # ...but the owner keeps it working (inventory + catalog-as-owned)
    assert any(i["id"] == "test_bubble_v3c" for i in c.get("/inventory", headers=H(tok)).json())
    assert any(x["id"] == "test_bubble_v3c" for x in c.get("/catalog", headers=H(tok)).json())


# ------------------------------------------------- reward engine hardening

def test_event_points_accrue_and_tiers_idempotent(v3client):
    c = v3client
    ta, ua = signup(v3client, "v3_ev_a")
    tb, ub = signup(v3client, "v3_ev_b")
    r = c.post("/conversations", json={"username": "v3_ev_b"}, headers=H(ta))
    conv = r.json()["id"]
    c.post(f"/conversations/{conv}/messages", json={"body": "one"}, headers=H(ta))
    c.post(f"/conversations/{conv}/messages", json={"body": "two"}, headers=H(tb))
    r = c.get("/events/cosmic_season", headers=H(ta))
    assert r.status_code == 200
    assert r.json()["points"] > 0  # points accrue server-side while live
    # seed points for a deterministic claim test
    s = SessionLocal()
    pts = s.query(m.EventPoints).filter_by(user_id=ua["id"], event_id="cosmic_season").first()
    pts.points = 150
    s.commit()
    bal = s.query(m.Wallet).filter_by(user_id=ua["id"], currency="shards").first().balance
    s.close()
    # tier 0 = 100 points -> 100 shards
    r = c.post("/events/cosmic_season/tiers/claim", json={"tier_index": 0}, headers=H(ta))
    assert r.status_code == 200, r.text
    r = c.get("/wallet", headers=H(ta))
    assert r.json()["balances"]["shards"] == bal + 100
    # retry -> already claimed (no double-grant)
    r = c.post("/events/cosmic_season/tiers/claim", json={"tier_index": 0}, headers=H(ta))
    assert r.status_code == 400
    r = c.get("/wallet", headers=H(ta))
    assert r.json()["balances"]["shards"] == bal + 100
    # tier 1 needs 500 points -> not enough
    r = c.post("/events/cosmic_season/tiers/claim", json={"tier_index": 1}, headers=H(ta))
    assert r.status_code == 400
    # bad index
    r = c.post("/events/cosmic_season/tiers/claim", json={"tier_index": 99}, headers=H(ta))
    assert r.status_code == 400


def test_daily_claim_still_idempotent(v3client):
    c = v3client
    tok, u = signup(v3client, "v3_daily")
    r = c.post("/rewards/daily/claim", headers=H(tok))
    assert r.status_code == 200
    r = c.post("/rewards/daily/claim", headers=H(tok))
    assert r.status_code == 400


def test_daily_status_after_claim(v3client):
    """Regression: GET /rewards/daily 500'd (NameError: dt) once a claim
    existed. Found 2026-09-30 via a real browser click-through."""
    c = v3client
    tok, u = signup(v3client, "v3_daily_status")
    r = c.get("/rewards/daily", headers=H(tok))
    assert r.status_code == 200, r.text
    assert r.json()["claimed"] is False
    assert len(r.json()["ladder"]) == 30
    r = c.post("/rewards/daily/claim", headers=H(tok))
    assert r.status_code == 200
    r = c.get("/rewards/daily", headers=H(tok))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["claimed"] is True
    assert d["next_day"] == 2
