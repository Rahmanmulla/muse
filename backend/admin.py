"""STIP backend — admin: cosmetics, events, economy, flags, audit, users (spec 81-83, 227)."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models as m
from auth import require_admin
from core import audit, credit, debit, utcnow
from db import get_db

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])

# ------------------------------------------------------------------ cosmetics
# v3 publishing lifecycle: draft → review → scheduled → live → retired.
# Re-release goes retired → draft. Direct review → live is allowed for
# editorial fast-track; scheduled items flip to live lazily at publish_at
# (core.publish_due) when the catalog/shop/collection is read.
PUBLISH_STATUSES = {"draft", "review", "scheduled", "live", "retired"}
PUBLISH_TRANSITIONS = {
    "draft": {"review", "live"},
    "review": {"draft", "scheduled", "live"},
    "scheduled": {"draft", "live"},
    "live": {"retired", "draft"},
    "retired": {"draft"},
}

@router.post("/cosmetics")
def create_cosmetic(payload: dict, admin: m.User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.get(m.Cosmetic, payload.get("id")):
        raise HTTPException(400, "Cosmetic id already exists.")
    if payload.get("category") not in m.COSMETIC_CATEGORIES:
        raise HTTPException(400, f"Unknown category. Valid: {m.COSMETIC_CATEGORIES}")
    if payload.get("rarity", "common") not in m.RARITIES:
        raise HTTPException(400, f"Unknown rarity. Valid: {m.RARITIES}")
    # v3 publishing lifecycle: new items start as draft unless a status is given
    status = payload.get("status", "draft")
    if status not in PUBLISH_STATUSES:
        raise HTTPException(400, f"Unknown status. Valid: {sorted(PUBLISH_STATUSES)}")
    publish_at = None
    if payload.get("publish_at"):
        try:
            publish_at = dt.datetime.fromisoformat(str(payload["publish_at"]))
        except ValueError:
            raise HTTPException(400, "publish_at must be ISO-8601.")
    if status == "scheduled" and not publish_at:
        raise HTTPException(400, "scheduled requires publish_at.")
    c = m.Cosmetic(
        id=payload["id"], category=payload["category"], name=payload.get("name", payload["id"]),
        description=payload.get("description", ""), rarity=payload.get("rarity", "common"),
        asset=payload.get("asset", {}), asset_hash=payload.get("asset_hash", ""),
        performance_class=payload.get("performance_class", "P0"),
        fallback_id=payload.get("fallback_id"), theme_tags=payload.get("theme_tags", []),
        availability=payload.get("availability", "permanent"),
        acquisition=payload.get("acquisition", "free"),
        price_shards=int(payload.get("price_shards", 0)), price_gems=int(payload.get("price_gems", 0)),
        event_id=payload.get("event_id"), obtainable=payload.get("obtainable", True),
        transferable=payload.get("transferable", False), set_id=payload.get("set_id"),
        enabled=payload.get("enabled", True), featured=payload.get("featured", False),
        status=status, publish_at=publish_at)
    db.add(c)
    audit(db, admin.id, "cosmetic_created", "cosmetic", c.id,
          {"name": c.name, "status": status})
    db.commit()
    return {"ok": True, "id": c.id, "status": c.status}


@router.patch("/cosmetics/{cosmetic_id}")
def update_cosmetic(cosmetic_id: str, payload: dict, admin: m.User = Depends(require_admin),
                    db: Session = Depends(get_db)):
    c = db.get(m.Cosmetic, cosmetic_id)
    if not c:
        raise HTTPException(404, "Cosmetic not found.")
    for key in ("name", "description", "rarity", "asset", "asset_hash", "performance_class",
                "fallback_id", "theme_tags", "availability", "acquisition", "price_shards",
                "price_gems", "event_id", "obtainable", "transferable", "set_id",
                "enabled", "featured", "expires_at"):
        if key in payload:
            setattr(c, key, payload[key])
    # asset updates bump version — ownership is never removed by versioning (spec 160)
    if "asset" in payload:
        c.version += 1
    audit(db, admin.id, "cosmetic_updated", "cosmetic", cosmetic_id, {"fields": list(payload.keys())})
    db.commit()
    return {"ok": True, "version": c.version}


@router.post("/cosmetics/{cosmetic_id}/transition")
def transition_cosmetic(cosmetic_id: str, payload: dict, admin: m.User = Depends(require_admin),
                        db: Session = Depends(get_db)):
    """Move a cosmetic through the publishing lifecycle. All transitions are
    validated against PUBLISH_TRANSITIONS and audited."""
    c = db.get(m.Cosmetic, cosmetic_id)
    if not c:
        raise HTTPException(404, "Cosmetic not found.")
    to_status = payload.get("to_status")
    if to_status not in PUBLISH_STATUSES:
        raise HTTPException(400, f"Unknown status. Valid: {sorted(PUBLISH_STATUSES)}")
    from_status = c.status or "live"
    if to_status not in PUBLISH_TRANSITIONS.get(from_status, set()):
        raise HTTPException(400, f"Cannot transition {from_status} -> {to_status}.")
    publish_at = c.publish_at
    if payload.get("publish_at"):
        try:
            publish_at = dt.datetime.fromisoformat(str(payload["publish_at"]))
        except ValueError:
            raise HTTPException(400, "publish_at must be ISO-8601.")
    if to_status == "scheduled" and not publish_at:
        raise HTTPException(400, "scheduled requires publish_at.")
    c.status = to_status
    c.publish_at = publish_at
    if to_status == "retired":
        c.obtainable = False
        c.availability = "retired"
    audit(db, admin.id, "cosmetic_transition", "cosmetic", cosmetic_id,
          {"from": from_status, "to": to_status})
    db.commit()
    return {"ok": True, "status": c.status}


@router.post("/cosmetics/{cosmetic_id}/retire")
def retire_cosmetic(cosmetic_id: str, admin: m.User = Depends(require_admin), db: Session = Depends(get_db)):
    """Retire: existing owners keep it, new users see it as unavailable (spec 175)."""
    c = db.get(m.Cosmetic, cosmetic_id)
    if not c:
        raise HTTPException(404, "Cosmetic not found.")
    c.availability = "retired"
    c.obtainable = False
    c.status = "retired"
    audit(db, admin.id, "cosmetic_retired", "cosmetic", cosmetic_id, {})
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------- events

@router.post("/events")
def create_event(payload: dict, admin: m.User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.get(m.Event, payload.get("id")):
        raise HTTPException(400, "Event id already exists.")
    ev = m.Event(id=payload["id"], name=payload.get("name", payload["id"]),
                 description=payload.get("description", ""), theme=payload.get("theme", ""),
                 status=payload.get("status", "draft"), banner_asset=payload.get("banner_asset", {}),
                 challenges=payload.get("challenges", []), shop_items=payload.get("shop_items", []),
                 currency=payload.get("currency", "event_tokens"),
                 progression_track=payload.get("progression_track", {} if False else []),
                 feature_flags=payload.get("feature_flags", {}))
    db.add(ev)
    audit(db, admin.id, "event_created", "event", ev.id, {"status": ev.status})
    db.commit()
    return {"ok": True, "id": ev.id}


@router.patch("/events/{event_id}")
def update_event(event_id: str, payload: dict, admin: m.User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    ev = db.get(m.Event, event_id)
    if not ev:
        raise HTTPException(404, "Event not found.")
    old_status = ev.status
    for key in ("name", "description", "theme", "status", "start_at", "end_at",
                "banner_asset", "challenges", "shop_items", "currency",
                "progression_track", "feature_flags"):
        if key in payload:
            setattr(ev, key, payload[key])
    # guard: cannot silently go live without schedule review — require explicit status
    audit(db, admin.id, "event_updated", "event", event_id,
          {"from": old_status, "to": ev.status, "fields": list(payload.keys())})
    db.commit()
    return {"ok": True, "status": ev.status}


# ---------------------------------------------------------------------- flags

@router.get("/flags")
def list_flags(admin: m.User = Depends(require_admin), db: Session = Depends(get_db)):
    return [{"key": f.key, "description": f.description, "enabled": f.enabled,
             "rollout_percent": f.rollout_percent} for f in db.query(m.FeatureFlag).all()]


@router.put("/flags/{key}")
def set_flag(key: str, payload: dict, admin: m.User = Depends(require_admin), db: Session = Depends(get_db)):
    f = db.get(m.FeatureFlag, key)
    if not f:
        f = m.FeatureFlag(key=key)
        db.add(f)
    if "description" in payload:
        f.description = payload["description"]
    if "enabled" in payload:
        f.enabled = bool(payload["enabled"])
    if "rollout_percent" in payload:
        f.rollout_percent = max(0, min(100, int(payload["rollout_percent"])))
    audit(db, admin.id, "flag_updated", "feature_flag", key,
          {"enabled": f.enabled, "rollout": f.rollout_percent})
    db.commit()
    return {"ok": True, "key": key, "enabled": f.enabled, "rollout_percent": f.rollout_percent}


# -------------------------------------------------------------------- economy

@router.get("/economy/overview")
def economy_overview(admin: m.User = Depends(require_admin), db: Session = Depends(get_db)):
    from sqlalchemy import func
    totals = (db.query(m.Wallet.currency, func.sum(m.Wallet.balance))
              .group_by(m.Wallet.currency).all())
    purchases = db.query(m.Purchase).count()
    granted = db.query(m.Purchase).filter_by(status="granted").count()
    return {"total_balances": {c: int(s or 0) for c, s in totals},
            "purchases": purchases, "granted": granted}


@router.post("/purchases/{purchase_id}/refund")
async def refund_purchase(purchase_id: int, admin: m.User = Depends(require_admin),
                          db: Session = Depends(get_db)):
    """Refund flow: verify → revoke entitlements → reconcile wallet (spec 159)."""
    from core import notify
    p = db.get(m.Purchase, purchase_id)
    if not p:
        raise HTTPException(404, "Purchase not found.")
    if p.status == "refunded":
        raise HTTPException(400, "Already refunded.")
    if p.status != "granted":
        raise HTTPException(400, "Only granted purchases can be refunded.")
    # revoke entitlements granted by this purchase
    ents = db.query(m.Entitlement).filter_by(purchase_id=p.id, status="active").all()
    for e in ents:
        e.status = "revoked"
    if p.price_amount > 0:
        credit(db, p.user_id, p.price_currency, p.price_amount,
               f"refund:{p.id}", "refund", str(p.id))
    p.status = "refunded"
    p.refunded_at = utcnow()
    audit(db, admin.id, "purchase_refunded", "purchase", str(p.id),
          {"user_id": p.user_id, "revoked": len(ents)})
    db.commit()
    await notify(db, p.user_id, "purchase", "Purchase refunded",
                 f"{p.item_id} was refunded.", {"kind": "refund", "purchase_id": p.id})
    db.commit()
    return {"ok": True, "revoked": len(ents)}


@router.get("/reconciliation")
def reconciliation(admin: m.User = Depends(require_admin), db: Session = Depends(get_db)):
    """Verify ledger integrity: wallet balance == sum of ledger deltas (spec 230)."""
    from sqlalchemy import func
    issues = []
    wallets = db.query(m.Wallet).all()
    for w in wallets:
        total = db.query(func.sum(m.WalletTransaction.amount_delta)).filter_by(
            user_id=w.user_id, currency=w.currency).scalar() or 0
        if int(total) != w.balance:
            issues.append({"user_id": w.user_id, "currency": w.currency,
                           "wallet": w.balance, "ledger_sum": int(total)})
    return {"ok": len(issues) == 0, "issues": issues}


@router.post("/economy/grant")
def admin_grant(payload: dict, admin: m.User = Depends(require_admin), db: Session = Depends(get_db)):
    """Manual grant (support tooling, spec 229) — always audited."""
    user_id = int(payload.get("user_id", 0))
    if not db.get(m.User, user_id):
        raise HTTPException(400, "User not found.")
    if payload.get("currency") and payload.get("amount"):
        credit(db, user_id, payload["currency"], int(payload["amount"]),
               payload.get("reason", "admin_grant"), "admin", f"admin:{admin.id}")
    if payload.get("cosmetic_id"):
        from core import grant_entitlement
        grant_entitlement(db, user_id, payload["cosmetic_id"], source="admin")
    audit(db, admin.id, "admin_grant", "user", str(user_id), payload)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------- users

@router.get("/users")
def admin_users(q: str = "", admin: m.User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(m.User).filter(m.User.username.like(f"%{q}%")).limit(50).all()
    return [{"id": u.id, "username": u.username, "display_name": u.display_name,
             "is_admin": u.is_admin, "is_suspended": u.is_suspended,
             "created_at": u.created_at.isoformat()} for u in rows]


@router.post("/users/{user_id}/suspend")
def suspend_user(user_id: int, admin: m.User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(m.User, user_id)
    if not u:
        raise HTTPException(404, "User not found.")
    u.is_suspended = True
    db.query(m.Device).filter_by(user_id=user_id).update({"revoked": True})
    audit(db, admin.id, "user_suspended", "user", str(user_id), {})
    db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/unsuspend")
def unsuspend_user(user_id: int, admin: m.User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(m.User, user_id)
    if not u:
        raise HTTPException(404, "User not found.")
    u.is_suspended = False
    audit(db, admin.id, "user_unsuspended", "user", str(user_id), {})
    db.commit()
    return {"ok": True}


@router.get("/users/{user_id}/economy")
def user_economy(user_id: int, admin: m.User = Depends(require_admin), db: Session = Depends(get_db)):
    """Support inspection: ownership, purchases, rewards — never message content (spec 229)."""
    from economy import wallet_out
    ents = db.query(m.Entitlement).filter_by(user_id=user_id).all()
    txs = (db.query(m.WalletTransaction).filter_by(user_id=user_id)
           .order_by(m.WalletTransaction.id.desc()).limit(30).all())
    return {
        "balances": wallet_out(db, user_id),
        "entitlements": [{"cosmetic_id": e.cosmetic_id, "source": e.source,
                          "status": e.status, "granted_at": e.granted_at.isoformat()} for e in ents],
        "recent_transactions": [{"currency": t.currency, "amount_delta": t.amount_delta,
                                 "reason": t.reason, "source": t.source} for t in txs],
    }


@router.get("/audit")
def audit_log(action: str = "", limit: int = 100, admin: m.User = Depends(require_admin),
              db: Session = Depends(get_db)):
    q = db.query(m.AuditLog)
    if action:
        q = q.filter_by(action=action)
    rows = q.order_by(m.AuditLog.id.desc()).limit(min(limit, 500)).all()
    return [{"id": a.id, "actor_id": a.actor_id, "action": a.action,
             "target_type": a.target_type, "target_id": a.target_id,
             "details": a.details or {}, "created_at": a.created_at.isoformat()} for a in rows]


@router.get("/reports")
def list_reports(admin: m.User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(m.Report).order_by(m.Report.id.desc()).limit(100).all()
    return [{"id": r.id, "reporter_id": r.reporter_id, "target_type": r.target_type,
             "target_id": r.target_id, "reason": r.reason, "status": r.status,
             "created_at": r.created_at.isoformat()} for r in rows]


@router.post("/reports/{report_id}")
def handle_report(report_id: int, payload: dict, admin: m.User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    r = db.get(m.Report, report_id)
    if not r:
        raise HTTPException(404, "Report not found.")
    if payload.get("status") in ("open", "reviewed", "actioned", "dismissed"):
        r.status = payload["status"]
    audit(db, admin.id, "report_handled", "report", str(report_id), {"status": r.status})
    db.commit()
    return {"ok": True}
