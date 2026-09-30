#!/usr/bin/env python3
"""STIP end-to-end verification: boots the real server, runs a two-user
scenario over HTTP + WebSocket. Run: .venv/bin/python e2e_verify.py"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

TMP = tempfile.mkdtemp(prefix="stip_e2e_")
ENV = {**os.environ, "STIP_DATA_DIR": TMP, "STIP_ADMINS": "e2e_admin"}
PORT = 8779
BASE = f"http://127.0.0.1:{PORT}"

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok  {name}")
    else:
        failed += 1
        print(f" FAIL {name} {detail}")


def api(method, path, token=None, body=None):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode() if body is not None else None,
        method=method, headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]


def main():
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1",
         "--port", str(PORT)], cwd=os.path.dirname(os.path.abspath(__file__)),
        env={**ENV, "PATH": os.path.dirname(sys.executable) + ":" + ENV["PATH"]},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                s, _ = api("GET", "/health")
                if s == 200:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            print("server did not start"); return 1

        s, _ = api("GET", "/health"); check("health", s == 200)

        s, a = api("POST", "/auth/signup", body={"username": "mia", "display_name": "Mia", "password": "secret123"})
        check("signup mia", s == 200, a); ta = a["access_token"]
        s, b = api("POST", "/auth/signup", body={"username": "leo", "display_name": "Leo", "password": "secret123"})
        check("signup leo", s == 200, b); tb = b["access_token"]
        s, adm = api("POST", "/auth/signup", body={"username": "e2e_admin", "password": "secret123"})
        check("signup admin", s == 200 and adm, adm); tadm = adm["access_token"]
        ha, hb, hadm = {"x": 1}, None, None  # placeholders
        HA = {"Authorization": f"Bearer {ta}"}
        HB = {"Authorization": f"Bearer {tb}"}
        HADM = {"Authorization": f"Bearer {tadm}"}

        def api2(method, path, headers, body=None):
            req = urllib.request.Request(
                BASE + path, data=json.dumps(body).encode() if body is not None else None,
                method=method, headers={"Content-Type": "application/json", **headers})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status, json.loads(r.read() or b"null")
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode()[:200]

        s, conv = api2("POST", "/conversations", HA, {"username": "leo"})
        check("create 1:1", s == 200, conv); cid = conv["id"]

        s, msg = api2("POST", f"/conversations/{cid}/messages", HA, {"body": "hey leo ✨"})
        check("send message", s == 200 and msg["body"] == "hey leo ✨", msg)
        check("bubble snapshot", msg.get("cosmetic_id") == "bubble_starter", msg.get("cosmetic_id"))
        mid = msg["id"]
        s, m2 = api2("POST", f"/conversations/{cid}/messages", HB, {"body": "hey mia!", "reply_to": mid})
        check("reply", s == 200 and m2["reply_to"]["id"] == mid, m2)
        s, _ = api2("POST", f"/conversations/{cid}/messages/{mid}/reactions", HB, {"emoji": "❤"})
        check("react", s == 200)
        s, _ = api2("POST", f"/conversations/{cid}/read", HA, {"message_id": m2["id"]})
        check("read receipt", s == 200)
        s, msgs = api2("GET", f"/conversations/{cid}/messages", HA)
        check("history", s == 200 and len(msgs) == 2, msgs)

        # websocket realtime
        import asyncio, websockets
        async def ws_check():
            async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws?token={tb}") as ws:
                await asyncio.sleep(0.3)
                s, m3 = api2("POST", f"/conversations/{cid}/messages", HA, {"body": "ws ping"})
                assert s == 200
                for _ in range(5):
                    raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    evt = json.loads(raw)
                    if evt.get("type") == "message.new":
                        return evt
                return {}
        evt = asyncio.run(ws_check())
        check("ws message.new", evt.get("type") == "message.new" and evt["message"]["body"] == "ws ping", evt)

        # economy
        s, shop = api2("GET", "/shop", HA)
        check("shop", s == 200 and len(shop["featured"]) > 0)
        item = next(i for vs in shop["by_rarity"].values() for i in vs
                    if i["price_shards"] and not i["owned"] and i["price_shards"] <= 150)
        s, p = api2("POST", "/shop/purchase", HA,
                    {"item_type": "cosmetic", "item_id": item["id"], "idempotency_key": "e2e-1"})
        check("purchase", s == 200 and p["status"] == "granted", p)
        s, p2 = api2("POST", "/shop/purchase", HA,
                     {"item_type": "cosmetic", "item_id": item["id"], "idempotency_key": "e2e-1"})
        check("idempotent repurchase", s == 200 and p2.get("duplicate") is True, p2)
        s, d = api2("POST", "/rewards/daily/claim", HA)
        check("daily claim", s == 200 and d["day_number"] == 1, d)
        s, _ = api2("POST", "/rewards/daily/claim", HA)
        check("daily double-claim blocked", s == 400)
        s, st = api2("GET", "/streaks", HA)
        check("streak (both sides sent)", s == 200 and st and st[0]["count"] >= 1, st)
        s, ach = api2("GET", "/achievements", HA)
        fm = next(a for a in ach if a["id"] == "first_message")
        check("achievement unlocked", fm["unlocked"] is True, fm)
        s, rec = api2("GET", "/admin/reconciliation", HADM)
        check("ledger reconciliation", s == 200 and rec["ok"] is True, rec)
        s, _ = api2("GET", "/admin/flags", HA)
        check("non-admin blocked", s == 403)

        # cosmetics
        s, lo = api2("GET", "/loadouts", HA)
        check("loadouts", s == 200 and lo[0]["is_active"])
        s, _ = api2("PUT", f"/loadouts/{lo[0]['id']}",
                    HA, {"slot": "AVATAR", "cosmetic_id": "avatar_neon_fox"})
        check("equip unowned rejected", s == 403)
        s, _ = api2("PUT", f"/loadouts/{lo[0]['id']}",
                    HA, {"slot": "AVATAR", "cosmetic_id": "avatar_starter"})
        check("equip owned", s == 200)

        print(f"\n{passed} passed, {failed} failed")
        return 1 if failed else 0
    finally:
        proc.terminate()


if __name__ == "__main__":
    sys.exit(main())
