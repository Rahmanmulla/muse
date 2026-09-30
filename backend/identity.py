"""STIP backend — v3 identity: signup state machine, account recovery,
username changes, referrals (ADR-002).

Signup (identifier-first):
  POST /auth/signup/start    {identifier}            -> shell user + signup session + OTP
  POST /auth/signup/verify   {signup_token, channel, address, code}
  POST /auth/signup/username {signup_token, username}
  POST /auth/signup/complete {signup_token, password, display_name?, device_name?, platform?}

The legacy POST /auth/signup (username+password up front) still works but is
deprecated; legacy accounts are grandfathered as identifier-verified.

Recovery restores *access* only (resets the password); it never restores
messages or keys. Passwords are re-hashed server-side — the server never
sees, stores, or returns a recoverable credential.
"""
from __future__ import annotations

import datetime as dt
import re
import secrets
import unicodedata

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models as m
from auth import ADMINS, get_current_user, hash_password, issue_tokens, rate_limit
from core import audit, bump_event, credit, notify, utcnow
from db import get_db
from seed import grant_starter_kit
from verify import consume_otp, detect_channel, issue_otp

router = APIRouter()

# ------------------------------------------------------------------ usernames

V3_USERNAME_RE = re.compile(r"^[a-z0-9_]{3,20}$")
# per v3 spec: reserved names (case-insensitive, already lowercased by normalization)
V3_RESERVED = {"admin", "support", "stip", "system", "official", "staff", "help", "security"}
USERNAME_CHANGE_COOLDOWN_DAYS = 30
USERNAME_TOMBSTONE_DAYS = 30
SHELL_PREFIX = "pending_"

REFERRAL_REWARD = 50          # shards, both sides
REFERRAL_CREDITS_PER_30D = 20
REFEREE_MAX_AGE_DAYS = 7


def normalize_username(raw: str) -> str:
    return unicodedata.normalize("NFKC", raw or "").strip().lower()


def validate_username_v3(raw: str) -> str:
    """Strict v3 username policy: NFKC-normalized, 3-20 chars, [a-z0-9_],
    reserved list, never the shell prefix."""
    u = normalize_username(raw)
    if not V3_USERNAME_RE.match(u):
        raise HTTPException(
            422, "Username must be 3-20 chars: lowercase letters, digits, underscore.")
    if u in V3_RESERVED:
        raise HTTPException(422, "That username is reserved.")
    if u.startswith(SHELL_PREFIX):
        raise HTTPException(422, "That username is reserved.")
    return u


def username_available(db: Session, u: str, exclude_user_id: int | None = None) -> None:
    """Raise 400 if taken (case-insensitive — usernames are stored lowercase)
    or still on its 30-day released-name hold."""
    q = db.query(m.User).filter_by(username=u)
    if exclude_user_id:
        q = q.filter(m.User.id != exclude_user_id)
    if q.first():
        raise HTTPException(400, "Username is taken.")
    tomb = db.query(m.UsernameTombstone).filter_by(normalized=u).first()
    if tomb and (utcnow() - tomb.released_at).days < USERNAME_TOMBSTONE_DAYS:
        raise HTTPException(400, "That username was recently released and is on hold.")


def apply_username_change(db: Session, user: m.User, new_raw: str) -> str:
    """Cooldown (30d) → validate → tombstone old name → assign. Returns the new username."""
    if (user.username_changed_at
            and (utcnow() - user.username_changed_at).days < USERNAME_CHANGE_COOLDOWN_DAYS):
        raise HTTPException(400, "Username can be changed once every 30 days.")
    u = validate_username_v3(new_raw)
    if u == user.username:
        return u  # no-op
    username_available(db, u, exclude_user_id=user.id)
    old = user.username
    if old and not old.startswith(SHELL_PREFIX):
        # release the old name onto the 30-day hold
        if db.query(m.UsernameTombstone).filter_by(normalized=old).first() is None:
            db.add(m.UsernameTombstone(normalized=old, released_at=utcnow()))
    user.username = u
    user.username_changed_at = utcnow()
    db.flush()
    return u


# ------------------------------------------------------------ signup helpers

