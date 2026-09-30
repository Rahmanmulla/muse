"""STIP backend — verification provider interface (v3, ADR-002).

OTP delivery is provider-pluggable: the app asks the configured
VerificationProvider to send a code; today that provider is the dev
provider, which returns the code in-band (honest placeholder — the
response shape is production-shaped so a real SMS/email vendor can be
swapped in without changing callers).
"""
from __future__ import annotations

import abc
import datetime as dt
import secrets

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models as m
from auth import rate_limit
from core import utcnow

OTP_TTL = dt.timedelta(minutes=10)
OTP_RATE = (5, 600)  # 5 sends per 10 min per channel:address:purpose


class VerificationProvider(abc.ABC):
    """Contract for delivering a one-time verification code."""

    @abc.abstractmethod
    def send_code(self, *, channel: str, address: str, code: str, purpose: str) -> dict:
        """Deliver `code` to `address`. Returns provider metadata for the API response."""


class DevVerificationProvider(VerificationProvider):
    """Dev provider: no real delivery; the code is returned in-band so the
    client (and tests) can complete verification. Do not use in production."""

    def send_code(self, *, channel: str, address: str, code: str, purpose: str) -> dict:
        return {"dev_code": code, "note": "Dev mode: code returned in-band."}


_provider: VerificationProvider = DevVerificationProvider()


def get_verification_provider() -> VerificationProvider:
    return _provider


def set_verification_provider(provider: VerificationProvider) -> None:
    """Swap the delivery vendor (production wiring point)."""
    global _provider
    _provider = provider


def detect_channel(identifier: str) -> str:
    """email if it looks like an address, else phone."""
    return "email" if "@" in (identifier or "") else "phone"


def issue_otp(db: Session, channel: str, address: str, purpose: str = "signup") -> dict:
    """Create an OTP row and hand it to the provider. Rate-limited per
    channel:address:purpose. Returns the provider's response metadata."""
    address = (address or "").strip()
    if channel not in ("phone", "email") or not address:
        raise HTTPException(400, "channel must be phone|email with an address.")
    rate_limit(f"otp:{channel}:{address}:{purpose}", *OTP_RATE)
    code = f"{secrets.randbelow(900000) + 100000}"
    db.add(m.OtpCode(channel=channel, address=address, code=code,
                     purpose=purpose, expires_at=utcnow() + OTP_TTL))
    db.commit()
    sent = get_verification_provider().send_code(
        channel=channel, address=address, code=code, purpose=purpose)
    return {"ok": True, **sent}


def consume_otp(db: Session, channel: str, address: str, code: str,
                purpose: str | None = None) -> m.OtpCode:
    """Validate a code (single-use, expiry-checked) or raise 400."""
    address = (address or "").strip()
    q = (db.query(m.OtpCode)
         .filter_by(channel=channel, address=address, code=(code or "").strip(), consumed=False))
    if purpose:
        q = q.filter_by(purpose=purpose)
    row = q.order_by(m.OtpCode.id.desc()).first()
    if not row or row.expires_at < utcnow():
        raise HTTPException(400, "Invalid or expired code.")
    row.consumed = True
    db.commit()
    return row
