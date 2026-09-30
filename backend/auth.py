"""STIP backend — authentication.

JWT access tokens (6h) bound to a per-device session row. Passwords hashed
with bcrypt. Per-username failed-login counting with lockout (brute-force
protection). Rate limits are per-process (documented in README as a scale
note — a Redis-backed limiter is the extraction path).
"""
from __future__ import annotations

import datetime as dt
import os
import secrets
import time
from collections import defaultdict

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from db import get_db
from models import Device, User

JWT_SECRET = os.environ.get("STIP_JWT_SECRET", "dev-only-insecure-secret")
JWT_ALG = "HS256"
ACCESS_TTL = dt.timedelta(hours=6)

ADMINS = {u.strip().lower() for u in os.environ.get("STIP_ADMINS", "").split(",") if u.strip()}

security = HTTPBearer(auto_error=False)

_hits: dict[str, list[float]] = defaultdict(list)


def rate_limit(key: str, max_hits: int, window_s: int):
    now = time.time()
    bucket = [t for t in _hits[key] if now - t < window_s]
    if len(bucket) >= max_hits:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests, slow down.")
    bucket.append(now)
    _hits[key] = bucket


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


def issue_tokens(user: User, device_name: str, db: Session,
                 platform: str | None = None, trusted: bool = False) -> dict:
    jti = secrets.token_hex(16)
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(user.id),
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int((now + ACCESS_TTL).timestamp()),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)
    dev = Device(user_id=user.id, device_name=device_name or "unknown", token_jti=jti,
                 platform=platform, trusted=trusted,
                 verified_at=now.replace(tzinfo=None) if trusted else None)
    db.add(dev)
    db.commit()
    return {"access_token": token, "token_type": "bearer",
            "expires_in": int(ACCESS_TTL.total_seconds()), "jti": jti}


def get_current_device(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> Device:
    """The Device row behind the current bearer token."""
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credentials.")
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token.")
    device = db.query(Device).filter_by(token_jti=payload.get("jti"), revoked=False).first()
    if device is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session revoked, sign in again.")
    return device


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credentials.")
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired, sign in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token.")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account no longer exists.")
    device = db.query(Device).filter_by(token_jti=payload.get("jti"), revoked=False).first()
    if device is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session revoked, sign in again.")
    if user.is_suspended:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account suspended.")
    device.last_active = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    db.commit()
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only.")
    return user
