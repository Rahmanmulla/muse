"""STIP backend test suite. Run: .venv/bin/python -m pytest tests/ -q

Covers: auth/OTP/devices, messaging lifecycle, malicious ownership and
balance inputs, idempotent purchases, gifting rules, daily-reward
idempotency, streak two-sided rule, ledger reconciliation, admin guards.
"""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

TMP = tempfile.mkdtemp(prefix="stip_test_")
os.environ["STIP_DATA_DIR"] = TMP
os.environ["STIP_ADMINS"] = "superadmin"

import db  # noqa: E402
import models as m  # noqa: E402
from db import SessionLocal  # noqa: E402


@pytest.fixture(scope="session")
def client():
    db.init_db()
    from seed import seed
    s = SessionLocal()
    seed(s)
    s.close()
    import app as appmod
    with TestClient(appmod.app) as c:
        yield c


def signup(client, username, password="secret123"):
    r = client.post("/auth/signup", json={"username": username, "display_name": username.title(),
                                          "password": password})
    assert r.status_code == 200, r.text
    d = r.json()
    return d["access_token"], {"id": d["user_id"], "username": d["username"]}


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="session")
def alice(client):
    return signup(client, "alice")


@pytest.fixture(scope="session")
def bob(client):
    return signup(client, "bob")


@pytest.fixture(scope="session")
def admin(client):
    return signup(client, "superadmin")


# ------------------------------------------------------------------ auth

def test_login_lockout(client):
    signup(client, "locky")
    for _ in range(8):
        r = client.post("/auth/login", json={"login": "locky", "password": "wrong"})
    assert r.status_code == 401
    r = client.post("/auth/login", json={"login": "locky", "password": "secret123"})
    assert r.status_code == 403  # locked


def test_otp_dev_flow(client):
    r = client.post("/auth/otp/request", json={"channel": "phone", "address": "+10000000001"})
    assert r.status_code == 200
    code = r.json()["dev_code"]
    assert code
    r = client.post("/auth/otp/verify", json={"channel": "phone", "address": "+10000000001", "code": code})
    assert r.status_code == 200
    assert r.json()["verified"] is True
    # single use
    r = client.post("/auth/otp/verify", json={"channel": "phone", "address": "+10000000001", "code": code})
    assert r.status_code == 400


def test_device_revoke(client):
    tok, user = signup(client, "devuser")
    r = client.get("/auth/devices", headers=H(tok))
    assert r.status_code == 200
    assert len(r.json()) >= 1


# -------------------------------------------------------------- messaging

@pytest.fixture(scope="session")
def convo(client, alice, bob):
    ta, ua = alice
    tb, ub = bob
    r = client.post("/conversations", json={"username": "bob"}, headers=H(ta))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_message_lifecycle(client, alice, bob, convo):
    ta, ua = alice
    tb, ub = bob
    r = client.post(f"/conversations/{convo}/messages", json={"body": "hello bob"}, headers=H(ta))
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    assert r.json()["cosmetic_id"] == "bubble_starter"  # default loadout bubble
    # reply + edit + react
    r = client.post(f"/conversations/{convo}/messages", json={"body": "hi alice", "reply_to": mid}, headers=H(tb))
    assert r.status_code == 200
    mid2 = r.json()["id"]
    r = client.patch(f"/conversations/{convo}/messages/{mid2}", json={"body": "hi alice!"}, headers=H(tb))
    assert r.status_code == 200 and r.json()["edited_at"] is not None
    # edit someone else's message -> 404/403
    r = client.patch(f"/conversations/{convo}/messages/{mid2}", json={"body": "pwned"}, headers=H(ta))
    assert r.status_code in (403, 404)
    r = client.post(f"/conversations/{convo}/messages/{mid}/reactions", json={"emoji": "❤"}, headers=H(tb))
    assert r.status_code == 200
    # read + streak: alice sent, bob sent -> both sides participated
    r = client.post(f"/conversations/{convo}/read", json={"message_id": mid2}, headers=H(ta))
    assert r.status_code == 200
    r = client.get("/streaks", headers=H(ta))
    assert r.json()[0]["count"] >= 1


def test_block_enforced(client, alice):
    ta, ua = alice
    tokc, uc = signup(client, "carol")
    client.post("/users/block", json={"user_id": uc["id"]}, headers=H(ta))
    r = client.post("/conversations", json={"username": "alice"}, headers=H(tokc))
    assert r.status_code == 403
    client.post("/users/unblock", json={"user_id": uc["id"]}, headers=H(ta))


def test_message_history_limit(client, alice, convo):
    ta, ua = alice
    for i in range(5):
        client.post(f"/conversations/{convo}/messages", json={"body": f"spam {i}"}, headers=H(ta))
    r = client.get(f"/conversations/{convo}/messages?limit=3", headers=H(ta))
    assert len(r.json()) == 3


# --------------------------------------------------------------- cosmetics

def test_equip_unowned_rejected(client, alice):
    ta, ua = alice
    r = client.get("/loadouts", headers=H(ta))
    lo = [x for x in r.json() if x["is_active"]][0]
    r = client.put(f"/loadouts/{lo['id']}", json={"slot": "AVATAR", "cosmetic_id": "avatar_neon_fox"},
                   headers=H(ta))
    assert r.status_code == 403  # doesn't own it


def test_equip_owned_ok(client, alice):
    ta, ua = alice
    r = client.get("/loadouts", headers=H(ta))
    lo = [x for x in r.json() if x["is_active"]][0]
    r = client.put(f"/loadouts/{lo['id']}", json={"slot": "AVATAR", "cosmetic_id": "avatar_starter"},
                   headers=H(ta))
    assert r.status_code == 200
    assert r.json()["items"]["AVATAR"]["id"] == "avatar_starter"