SESSION_TTL = dt.timedelta(hours=24)


def _get_session(db: Session, token: str) -> m.SignupSession:
    sess = db.query(m.SignupSession).filter_by(token=token or "").first()
    if not sess:
        raise HTTPException(404, "Signup session not found.")
    if sess.expires_at < utcnow():
        raise HTTPException(400, "Signup session expired, start over.")
    if sess.completed:
        raise HTTPException(400, "Signup already completed.")
    return sess


def _shell_user(db: Session, channel: str, address: str) -> m.User:
    """Find or create the un-loginable shell row for this identifier."""
    if channel == "email":
        user = db.query(m.User).filter_by(email=address).first()
    else:
        user = db.query(m.User).filter_by(phone=address).first()
    if user is None:
        user = m.User(
            username=f"{SHELL_PREFIX}{secrets.token_hex(4)}",
            display_name="New user",
            email=address if channel == "email" else None,
            phone=address if channel == "phone" else None,
            password_hash="!",  # never matches — shell can't log in
            identifier_verified=False,
        )
        db.add(user)
        db.flush()
        # wallets are created at complete (grant_starter_kit), not here
    return user


# ------------------------------------------------------------------- signup

@router.post("/auth/signup/start")
def signup_start(payload: dict, db: Session = Depends(get_db)):
    """Step 1: identifier-first. Creates the shell + session, sends the OTP."""
    identifier = (payload.get("identifier") or "").strip()
    if not identifier:
        raise HTTPException(400, "identifier is required (email or phone).")
    channel = detect_channel(identifier)
    address = identifier.lower() if channel == "email" else identifier
    rate_limit(f"signup_start:{channel}:{address}", 5, 3600)
    # already registered & verified? go log in.
    existing = (db.query(m.User).filter_by(email=address).first() if channel == "email"
                else db.query(m.User).filter_by(phone=address).first())
    if existing and existing.identifier_verified and not existing.username.startswith(SHELL_PREFIX):
        raise HTTPException(400, "That identifier is already registered. Log in instead.")
    user = _shell_user(db, channel, address)
    sess = db.query(m.SignupSession).filter_by(user_id=user.id).first()
    if sess is None or sess.expires_at < utcnow() or sess.completed:
        if sess:
            db.delete(sess)
            db.flush()
        sess = m.SignupSession(user_id=user.id, token=secrets.token_urlsafe(32),
                               channel=channel, address=address,
                               expires_at=utcnow() + SESSION_TTL)
        db.add(sess)
        db.commit()
    sent = issue_otp(db, channel, address, purpose="signup")
    audit(db, user.id, "signup_started", "user", str(user.id), {"channel": channel})
    db.commit()
    return {"ok": True, "signup_token": sess.token, **sent}


@router.post("/auth/signup/verify")
def signup_verify(payload: dict, db: Session = Depends(get_db)):
    """Step 2: verify the OTP → identifier_verified flips on the shell user."""
    sess = _get_session(db, payload.get("signup_token"))
    consume_otp(db, sess.channel, sess.address, payload.get("code"), purpose="signup")
    user = db.get(m.User, sess.user_id)
    user.identifier_verified = True
    sess.verified = True
    audit(db, user.id, "signup_verified", "user", str(user.id), {})
    db.commit()
    return {"ok": True, "verified": True, "signup_token": sess.token}


@router.post("/auth/signup/username")
def signup_username(payload: dict, db: Session = Depends(get_db)):
    """Step 3: reserve the username on the verified session."""
    sess = _get_session(db, payload.get("signup_token"))
    if not sess.verified:
        raise HTTPException(400, "Verify your identifier first.")
    user = db.get(m.User, sess.user_id)
    u = validate_username_v3(payload.get("username", ""))
    username_available(db, u)
    user.username = u  # shell name is random; no tombstone needed
    sess.username_reserved = True
    db.commit()
    return {"ok": True, "username": u}


