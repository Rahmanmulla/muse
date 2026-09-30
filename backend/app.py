"""STIP backend — core API: auth, users, conversations, messages, media.

Run: uvicorn app:app --host 127.0.0.1 --port 8772
"""
from __future__ import annotations

import datetime as dt
import os
import re
import secrets
import shutil
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

import models as m
from auth import (ADMINS, get_current_device, get_current_user, hash_password, issue_tokens, rate_limit,
                  require_admin, verify_password)
from core import (audit, award_xp, bump_event, bump_stat, check_achievements, credit,
                  get_stat, has_entitlement, local_day, next_seq, notify, resolve_chat_style,
                  streak_pair, today_utc, utcnow)
from db import MEDIA_DIR, SessionLocal, get_db, init_db
from seed import grant_starter_kit, seed
from verify import consume_otp, issue_otp
from ws import manager, user_id_from_token

app = FastAPI(title="STIP API", version="1.0.0")

# CORS: the Android (Capacitor) app runs in a WebView on its own origin and
# calls this API cross-origin. Bearer-token auth (no cookies), so a permissive
# origin policy is safe here. Tighten STIP_CORS_ORIGINS in production.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

_cors_origins = [o.strip() for o in os.environ.get("STIP_CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Modular monolith routers (spec 71): clean boundaries, extractable later.
from cosmetics import router as cosmetics_router  # noqa: E402
from economy import router as economy_router  # noqa: E402
from engagement import router as engagement_router  # noqa: E402
from admin import router as admin_router  # noqa: E402
from identity import router as identity_router  # noqa: E402  (v3 auth state machine)
from requests import router as requests_router  # noqa: E402  (v3 message requests)
from preview import router as preview_router  # noqa: E402  (v3 link previews)

app.include_router(cosmetics_router)
app.include_router(economy_router)
app.include_router(engagement_router)
app.include_router(admin_router)
app.include_router(identity_router)
app.include_router(requests_router)
app.include_router(preview_router)

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,30}[a-z0-9]$")
RESERVED = {"admin", "support", "stip", "official", "system", "mod", "moderator",
            "help", "security", "staff", "team", "null", "undefined"}

SETTINGS_SCHEMA = {
    "profile_visibility": ["everyone", "contacts", "nobody"],
    "read_receipts": bool, "typing_indicators": bool, "online_status": bool,
    "last_seen": ["everyone", "contacts", "nobody"],
    "link_previews": bool, "media_autodownload": ["wifi", "always", "never"],
    "notification_preview": ["full", "sender", "none"],
    "reduced_motion": bool, "haptics": ["on", "reduced", "off"],
    "theme": ["light", "dark", "system"],
    "cosmetic_downloads": ["wifi", "always", "manual"],
    "streak_notifications": bool, "event_notifications": bool,
    # v3: strangers must go through a message request (default) vs open DMs
    "message_requests": bool,
}
DEFAULT_SETTINGS = {
    "profile_visibility": "everyone", "read_receipts": True, "typing_indicators": True,
    "online_status": True, "last_seen": "everyone", "link_previews": True,
    "media_autodownload": "wifi", "notification_preview": "full",
    "reduced_motion": False, "haptics": "on", "theme": "system",
    "cosmetic_downloads": "wifi", "streak_notifications": True, "event_notifications": True,
    "message_requests": True,
}

# --------------------------------------------------------------- utilities

def validate_username(username: str) -> str:
    u = (username or "").strip().lower()
    if not USERNAME_RE.match(u):
        raise HTTPException(422, "Username must be 3-32 chars: lowercase letters, digits, . _ -; start and end alphanumeric.")
    if u in RESERVED:
        raise HTTPException(422, "That username is reserved.")
    return u


def is_blocked(db: Session, a: int, b: int) -> bool:
    return db.query(m.Block).filter(
        or_((m.Block.blocker_id == a) & (m.Block.blocked_id == b),
            (m.Block.blocker_id == b) & (m.Block.blocked_id == a))).first() is not None


def profile_out(db: Session, user: m.User, viewer_id: int | None = None) -> dict:
    active = db.query(m.Loadout).filter_by(user_id=user.id, is_active=True).first()
    items = {}
    if active:
        items = {i.slot: i.cosmetic_id for i in db.query(m.LoadoutItem).filter_by(loadout_id=active.id).all()}
    def cos(cid):
        if not cid:
            return None
        c = db.get(m.Cosmetic, cid)
        return {"id": c.id, "name": c.name, "rarity": c.rarity, "category": c.category,
                "asset": c.asset, "performance_class": c.performance_class} if c else None
    show_private = viewer_id == user.id
    vis = get_setting(db, user.id, "profile_visibility")
    can_view = show_private or vis == "everyone"  # contacts check is future scope
    last_seen = user.last_seen.isoformat() if user.last_seen else None
    if not show_private:
        ls_vis = get_setting(db, user.id, "last_seen")
        if ls_vis == "nobody":
            last_seen = None
        if get_setting(db, user.id, "online_status") is False:
            last_seen = None
    return {
        "id": user.id, "username": user.username, "display_name": user.display_name,
        "avatar": cos(items.get("AVATAR")) if can_view else None,
        "frame": cos(items.get("FRAME")) if can_view else None,
        "banner": cos(items.get("BANNER")) if can_view else None,
        "nameplate": cos(items.get("NAMEPLATE")) if can_view else None,
        "profile_effect": cos(items.get("PROFILE_EFFECT")) if can_view else None,
        "level": user.level, "xp": user.xp,
        "last_seen": last_seen,
        "online": False,  # filled by presence where known
        "email": user.email if show_private else None,
        "phone": user.phone if show_private else None,
        "created_at": user.created_at.isoformat(),
    }


def get_setting(db: Session, user_id: int, key: str):
    row = db.query(m.UserSetting).filter_by(user_id=user_id, key=key).first()
    if row:
        return row.value
    return DEFAULT_SETTINGS.get(key)


def conv_out(db: Session, conv: m.Conversation, viewer_id: int) -> dict:
    members = db.query(m.ConversationMember).filter_by(conversation_id=conv.id).all()
    member_ids = [x.user_id for x in members]
    peer = None
    if not conv.is_group and len(member_ids) == 2:
        peer_id = member_ids[0] if member_ids[1] == viewer_id else member_ids[1]
        peer_u = db.get(m.User, peer_id)
        if peer_u:
            peer = profile_out(db, peer_u, viewer_id)
            peer["online"] = peer_id in manager.active
    # hidden messages (pending message request) are only visible to their sender
    visible = or_(m.Message.hidden == False, m.Message.sender_id == viewer_id)
    last = (db.query(m.Message).filter(m.Message.conversation_id == conv.id, visible)
            .order_by(m.Message.id.desc()).first())
    last_msg = None
    if last:
        last_msg = {"id": last.id, "kind": last.kind, "sender_id": last.sender_id,
                    "body": None if last.deleted else (last.body[:120] if last.kind == "text" else f"[{last.kind}]"),
                    "created_at": last.created_at.isoformat()}
    read = db.query(m.ReadReceipt).filter_by(conversation_id=conv.id, user_id=viewer_id).first()
    last_read = read.last_read_message_id if read else 0
    unread = db.query(m.Message).filter(
        m.Message.conversation_id == conv.id, m.Message.id > last_read,
        m.Message.sender_id != viewer_id, m.Message.deleted == False, visible).count()
    muted = bool(db.query(m.UserSetting).filter_by(
        user_id=viewer_id, key=f"mute_{conv.id}").first())
    pinned = bool(db.query(m.UserSetting).filter_by(
        user_id=viewer_id, key=f"pin_{conv.id}").first())
    streak = None
    if not conv.is_group and peer:
        a, b = streak_pair(viewer_id, peer["id"])
        s = db.query(m.Streak).filter_by(user_a=a, user_b=b).first()
        if s and s.count > 0:
            streak = {"count": s.count, "longest": s.longest}
    theme = db.query(m.ChatTheme).filter_by(user_id=viewer_id, conversation_id=conv.id).first()
    member_profiles = []
    for uid in member_ids:
        u = db.get(m.User, uid)
        if u:
            member_profiles.append(profile_out(db, u, viewer_id))
    # v3 message-request state for this conversation (if any)
    request_info = None
    req = db.query(m.MessageRequest).filter_by(conversation_id=conv.id, status="pending").first()
    if req and viewer_id in (req.from_user_id, req.to_user_id):
        request_info = {"id": req.id, "status": req.status,
                        "direction": "outgoing" if req.from_user_id == viewer_id else "incoming",
                        "from_user_id": req.from_user_id, "to_user_id": req.to_user_id,
                        "created_at": req.created_at.isoformat()}
    return {
        "id": conv.id, "is_group": conv.is_group, "title": conv.title or (peer["display_name"] if peer else "Chat"),
        "peer": peer, "member_count": len(member_ids), "members": member_profiles,
        "last_message": last_msg,
        "unread": unread, "unread_count": unread, "muted": muted, "pinned": pinned, "streak": streak,
        "theme_scope": theme.scope if theme else None,
        "request": request_info,
        "updated_at": conv.updated_at.isoformat(),
    }


def message_out(db: Session, msg: m.Message, viewer_id: int) -> dict:
    sender = db.get(m.User, msg.sender_id)
    reply = None
    if msg.reply_to_id:
        r = db.get(m.Message, msg.reply_to_id)
        if r:
            rs = db.get(m.User, r.sender_id)
            reply = {"id": r.id, "sender_username": rs.username if rs else "?",
                     "body": None if r.deleted else (r.body[:200] if r.kind == "text" else f"[{r.kind}]"),
                     "kind": r.kind}
    reacts = db.query(m.Reaction).filter_by(message_id=msg.id).all()
    by_emoji: dict[str, dict] = {}
    for rc in reacts:
        e = by_emoji.setdefault(rc.emoji, {"emoji": rc.emoji, "count": 0, "users": [], "effect_id": rc.effect_id})
        e["count"] += 1
        e["users"].append(rc.user_id)
    statuses = db.query(m.MessageStatus).filter_by(message_id=msg.id).all()
    delivery = {s.user_id: s.state for s in statuses}
    media_url = f"/media/{Path(msg.media_path).name}" if msg.media_path else None
    return {
        "id": msg.id, "conversation_id": msg.conversation_id, "sender_id": msg.sender_id,
        "sender_username": sender.username if sender else "?",
        "kind": msg.kind, "body": None if msg.deleted else msg.body,
        "media_url": media_url, "media_mime": msg.media_mime,
        "sticker_pack_id": msg.sticker_pack_id, "sticker_id": msg.sticker_id,
        "reply_to": reply, "forwarded": msg.forwarded,
        "reactions": list(by_emoji.values()),
        "cosmetic_id": msg.cosmetic_id, "send_effect_id": msg.send_effect_id,
        "client_msg_id": msg.client_msg_id, "server_sequence": msg.server_sequence,
        "edited_at": msg.edited_at.isoformat() if msg.edited_at else None,
        "deleted": msg.deleted, "delivery": delivery,
        "created_at": msg.created_at.isoformat(),
    }


def require_member(db: Session, conv_id: int, user_id: int) -> m.Conversation:
    conv = db.get(m.Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found.")
    mem = db.query(m.ConversationMember).filter_by(conversation_id=conv_id, user_id=user_id).first()
    if not mem:
        raise HTTPException(403, "Not a member of this conversation.")
    return conv


# ------------------------------------------------------------------- signup

# NOTE: the legacy username+password signup below is kept working but
# deprecated in favor of the v3 identifier-first state machine
# (POST /auth/signup/start|verify|username|complete) in identity.py.
# Legacy accounts are grandfathered as identifier-verified (ADR-002).


@app.post("/auth/signup")
async def signup(payload: dict, db: Session = Depends(get_db)):
    rate_limit("signup:" + (payload.get("username") or "?"), 10, 3600)
    username = validate_username(payload.get("username", ""))
    display = (payload.get("display_name") or username).strip()[:64]
    if db.query(m.User).filter_by(username=username).first():
        raise HTTPException(400, "Username is taken.")
    email = (payload.get("email") or "").strip().lower() or None
    phone = (payload.get("phone") or "").strip() or None
    if email and db.query(m.User).filter_by(email=email).first():
        raise HTTPException(400, "Email already registered.")
    if phone and db.query(m.User).filter_by(phone=phone).first():
        raise HTTPException(400, "Phone already registered.")
    user = m.User(username=username, display_name=display, email=email, phone=phone,
                  password_hash=hash_password(payload.get("password", "")),
                  utc_offset_minutes=int(payload.get("utc_offset_minutes") or 0),
                  is_admin=username in ADMINS,
                  identifier_verified=True)  # legacy flow: grandfathered (ADR-002)
    db.add(user)
    db.commit()
    db.refresh(user)
    grant_starter_kit(db, user)
    credit(db, user.id, "shards", 100, "welcome_bonus", "reward", "welcome")
    db.commit()
    audit(db, user.id, "signup", "user", str(user.id), {"username": username})
    db.commit()
    tokens = issue_tokens(user, payload.get("device_name"), db)
    await bump_event(db, user.id, "friend_added", 0)  # no-op warmup
    return {**tokens, "user_id": user.id, "username": username}


@app.post("/auth/login")
async def login(payload: dict, db: Session = Depends(get_db)):
    login_id = (payload.get("login") or "").strip().lower()
    rate_limit("login:" + login_id, 20, 600)
    user = (db.query(m.User).filter_by(username=login_id).first()
            or db.query(m.User).filter_by(email=login_id).first()
            or db.query(m.User).filter_by(phone=payload.get("login", "").strip()).first())
    if user is None:
        raise HTTPException(401, "Invalid credentials.")
    if user.locked_until and user.locked_until > utcnow():
        raise HTTPException(403, "Account temporarily locked. Try again later.")
    if not verify_password(payload.get("password", ""), user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= 8:
            user.locked_until = utcnow() + dt.timedelta(minutes=15)
            user.failed_logins = 0
        db.commit()
        audit(db, user.id, "login_failed", "user", str(user.id), {})
        db.commit()
        raise HTTPException(401, "Invalid credentials.")
    if not user.identifier_verified or user.username.startswith("pending_"):
        # unfinished v3 signup shell — can never log in with a password
        raise HTTPException(403, "Account not verified yet. Complete signup first.")
    user.failed_logins = 0
    user.locked_until = None
    # v3: flag sign-ins from a device name we haven't seen for this user
    device_name = payload.get("device_name") or "unknown"
    known = {r[0] for r in db.query(m.Device.device_name)
             .filter_by(user_id=user.id).all()}
    new_device = device_name not in known
    db.commit()
    audit(db, user.id, "login", "user", str(user.id),
          {"device_name": device_name, "new_device": new_device})
    db.commit()
    tokens = issue_tokens(user, device_name, db, platform=payload.get("platform"))
    if new_device:
        audit(db, user.id, "new_device_login", "user", str(user.id),
              {"device_name": device_name, "platform": payload.get("platform")})
        await notify(db, user.id, "security", "New sign-in",
                     f"A new device signed in: {device_name}. If this wasn't you, revoke it in Settings.",
                     {"kind": "new_device", "device_name": device_name})
        db.commit()
    return {**tokens, "user_id": user.id, "username": user.username, "new_device": new_device}


@app.post("/auth/logout")
def logout(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    # revoke handled via token lookup — find current jti from... simplified:
    # revoke all devices is explicit; here we revoke the most recent active device
    dev = (db.query(m.Device).filter_by(user_id=user.id, revoked=False)
           .order_by(m.Device.id.desc()).first())
    if dev:
        dev.token_jti = "revoked:" + dev.token_jti
        dev.revoked = True
        db.commit()
    audit(db, user.id, "logout", "user", str(user.id), {})
    db.commit()
    return {"ok": True}


@app.get("/auth/devices")
def devices(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [{"id": d.id, "device_name": d.device_name, "platform": d.platform,
             "trusted": d.trusted, "created_at": d.created_at.isoformat(),
             "last_active": d.last_active.isoformat() if d.last_active else None,
             "revoked": d.revoked}
            for d in db.query(m.Device).filter_by(user_id=user.id).order_by(m.Device.id.desc()).all()]


@app.post("/auth/devices/{device_id}/revoke")
def revoke_device(device_id: int, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    d = db.query(m.Device).filter_by(id=device_id, user_id=user.id).first()
    if not d:
        raise HTTPException(404, "Device not found.")
    d.revoked = True
    audit(db, user.id, "device_revoked", "device", str(device_id), {})
    db.commit()
    return {"ok": True}


@app.post("/auth/devices/revoke-others")
def revoke_others(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    latest = (db.query(m.Device).filter_by(user_id=user.id, revoked=False)
              .order_by(m.Device.id.desc()).first())
    q = db.query(m.Device).filter_by(user_id=user.id, revoked=False)
    if latest:
        q = q.filter(m.Device.id != latest.id)
    n = q.update({"revoked": True})
    audit(db, user.id, "devices_revoked_others", "user", str(user.id), {"count": n})
    db.commit()
    return {"ok": True, "revoked": n}


@app.post("/auth/password")
def change_password(payload: dict, user: m.User = Depends(get_current_user),
                    device: m.Device = Depends(get_current_device), db: Session = Depends(get_db)):
    """Password change. From an *untrusted* device (v3 device trust), a fresh
    OTP to the email/phone on record is required in the same request
    ({otp_channel, otp_address, otp_code}) — request one first via
    POST /auth/otp/request with purpose 'password_change'. Accounts with no
    email/phone on record fall back to current-password only."""
    if not verify_password(payload.get("current_password", ""), user.password_hash):
        raise HTTPException(400, "Current password is wrong.")
    if not device.trusted and (user.email or user.phone):
        code = payload.get("otp_code")
        channel = payload.get("otp_channel")
        address = (payload.get("otp_address") or "").strip()
        if not code:
            raise HTTPException(400, "Untrusted device: a fresh otp_code is required. "
                                     "Request one via POST /auth/otp/request (purpose password_change).")
        # the OTP must be for this account's own email/phone — never someone else's
        own = user.email if channel == "email" else user.phone
        if not own or address.lower() != (own or "").lower():
            raise HTTPException(400, "OTP must be sent to the email/phone on this account.")
        consume_otp(db, channel, address, code, purpose="password_change")
        device.trusted = True
        device.verified_at = utcnow()
        audit(db, user.id, "device_trusted", "device", str(device.id),
              {"via": "password_change_otp"})
    user.password_hash = hash_password(payload.get("new_password", ""))
    audit(db, user.id, "password_changed", "user", str(user.id), {})
    db.commit()
    return {"ok": True}


@app.post("/auth/otp/request")
def otp_request(payload: dict, db: Session = Depends(get_db)):
    """Issue a one-time code via the configured VerificationProvider (dev
    provider returns the code in-band)."""
    return issue_otp(db, payload.get("channel"), payload.get("address"),
                     purpose=payload.get("purpose", "signup"))


@app.post("/auth/otp/verify")
def otp_verify(payload: dict, db: Session = Depends(get_db)):
    consume_otp(db, payload.get("channel"), payload.get("address"),
                payload.get("code"), purpose=payload.get("purpose") or None)
    return {"ok": True, "verified": True}


@app.post("/auth/devices/verify")
def verify_device(payload: dict, user: m.User = Depends(get_current_user),
                  device: m.Device = Depends(get_current_device), db: Session = Depends(get_db)):
    """Mark the current device trusted after an OTP to the user's own
    email/phone (purpose 'device')."""
    channel = payload.get("channel")
    address = (payload.get("address") or "").strip()
    own = user.email if channel == "email" else user.phone
    if not own or address.lower() != (own or "").lower():
        raise HTTPException(400, "Address must be the email/phone on this account.")
    consume_otp(db, channel, address, payload.get("code"), purpose="device")
    device.trusted = True
    device.verified_at = utcnow()
    audit(db, user.id, "device_trusted", "device", str(device.id), {"via": "device_verify"})
    db.commit()
    return {"ok": True, "trusted": True}


# --------------------------------------------------------------------- users

@app.get("/users/me")
def me(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = profile_out(db, user, user.id)
    p["online"] = True
    wallets = {w.currency: w.balance for w in db.query(m.Wallet).filter_by(user_id=user.id).all()}
    p["wallets"] = wallets
    p["is_admin"] = user.is_admin
    return p


@app.get("/users/search")
def user_search(q: str = Query(..., min_length=1, max_length=64),
                user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    rate_limit(f"usearch:{user.id}", 30, 60)
    ql = q.strip().lower()
    rows = (db.query(m.User)
            .filter(or_(m.User.username.like(ql + "%"), m.User.display_name.ilike(f"%{q.strip()}%")))
            .filter(m.User.id != user.id, m.User.is_suspended == False,
                    m.User.identifier_verified == True,
                    func.substr(m.User.username, 1, 8) != "pending_")
            .limit(20).all())
    out = []
    for u in rows:
        if is_blocked(db, user.id, u.id):
            continue
        p = profile_out(db, u, user.id)
        p["online"] = u.id in manager.active
        out.append(p)
    return out


@app.get("/users/{username}")
def get_user(username: str, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    u = db.query(m.User).filter_by(username=username.strip().lower()).first()
    if not u or u.is_suspended or not u.identifier_verified or u.username.startswith("pending_"):
        raise HTTPException(404, "User not found.")
    if is_blocked(db, user.id, u.id):
        raise HTTPException(404, "User not found.")
    p = profile_out(db, u, user.id)
    p["online"] = u.id in manager.active
    return p


@app.patch("/users/me")
async def update_me(payload: dict, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if "display_name" in payload:
        user.display_name = (payload["display_name"] or "").strip()[:64] or user.display_name
    if "username" in payload:
        # v3 username policy (ADR-002): 3-20 chars [a-z0-9_], NFKC-normalized,
        # reserved list, 30-day change cooldown, 30-day released-name hold.
        from identity import apply_username_change
        apply_username_change(db, user, payload["username"])
    if "utc_offset_minutes" in payload:
        user.utc_offset_minutes = max(-720, min(840, int(payload["utc_offset_minutes"])))
    db.commit()
    await bump_event(db, user.id, "profile_customized")
    return {"ok": True, "username": user.username}


@app.get("/users/me/settings")
def get_settings(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    out = dict(DEFAULT_SETTINGS)
    for row in db.query(m.UserSetting).filter_by(user_id=user.id).all():
        if row.key in SETTINGS_SCHEMA or row.key.startswith(("mute_", "pin_")):
            out[row.key] = row.value
    return out


@app.put("/users/me/settings/{key}")
def put_setting(key: str, payload: dict, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if key not in SETTINGS_SCHEMA and not (key.startswith("mute_") or key.startswith("pin_")):
        raise HTTPException(400, "Unknown setting.")
    value = payload.get("value")
    schema = SETTINGS_SCHEMA.get(key)
    if isinstance(schema, list) and value not in schema:
        raise HTTPException(400, f"value must be one of {schema}")
    if schema is bool and not isinstance(value, bool):
        raise HTTPException(400, "value must be boolean")
    row = db.query(m.UserSetting).filter_by(user_id=user.id, key=key).first()
    if row is None:
        row = m.UserSetting(user_id=user.id, key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()
    return {"ok": True, key: value}


@app.post("/users/block")
def block(payload: dict, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    target = db.get(m.User, int(payload.get("user_id", 0)))
    if not target or target.id == user.id:
        raise HTTPException(400, "Invalid user.")
    if db.query(m.Block).filter_by(blocker_id=user.id, blocked_id=target.id).first() is None:
        db.add(m.Block(blocker_id=user.id, blocked_id=target.id))
    audit(db, user.id, "user_blocked", "user", str(target.id), {})
    db.commit()
    return {"ok": True}


@app.post("/users/unblock")
def unblock(payload: dict, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(m.Block).filter_by(blocker_id=user.id, blocked_id=int(payload.get("user_id", 0))).delete()
    db.commit()
    return {"ok": True}


@app.get("/users/me/blocks")
def blocks(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(m.Block).filter_by(blocker_id=user.id).all()
    return [profile_out(db, db.get(m.User, b.blocked_id), user.id) for b in rows
            if db.get(m.User, b.blocked_id)]


@app.post("/reports")
def report(payload: dict, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.get("target_type") not in ("user", "message", "cosmetic"):
        raise HTTPException(400, "target_type must be user|message|cosmetic")
    db.add(m.Report(reporter_id=user.id, target_type=payload["target_type"],
                    target_id=str(payload.get("target_id")), reason=(payload.get("reason") or "")[:2000]))
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------- conversations

@app.post("/conversations")
async def create_conversation(payload: dict, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    rate_limit(f"conv:{user.id}", 20, 3600)
    member_ids: list[int] = []
    title = payload.get("title")
    if payload.get("user_id") or payload.get("username"):
        target = None
        if payload.get("user_id"):
            target = db.get(m.User, int(payload["user_id"]))
        else:
            target = db.query(m.User).filter_by(username=str(payload["username"]).strip().lower()).first()
        if not target or target.id == user.id or target.is_suspended:
            raise HTTPException(400, "Invalid user.")
        if is_blocked(db, user.id, target.id):
            raise HTTPException(403, "Cannot start a conversation with this user.")
        # reuse existing 1:1
        existing = (db.query(m.Conversation)
                    .join(m.ConversationMember, m.ConversationMember.conversation_id == m.Conversation.id)
                    .filter(m.Conversation.is_group == False,
                            m.ConversationMember.user_id.in_([user.id, target.id]))
                    .group_by(m.Conversation.id)
                    .having(func.count(m.ConversationMember.user_id) == 2).first())
        if existing:
            return conv_out(db, existing, user.id)
        member_ids = [user.id, target.id]
    elif payload.get("member_ids"):
        member_ids = sorted(set([user.id] + [int(x) for x in payload["member_ids"]][:49]))
        for mid in member_ids:
            if mid != user.id and is_blocked(db, user.id, mid):
                raise HTTPException(403, "Cannot add a blocked user.")
    else:
        raise HTTPException(400, "Provide user_id/username or member_ids.")
    conv = m.Conversation(is_group=len(member_ids) > 2, title=title, created_by=user.id)
    db.add(conv)
    db.flush()
    for mid in member_ids:
        db.add(m.ConversationMember(conversation_id=conv.id, user_id=mid))
    db.commit()
    audit(db, user.id, "conversation_created", "conversation", str(conv.id), {"members": member_ids})
    db.commit()
    if len(member_ids) == 2:
        other = member_ids[0] if member_ids[1] == user.id else member_ids[1]
        await bump_event(db, other, "friend_added")
        await bump_event(db, user.id, "friend_added")
        db.commit()
    return conv_out(db, conv, user.id)


@app.get("/conversations")
def list_conversations(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    # shadow memberships (pending message requests you received) are excluded:
    # they surface via GET /requests/inbox instead.
    member_conv_ids = [r.conversation_id for r in
                       db.query(m.ConversationMember.conversation_id)
                       .filter_by(user_id=user.id, hidden=False).all()]
    convs = (db.query(m.Conversation).filter(m.Conversation.id.in_(member_conv_ids))
             .order_by(m.Conversation.updated_at.desc()).limit(100).all())
    out = [conv_out(db, c, user.id) for c in convs]
    # pinned first, then newest
    out.sort(key=lambda c: (not c["pinned"], c["updated_at"]), reverse=False)
    return out


# ------------------------------------------------------------------ messages

async def update_streak_and_friendship(db: Session, conv: m.Conversation, sender_id: int):
    """Two-sided streak: a UTC day counts only when both sides sent a message."""
    if conv.is_group:
        return
    members = [r.user_id for r in db.query(m.ConversationMember.user_id)
               .filter_by(conversation_id=conv.id).all()]
    if len(members) != 2:
        return
    a, b = streak_pair(members[0], members[1])
    day = today_utc()
    sd = db.query(m.StreakDay).filter_by(user_a=a, user_b=b, day=day).first()
    if sd is None:
        sd = m.StreakDay(user_a=a, user_b=b, day=day)
        db.add(sd)
        db.flush()
    if sender_id == a:
        sd.a_sent = True
    else:
        sd.b_sent = True
    db.flush()
    if not (sd.a_sent and sd.b_sent):
        return
    streak = db.query(m.Streak).filter_by(user_a=a, user_b=b).first()
    if streak is None:
        streak = m.Streak(user_a=a, user_b=b)
        db.add(streak)
        db.flush()
    if streak.last_active_day == day:
        return  # already counted today
    yesterday = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    if streak.last_active_day == yesterday:
        streak.count += 1
    else:
        streak.count = 1
    streak.last_active_day = day
    streak.longest = max(streak.longest, streak.count)
    db.flush()
    for uid in (a, b):
        bump_stat(db, uid, "ach_streak_days", 0)  # ensure row
        # set the achievement counter to the current streak count
        stat = db.query(m.UserStat).filter_by(user_id=uid, key="ach_streak_days").first()
        stat.value = max(stat.value, streak.count)
        await check_achievements(db, uid, "streak_days")
        sset = get_setting(db, uid, "streak_notifications")
        if sset and streak.count in (3, 7, 14, 30, 60, 100, 365):
            other = db.get(m.User, b if uid == a else a)
            name = other.display_name if other else "friend"
            await notify(db, uid, "streak", f"🔥 {streak.count}-day streak!",
                         f"You and {name} kept the flame alive.",
                         {"kind": "streak", "count": streak.count, "with_user_id": other.id if other else None},
                         event_name="streak.updated")
    # friendship milestones
    fs = db.query(m.FriendshipStat).filter_by(user_a=a, user_b=b).first()
    if fs is None:
        fs = m.FriendshipStat(user_a=a, user_b=b)
        db.add(fs)
        db.flush()
    fs.message_count += 1
    if fs.first_message_at is None:
        fs.first_message_at = utcnow()
    db.flush()
    await check_friendship_milestones(db, fs, a, b)


async def check_friendship_milestones(db: Session, fs: m.FriendshipStat, a: int, b: int):
    unlocked = set(fs.milestones or [])
    pending: list[tuple[str, str, str, int]] = []

    def grant(key: str, title: str, body: str, shards: int):
        if key in unlocked:
            return
        unlocked.add(key)
        pending.append((key, title, body, shards))

    n = fs.message_count
    if n == 1:
        grant("first_message", "First message exchanged 💬", "A conversation begins.", 10)
    if n >= 100:
        grant("msg_100", "100 messages together", "That's a real conversation.", 50)
    if fs.first_message_at:
        days = (utcnow() - fs.first_message_at).days
        if days >= 7:
            grant("week_1", "1 week connected", "Seven days of staying in touch.", 75)
        if days >= 30:
            grant("days_30", "30 days connected", "A month of friendship.", 150)
        if days >= 100:
            grant("days_100", "100 days connected", "Some bonds just last.", 300)
        if days >= 365:
            grant("year_1", "1 year connected 🎉", "A whole year of you two.", 600)
    fs.milestones = sorted(unlocked)
    db.flush()
    for key, title, body, shards in pending:
        for uid in (a, b):
            credit(db, uid, "shards", shards, f"milestone:{key}", "reward", key)
            await notify(db, uid, "reward", title, body, {"kind": "milestone", "key": key})
    db.flush()


@app.post("/conversations/{conv_id}/messages")
async def send_message(conv_id: int, payload: dict,
                       user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    rate_limit(f"msg:{user.id}", 60, 60)
    conv = require_member(db, conv_id, user.id)
    kind = payload.get("kind", "text")
    if kind not in ("text", "image", "video", "sticker", "gif", "file"):
        raise HTTPException(400, "Unsupported message kind.")
    if kind == "text" and not (payload.get("body") or "").strip():
        raise HTTPException(400, "Message body required.")
    if kind in ("image", "video", "file") and not payload.get("media_path"):
        raise HTTPException(400, "media_path required. Upload via POST /media/upload first.")
    # v3 idempotent send: a retry with the same client_msg_id returns the
    # original message (200, duplicate: true) instead of a double-send.
    client_msg_id = payload.get("client_msg_id")
    if client_msg_id:
        try:
            uuid.UUID(str(client_msg_id))
        except ValueError:
            raise HTTPException(400, "client_msg_id must be a uuid.")
        existing = db.query(m.Message).filter_by(
            conversation_id=conv_id, sender_id=user.id, client_msg_id=str(client_msg_id)).first()
        if existing:
            out = message_out(db, existing, user.id)
            out["duplicate"] = True
            return out
    # bubble cosmetic at send time (visual only) — snapshot sender's active bubble
    bubble_id = payload.get("cosmetic_id")
    if not bubble_id:
        active = db.query(m.Loadout).filter_by(user_id=user.id, is_active=True).first()
        if active:
            item = db.query(m.LoadoutItem).filter_by(loadout_id=active.id, slot="BUBBLE").first()
            bubble_id = item.cosmetic_id if item else None
    if bubble_id:
        c = db.get(m.Cosmetic, bubble_id)
        if not c or c.category != "chat.bubble" or not has_entitlement(db, user.id, bubble_id):
            raise HTTPException(400, "You don't own that bubble.")
    send_effect_id = payload.get("send_effect_id")
    if send_effect_id and not has_entitlement(db, user.id, send_effect_id):
        raise HTTPException(400, "You don't own that send effect.")
    # v3: while a message request is pending on this conversation, new
    # messages from the sender stay hidden until the recipient accepts.
    pending_req = db.query(m.MessageRequest).filter_by(
        conversation_id=conv_id, status="pending").first() is not None
    seq = next_seq(db, conv)
    msg = m.Message(conversation_id=conv_id, sender_id=user.id, kind=kind,
                    body=(payload.get("body") or "")[:8000] if kind == "text" else (payload.get("body") or "")[:500],
                    media_path=payload.get("media_path"), media_mime=payload.get("media_mime"),
                    media_size=payload.get("media_size"),
                    sticker_pack_id=payload.get("sticker_pack_id"), sticker_id=payload.get("sticker_id"),
                    reply_to_id=payload.get("reply_to_id") or payload.get("reply_to"), cosmetic_id=bubble_id,
                    send_effect_id=send_effect_id, server_sequence=seq,
                    client_msg_id=str(client_msg_id) if client_msg_id else None,
                    hidden=pending_req)
    db.add(msg)
    db.flush()
    conv.updated_at = utcnow()
    member_ids = [r.user_id for r in db.query(m.ConversationMember.user_id)
                  .filter_by(conversation_id=conv_id).all()]
    for mid in member_ids:
        if mid != user.id:
            db.add(m.MessageStatus(message_id=msg.id, user_id=mid, state="delivered"))
    db.commit()
    await update_streak_and_friendship(db, conv, user.id)
    await bump_event(db, user.id, "message_sent")
    leveled = award_xp(db, user, 2, "message_sent")
    db.commit()
    out = message_out(db, msg, user.id)
    evt = {"type": "message.new", "message": out,
           "style": resolve_chat_style(db, user.id, conv_id)}
    await manager.broadcast_to_users(member_ids, evt, exclude=user.id)
    for mid in member_ids:
        if mid == user.id:
            continue
        if get_setting(db, mid, "notification_preview") == "none":
            continue
        if db.query(m.UserSetting).filter_by(user_id=mid, key=f"mute_{conv_id}").first():
            continue
        await notify(db, mid, "message", user.display_name,
                     (msg.body[:80] if msg.kind == "text" else f"Sent a {msg.kind}")
                     if get_setting(db, mid, "notification_preview") == "full" else "New message",
                     {"kind": "message", "conversation_id": conv_id, "message_id": msg.id},
                     event_name="message.new")
    db.commit()
    out["leveled_up"] = leveled
    return out


@app.get("/conversations/{conv_id}/messages")
def list_messages(conv_id: int, before: int | None = None, limit: int = Query(50, le=100),
                  user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_member(db, conv_id, user.id)
    # hidden messages (pending request) are only visible to their sender
    q = db.query(m.Message).filter(m.Message.conversation_id == conv_id,
                                   or_(m.Message.hidden == False, m.Message.sender_id == user.id))
    if before:
        q = q.filter(m.Message.id < before)
    msgs = q.order_by(m.Message.id.desc()).limit(limit).all()
    return [message_out(db, x, user.id) for x in reversed(msgs)]


@app.patch("/conversations/{conv_id}/messages/{mid}")
async def edit_message(conv_id: int, mid: int, payload: dict,
                       user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_member(db, conv_id, user.id)
    msg = db.get(m.Message, mid)
    if not msg or msg.conversation_id != conv_id or msg.sender_id != user.id:
        raise HTTPException(404, "Message not found.")
    if msg.kind != "text" or msg.deleted:
        raise HTTPException(400, "Only own text messages can be edited.")
    if (utcnow() - msg.created_at).total_seconds() > 15 * 60:
        raise HTTPException(400, "Edit window (15 min) has passed.")
    msg.body = (payload.get("body") or "")[:8000]
    msg.edited_at = utcnow()
    db.commit()
    out = message_out(db, msg, user.id)
    member_ids = [r.user_id for r in db.query(m.ConversationMember.user_id)
                  .filter_by(conversation_id=conv_id).all()]
    await manager.broadcast_to_users(member_ids, {"type": "message.edit", "message": out}, exclude=user.id)
    return out


@app.delete("/conversations/{conv_id}/messages/{mid}")
async def delete_message(conv_id: int, mid: int,
                         user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_member(db, conv_id, user.id)
    msg = db.get(m.Message, mid)
    if not msg or msg.conversation_id != conv_id or msg.sender_id != user.id:
        raise HTTPException(404, "Message not found.")
    msg.deleted = True
    msg.body = None
    db.commit()
    member_ids = [r.user_id for r in db.query(m.ConversationMember.user_id)
                  .filter_by(conversation_id=conv_id).all()]
    await manager.broadcast_to_users(member_ids, {"type": "message.delete",
                                                  "conversation_id": conv_id, "message_id": mid},
                                     exclude=user.id)
    return {"ok": True}


@app.post("/conversations/{conv_id}/messages/{mid}/reactions")
async def add_reaction(conv_id: int, mid: int, payload: dict,
                       user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_member(db, conv_id, user.id)
    msg = db.get(m.Message, mid)
    if not msg or msg.conversation_id != conv_id or msg.deleted:
        raise HTTPException(404, "Message not found.")
    emoji = (payload.get("emoji") or "")[:16]
    if not emoji:
        raise HTTPException(400, "emoji required.")
    effect_id = payload.get("effect_id")
    if effect_id and not has_entitlement(db, user.id, effect_id):
        raise HTTPException(400, "You don't own that reaction effect.")
    if db.query(m.Reaction).filter_by(message_id=mid, user_id=user.id, emoji=emoji).first() is None:
        db.add(m.Reaction(message_id=mid, user_id=user.id, emoji=emoji, effect_id=effect_id))
    db.commit()
    await bump_event(db, user.id, "reaction_sent")
    member_ids = [r.user_id for r in db.query(m.ConversationMember.user_id)
                  .filter_by(conversation_id=conv_id).all()]
    await manager.broadcast_to_users(member_ids, {"type": "reaction.added", "message_id": mid,
                                                  "emoji": emoji, "user_id": user.id,
                                                  "effect_id": effect_id}, exclude=user.id)
    return {"ok": True}


@app.delete("/conversations/{conv_id}/messages/{mid}/reactions")
async def remove_reaction(conv_id: int, mid: int, emoji: str = Query(...),
                          user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_member(db, conv_id, user.id)
    db.query(m.Reaction).filter_by(message_id=mid, user_id=user.id, emoji=emoji).delete()
    db.commit()
    member_ids = [r.user_id for r in db.query(m.ConversationMember.user_id)
                  .filter_by(conversation_id=conv_id).all()]
    await manager.broadcast_to_users(member_ids, {"type": "reaction.removed", "message_id": mid,
                                                  "emoji": emoji, "user_id": user.id}, exclude=user.id)
    return {"ok": True}


@app.post("/conversations/{conv_id}/messages/{mid}/forward")
async def forward_message(conv_id: int, mid: int, payload: dict,
                          user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_member(db, conv_id, user.id)
    target_id = int(payload.get("target_conv_id", 0))
    target = require_member(db, target_id, user.id)
    src = db.get(m.Message, mid)
    if not src or src.conversation_id != conv_id or src.deleted:
        raise HTTPException(404, "Message not found.")
    seq = next_seq(db, target)
    msg = m.Message(conversation_id=target_id, sender_id=user.id, kind=src.kind, body=src.body,
                    media_path=src.media_path, media_mime=src.media_mime, forwarded=True,
                    server_sequence=seq)
    db.add(msg)
    db.flush()
    target.updated_at = utcnow()
    db.commit()
    out = message_out(db, msg, user.id)
    member_ids = [r.user_id for r in db.query(m.ConversationMember.user_id)
                  .filter_by(conversation_id=target_id).all()]
    await manager.broadcast_to_users(member_ids, {"type": "message.new", "message": out}, exclude=user.id)
    return out


@app.post("/conversations/{conv_id}/messages/{mid}/pin")
def pin_message(conv_id: int, mid: int, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_member(db, conv_id, user.id)
    if db.get(m.Message, mid) is None:
        raise HTTPException(404, "Message not found.")
    if db.query(m.PinnedMessage).filter_by(message_id=mid).first() is None:
        db.add(m.PinnedMessage(conversation_id=conv_id, message_id=mid, pinned_by=user.id))
    db.commit()
    return {"ok": True}


@app.get("/conversations/{conv_id}/pins")
def list_pins(conv_id: int, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_member(db, conv_id, user.id)
    pins = db.query(m.PinnedMessage).filter_by(conversation_id=conv_id).all()
    return [message_out(db, db.get(m.Message, p.message_id), user.id) for p in pins
            if db.get(m.Message, p.message_id)]


@app.post("/conversations/{conv_id}/read")
async def mark_read(conv_id: int, payload: dict,
                    user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_member(db, conv_id, user.id)
    last_id = int(payload.get("last_message_id", 0))
    row = db.query(m.ReadReceipt).filter_by(conversation_id=conv_id, user_id=user.id).first()
    if row is None:
        row = m.ReadReceipt(conversation_id=conv_id, user_id=user.id, last_read_message_id=last_id)
        db.add(row)
    else:
        row.last_read_message_id = max(row.last_read_message_id, last_id)
        row.updated_at = utcnow()
    db.query(m.MessageStatus).filter(m.MessageStatus.message_id.in_(
        db.query(m.Message.id).filter(m.Message.conversation_id == conv_id,
                                      m.Message.id <= last_id)),
        m.MessageStatus.user_id == user.id).update({"state": "read"}, synchronize_session=False)
    db.commit()
    member_ids = [r.user_id for r in db.query(m.ConversationMember.user_id)
                  .filter_by(conversation_id=conv_id).all()]
    if get_setting(db, user.id, "read_receipts"):
        await manager.broadcast_to_users(member_ids, {"type": "message.read", "conversation_id": conv_id,
                                                      "user_id": user.id, "last_message_id": last_id},
                                         exclude=user.id)
    return {"ok": True}


@app.post("/conversations/{conv_id}/typing")
async def typing(conv_id: int, payload: dict,
                 user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_member(db, conv_id, user.id)
    if not get_setting(db, user.id, "typing_indicators"):
        return {"ok": True}
    style = resolve_chat_style(db, user.id, conv_id)
    member_ids = [r.user_id for r in db.query(m.ConversationMember.user_id)
                  .filter_by(conversation_id=conv_id).all()]
    await manager.broadcast_to_users(member_ids, {"type": "typing.started" if payload.get("typing") else "typing.stopped",
                                                  "conversation_id": conv_id, "user_id": user.id,
                                                  "typing_effect_id": style.get("typing_effect_id")},
                                     exclude=user.id)
    return {"ok": True}


@app.get("/conversations/{conv_id}/search")
def search_messages(conv_id: int, q: str = Query(..., min_length=1),
                    user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_member(db, conv_id, user.id)
    rows = (db.query(m.Message).filter(m.Message.conversation_id == conv_id,
                                       m.Message.kind == "text", m.Message.deleted == False,
                                       m.Message.body.ilike(f"%{q}%"),
                                       or_(m.Message.hidden == False, m.Message.sender_id == user.id))
            .order_by(m.Message.id.desc()).limit(50).all())
    return [message_out(db, x, user.id) for x in reversed(rows)]


@app.get("/conversations/{conv_id}/draft")
def get_draft(conv_id: int, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_member(db, conv_id, user.id)
    d = db.query(m.ChatDraft).filter_by(conversation_id=conv_id, user_id=user.id).first()
    return {"content": d.content if d else ""}


@app.put("/conversations/{conv_id}/draft")
def put_draft(conv_id: int, payload: dict, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_member(db, conv_id, user.id)
    content = (payload.get("content") or "")[:4000]
    d = db.query(m.ChatDraft).filter_by(conversation_id=conv_id, user_id=user.id).first()
    if d is None:
        d = m.ChatDraft(conversation_id=conv_id, user_id=user.id, content=content)
        db.add(d)
    else:
        d.content = content
        d.updated_at = utcnow()
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------- media

ALLOWED_MIME = {"image/jpeg", "image/png", "image/gif", "image/webp",
                "video/mp4", "video/webm", "application/pdf"}


@app.post("/media/upload")
def upload_media(file: UploadFile = File(...), user: m.User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    rate_limit(f"upload:{user.id}", 30, 3600)
    mime = file.content_type or "application/octet-stream"
    if mime not in ALLOWED_MIME:
        raise HTTPException(400, "File type not allowed.")
    data = file.file.read()
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(400, "File too large (50MB max).")
    ext = Path(file.filename or "").suffix[:8] or {"image/jpeg": ".jpg"}.get(mime, ".bin")
    name = f"{secrets.token_hex(12)}{ext}"
    (MEDIA_DIR / name).write_bytes(data)
    audit(db, user.id, "media_uploaded", "media", name, {"mime": mime, "size": len(data)})
    db.commit()
    return {"media_path": f"media/{name}", "media_url": f"/media/{name}",
            "media_mime": mime, "media_size": len(data)}


# ------------------------------------------------------------------ realtime

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, token: str = Query(...)):
    user_id = user_id_from_token(token)
    if user_id is None:
        await websocket.close(code=4401)
        return
    await manager.connect(websocket, user_id)
    await manager.send_to_user(user_id, {"type": "presence.changed", "user_id": user_id, "online": True})
    try:
        while True:
            await websocket.receive_text()  # keepalive; client may send pings
    except Exception:
        pass
    finally:
        manager.disconnect(websocket, user_id)


# --------------------------------------------------------------------- misc

@app.get("/health")
def health():
    return {"ok": True, "service": "stip", "version": "1.0.0"}


# NOTE: StaticFiles mounts must be registered AFTER all routes (Talkies lesson:
# a "/" mount swallows API routes registered later and returns 405s).
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"


def _spa():
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


@app.on_event("startup")
def _startup():
    init_db()
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
    _spa()
