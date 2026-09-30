# STIP — Make Every Chat Yours

A cosmetic-driven 1:1 messaging app. Messaging is the core; cosmetics are the
optional identity layer (zero functional advantage from paid items).

## Run it (your machine)

**Backend** (port 8772):
```bash
cd ~/workspace/stip/backend
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8772
```
First run seeds the catalog (52 cosmetics, sets, achievements, 30-day reward
ladder, Cosmic Season event). Data lives in `~/.stip/`.

Make yourself admin: `STIP_ADMINS=your_username` before starting.

**Frontend**: open `http://127.0.0.1:8772/` — the backend serves the built app.
Rebuild after changes:
```bash
cd ~/workspace/stip/frontend && npm install && npm run build
```

**Tests**: `cd backend && .venv/bin/python -m pytest tests/ -q` (40 tests)
**E2E**: `.venv/bin/python e2e_verify.py` (24 live checks incl. WebSocket)

## Android APK

The web app is wrapped with [Capacitor](https://capacitorjs.com/) — the same
code, running as a native Android app.

**Get an APK (no Android Studio needed):**
1. Run the backend on your computer so your phone can reach it:
   ```bash
   cd backend && uvicorn app:app --host 0.0.0.0 --port 8772
   ```
   (`0.0.0.0`, not `127.0.0.1` — your phone can't reach your loopback.)
2. Find your computer's LAN IP (`ipconfig` on Windows, `ip addr` on Linux/macOS).
3. GitHub repo → **Actions** → **Build Android APK** → **Run workflow** →
   enter `api_url` as `http://<your-lan-ip>:8772` → **Run workflow**.
4. When it finishes, download the **stip-debug-apk** artifact, copy it to your
   phone, and install it (debug builds are auto-signed; allow "install unknown
   apps" once).

Every push to `main` also builds an APK automatically (pointing at the Android
emulator's `http://10.0.2.2:8772` by default).

**Build locally** (needs Android Studio / SDK):
```bash
cd frontend
VITE_API_URL=http://<your-lan-ip>:8772 bun run build
bun x cap sync android
cd android && ./gradlew assembleDebug
# APK: android/app/build/outputs/apk/debug/app-debug.apk
```

Notes: the API URL is baked in at web-build time (`VITE_API_URL`); the backend
allows cross-origin requests from the app's WebView (set `STIP_CORS_ORIGINS` to
tighten in production). Sign the APK with your own key for Play Store release.

## What's new in v3 (2026-09-30)

Per `STIP_Master_Specification_v3.docx`; decisions in `docs/adr/` (web-first,
v3 auth state machine, E2EE deferred with upgrade path).
- Auth: email/phone → verify → username → password signup machine (legacy
  signup deprecated but working); username policy (3–20, reserved list,
  30-day change cooldown, 30-day released-name hold); recovery flow; device
  trust + OTP-gated password changes on untrusted devices.
- Messaging: idempotent sends (`client_msg_id` + `server_sequence`), message
  requests with inbox/accept/reject(+report), SSRF-guarded link previews.
- Social: referrals (50 shards both sides, anti-farming caps), QR identity.
- Cosmetics: publishing lifecycle (draft→review→scheduled→live→retired),
  2D avatar starter identities, per-chat personality themes, cosmetic
  discovery sheets, light/dark/follow-system themes with reduced-motion
  kill switch.

## Layout

- `backend/` — FastAPI modular monolith: `app.py` (auth/users/messaging),
  `cosmetics.py` (catalog/loadouts/themes), `economy.py` (wallet/shop/gifts/rewards),
  `engagement.py` (streaks/events/achievements), `admin.py`, `core.py`
  (ledger/XP/achievements), `models.py`, `seed.py`, `ws.py`
- `frontend/` — React + TS + Vite
- `API.md` — full API contract

## Honest limits (not faked)

- Payments: dev provider only (instant verify). Real billing is a swap-in.
- E2EE: not implemented; documented upgrade path.
- No voice/video calls or voice messages (out of scope per spec).
- Push: in-app notifications only.