@router.post("/auth/signup/complete")
async def signup_complete(payload: dict, db: Session = Depends(get_db)):
    """Step 4: set password + display name → real account, tokens issued.
    The device that completes signup is trusted."""
    sess = _get_session(db, payload.get("signup_token"))
    if not sess.verified:
        raise HTTPException(400, "Verify your identifier first.")
    if not sess.username_reserved:
        raise HTTPException(400, "Choose a username first.")
    user = db.get(m.User, sess.user_id)
    user.password_hash = hash_password(payload.get("password", ""))  # 400 if < 8 chars
    user.display_name = (payload.get("display_name") or user.username).strip()[:64]
    user.utc_offset_minutes = int(payload.get("utc_offset_minutes") or 0)
    if user.username in ADMINS:
        user.is_admin = True
    sess.completed = True
    db.flush()
    grant_starter_kit(db, user)
    credit(db, user.id, "shards", 100, "welcome_bonus", "reward", "welcome")
    db.commit()
    audit(db, user.id, "signup", "user", str(user.id), {"username": user.username, "v3": True})
    db.commit()
    tokens = issue_tokens(user, payload.get("device_name"), db,
                          platform=payload.get("platform"), trusted=True)
    db.query(m.Device).filter_by(user_id=user.id, token_jti=tokens["jti"]).update(
        {"verified_at": utcnow()})
    db.commit()
    await bump_event(db, user.id, "friend_added", 0)  # no-op warmup
    return {**tokens, "user_id": user.id, "username": user.username}


# ----------------------------------------------------------------- recovery

@router.post("/auth/recovery/start")
def recovery_start(payload: dict, db: Session = Depends(get_db)):
    """Begin recovery: look the account up by username/email/phone and send
    an OTP to the email/phone on record. Recovery restores *access* only."""
    identifier = (payload.get("identifier") or "").strip()
    if not identifier:
        raise HTTPException(400, "identifier is required.")
    rate_limit(f"recovery:{identifier.lower()}", 5, 3600)
    user = (db.query(m.User).filter_by(username=identifier.lower()).first()
            or db.query(m.User).filter_by(email=identifier.lower()).first()
            or db.query(m.User).filter_by(phone=identifier).first())
    if not user:
        # don't leak account existence
        return {"ok": True, "note": "If the account exists, a recovery code was sent."}
    if user.email:
        channel, address = "email", user.email
    elif user.phone:
        channel, address = "phone", user.phone
    else:
        raise HTTPException(400, "This account has no email or phone on record; contact support.")
    sent = issue_otp(db, channel, address, purpose="recovery")
    audit(db, user.id, "recovery_started", "user", str(user.id), {"channel": channel})
    db.commit()
    return {"ok": True, **sent}


@router.post("/auth/recovery/reset")
def recovery_reset(payload: dict, db: Session = Depends(get_db)):
    """Complete recovery: valid OTP → new password, all devices revoked,
    lockout cleared. Returns fresh tokens on the current device."""
    identifier = (payload.get("identifier") or "").strip()
    if not identifier:
        raise HTTPException(400, "identifier is required.")
    user = (db.query(m.User).filter_by(username=identifier.lower()).first()
            or db.query(m.User).filter_by(email=identifier.lower()).first()
            or db.query(m.User).filter_by(phone=identifier).first())
    if not user:
        raise HTTPException(400, "Invalid recovery code.")
    channel = "email" if user.email else "phone"
    address = user.email or user.phone
    consume_otp(db, channel, address, payload.get("code"), purpose="recovery")
    user.password_hash = hash_password(payload.get("new_password", ""))
    user.failed_logins = 0
    user.locked_until = None
    # revoke every device session — the recoverer starts clean
    db.query(m.Device).filter_by(user_id=user.id, revoked=False).update({"revoked": True})
    audit(db, user.id, "recovery_completed", "user", str(user.id), {})
    db.commit()
    tokens = issue_tokens(user, payload.get("device_name"), db,
                          platform=payload.get("platform"), trusted=True)
    return {**tokens, "user_id": user.id, "username": user.username}


# ------------------------------------------------------------- username flow