def test_wrong_slot_category_rejected(client, alice):
    ta, ua = alice
    r = client.get("/loadouts", headers=H(ta))
    lo = [x for x in r.json() if x["is_active"]][0]
    r = client.put(f"/loadouts/{lo['id']}", json={"slot": "AVATAR", "cosmetic_id": "bubble_classic"},
                   headers=H(ta))
    assert r.status_code == 400


def test_chat_theme_ownership_enforced(client, alice, convo):
    ta, ua = alice
    r = client.put(f"/conversations/{convo}/theme",
                   json={"scope": "personal", "wallpaper_id": "wp_cyberpunk"}, headers=H(ta))
    assert r.status_code == 403  # unowned
    r = client.put(f"/conversations/{convo}/theme",
                   json={"scope": "personal", "wallpaper_id": "wp_starter"}, headers=H(ta))
    assert r.status_code == 200
    r = client.get(f"/conversations/{convo}/theme", headers=H(ta))
    assert r.json()["wallpaper_id"]["id"] == "wp_starter"


# ---------------------------------------------------------------- economy

def test_purchase_idempotent(client, alice):
    ta, ua = alice
    r = client.get("/shop", headers=H(ta))
    shop = r.json()
    pool = [i for items in shop["by_rarity"].values() for i in items
            if i["price_shards"] and not i["owned"]]
    assert pool, "no purchasable shard items in shop"
    item = sorted(pool, key=lambda i: i["price_shards"])[0]
    key = "test-key-1"
    p1 = client.post("/shop/purchase", json={"item_type": "cosmetic", "item_id": item["id"],
                                              "idempotency_key": key}, headers=H(ta))
    assert p1.status_code == 200, p1.text
    bal_after = p1.json()["balances"]["shards"]
    p2 = client.post("/shop/purchase", json={"item_type": "cosmetic", "item_id": item["id"],
                                              "idempotency_key": key}, headers=H(ta))
    assert p2.status_code == 200
    assert p2.json()["duplicate"] is True
    r = client.get("/wallet", headers=H(ta))
    assert r.json()["balances"]["shards"] == bal_after  # charged exactly once


def test_purchase_insufficient_funds(client):
    tok, u = signup(client, "broke")
    r = client.post("/shop/purchase", json={"item_type": "cosmetic", "item_id": "bubble_cosmic",
                                            "idempotency_key": "broke-1"}, headers=H(tok))
    assert r.status_code == 400


def test_gift_rules(client, alice, bob, admin):
    ta, ua = alice
    tb, ub = bob
    ah = H(admin[0])
    # gift unowned -> 400
    r = client.post("/gifts", json={"cosmetic_id": "avatar_neon_fox", "recipient_id": ub["id"]}, headers=H(ta))
    assert r.status_code == 400
    # admin grants alice a transferable item; alice gifts it to bob
    r = client.post("/admin/economy/grant", json={"user_id": ua["id"], "cosmetic_id": "reaction_lightning"}, headers=ah)
    assert r.status_code == 200
    r = client.post("/gifts", json={"cosmetic_id": "reaction_lightning", "recipient_id": ub["id"],
                                    "message": "for you"}, headers=H(ta))
    assert r.status_code == 200, r.text
    # alice no longer owns it; bob does
    r = client.get("/inventory", headers=H(ta))
    assert all(i["id"] != "reaction_lightning" for i in r.json())
    r = client.get("/inventory", headers=H(tb))
    assert any(i["id"] == "reaction_lightning" for i in r.json())
    # gifting again (no longer owned) -> 400
    r = client.post("/gifts", json={"cosmetic_id": "reaction_lightning", "recipient_id": ub["id"]}, headers=H(ta))
    assert r.status_code == 400



def test_daily_claim_idempotent(client, alice):
    ta, ua = alice
    r = client.post("/rewards/daily/claim", headers=H(ta))
    assert r.status_code == 200, r.text
    assert r.json()["day_number"] == 1
    r = client.post("/rewards/daily/claim", headers=H(ta))
    assert r.status_code == 400  # already claimed


def test_ledger_reconciliation(client, admin):
    r = client.get("/admin/reconciliation", headers=H(admin[0]))
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_non_admin_blocked(client, alice):
    ta, ua = alice
    r = client.get("/admin/flags", headers=H(ta))
    assert r.status_code == 403


def test_refund_flow(client, admin):
    ah = H(admin[0])
    tok, u = signup(client, "refundy")
    # grant shards then buy
    client.post("/admin/economy/grant", json={"user_id": u["id"], "currency": "shards", "amount": 1000,
                                              "reason": "test"}, headers=ah)
    r = client.post("/shop/purchase", json={"item_type": "cosmetic", "item_id": "bubble_glass",
                                            "idempotency_key": "refund-1"}, headers=H(tok))
    assert r.status_code == 200
    pid = r.json()["purchase_id"]
    bal_before = client.get("/wallet", headers=H(tok)).json()["balances"]["shards"]
    r = client.post(f"/admin/purchases/{pid}/refund", headers=ah)
    assert r.status_code == 200
    assert r.json()["revoked"] >= 1
    bal_after = client.get("/wallet", headers=H(tok)).json()["balances"]["shards"]
    assert bal_after == bal_before + 100  # price of bubble_glass refunded
    r = client.get("/inventory", headers=H(tok))
    assert all(i["id"] != "bubble_glass" for i in r.json())


def test_achievements_progress(client, alice, convo):
    ta, ua = alice
    r = client.get("/achievements", headers=H(ta))
    first = [a for a in r.json() if a["id"] == "first_connection"][0]
    assert first["unlocked"] is True
    r = client.get("/profile/progress", headers=H(ta))
    assert r.json()["level"] >= 1