@router.get("/users/me/username/check")
def username_check(username: str = "", db: Session = Depends(get_db),
                   user: m.User = Depends(get_current_user)):
    """Validate + reserve-check a username without changing anything."""
    u = validate_username_v3(username)
    username_available(db, u, exclude_user_id=user.id)
    return {"ok": True, "username": u, "available": True}


@router.post("/users/me/username")
async def change_username(payload: dict, user: m.User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    """Dedicated username change: 30-day cooldown, 30-day released-name hold,
    audit + notification."""
    old = user.username
    new_u = apply_username_change(db, user, payload.get("username", ""))
    audit(db, user.id, "username_changed", "user", str(user.id),
          {"from": old, "to": new_u})
    db.commit()
    await notify(db, user.id, "security", "Username changed",
                 f"Your username is now @{new_u}. Your old name is held for 30 days.",
                 {"kind": "username", "old": old, "new": new_u})
    db.commit()
    return {"ok": True, "username": new_u}


# ----------------------------------------------------------------- referrals

def _referral_code(db: Session, user_id: int) -> m.ReferralCode:
    row = db.query(m.ReferralCode).filter_by(user_id=user_id).first()
    if row is None:
        for _ in range(5):
            code = f"STIP-{user_id}-{secrets.token_hex(2).upper()}"
            if not db.query(m.ReferralCode).filter_by(code=code).first():
                row = m.ReferralCode(user_id=user_id, code=code)
                db.add(row)
                db.commit()
                break
        else:
            raise HTTPException(500, "Could not mint a referral code.")
    return row


@router.get("/referrals/mine")
def referral_mine(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = _referral_code(db, user.id)
    since = utcnow() - dt.timedelta(days=30)
    credited = (db.query(m.ReferralUse).filter(m.ReferralUse.referrer_id == user.id,
                                               m.ReferralUse.credited_at >= since).count())
    total = db.query(m.ReferralUse).filter_by(referrer_id=user.id).count()
    return {"code": row.code, "credited_last_30d": credited, "total_credited": total,
            "reward_shards": REFERRAL_REWARD, "credit_limit_30d": REFERRAL_CREDITS_PER_30D}


@router.post("/referrals/apply")
async def referral_apply(payload: dict, user: m.User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Apply a referral code. Referee must be ≤7 days old; one code per
    account (UNIQUE referee guard); referrer credited ≤20/30d. Both sides
    get 50 shards via the ledger."""
    rate_limit(f"referral:{user.id}", 5, 3600)
    code = (payload.get("code") or "").strip().upper()
    row = db.query(m.ReferralCode).filter_by(code=code).first()
    if not row:
        raise HTTPException(400, "Invalid referral code.")
    if row.user_id == user.id:
        raise HTTPException(400, "You can't refer yourself.")
    if (utcnow() - user.created_at).days > REFEREE_MAX_AGE_DAYS:
        raise HTTPException(400, "Referral codes only apply within 7 days of signup.")
    if db.query(m.ReferralUse).filter_by(referee_id=user.id).first():
        raise HTTPException(400, "You've already applied a referral code.")
    since = utcnow() - dt.timedelta(days=30)
    credited = (db.query(m.ReferralUse).filter(m.ReferralUse.referrer_id == row.user_id,
                                               m.ReferralUse.credited_at >= since).count())
    if credited >= REFERRAL_CREDITS_PER_30D:
        raise HTTPException(400, "This referrer has hit their 30-day credit limit.")
    use = m.ReferralUse(referrer_id=row.user_id, referee_id=user.id, code=code)
    db.add(use)
    db.flush()
    credit(db, row.user_id, "shards", REFERRAL_REWARD, f"referral:{use.id}", "referral", code)
    credit(db, user.id, "shards", REFERRAL_REWARD, f"referral:{use.id}", "referral", code)
    audit(db, user.id, "referral_applied", "referral", code,
          {"referrer": row.user_id, "use_id": use.id})
    db.commit()
    await notify(db, row.user_id, "reward", "Referral credited! 🎉",
                 f"{user.display_name} joined with your code. +{REFERRAL_REWARD} shards.",
                 {"kind": "referral", "referee_id": user.id})
    db.commit()
    return {"ok": True, "rewarded_shards": REFERRAL_REWARD}
