"""STIP backend — economy: wallet ledger, shop, purchases, gifting, daily rewards.

Server-authoritative (spec 4, 73-75): purchases go created → pending →
verified → granted; idempotency keys prevent double-grants; every currency
movement is an append-only ledger row. Real-money billing is an honest
placeholder — the dev provider verifies instantly; the pipeline shape is
production-shaped so a real provider can be swapped in.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models as m
from auth import get_current_user, rate_limit
from core import (audit, bump_event, credit, debit, get_wallet, grant_entitlement,
                  has_entitlement, local_day, notify, publish_due, utcnow)
from db import get_db

router = APIRouter()


def wallet_out(db: Session, user_id: int) -> dict:
    return {w.currency: w.balance for w in db.query(m.Wallet).filter_by(user_id=user_id).all()}


# ------------------------------------------------------------------ wallets

@router.get("/wallet")
def get_wallet_view(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    for cur in m.CURRENCIES:
        get_wallet(db, user.id, cur)
    db.commit()
    return {"balances": wallet_out(db, user.id)}


@router.get("/wallet/transactions")
def wallet_history(limit: int = 50, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(m.WalletTransaction).filter_by(user_id=user.id)
            .order_by(m.WalletTransaction.id.desc()).limit(min(limit, 200)).all())
    return [{"id": t.id, "currency": t.currency, "amount_delta": t.amount_delta,
             "balance_after": t.balance_after, "reason": t.reason, "source": t.source,
             "reference_id": t.reference_id, "created_at": t.created_at.isoformat()} for t in rows]


# --------------------------------------------------------------------- shop

@router.get("/shop")
def shop(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    # v3 publishing lifecycle: lazily flip due scheduled items to live
    publish_due(db)
    items = db.query(m.Cosmetic).filter_by(enabled=True, obtainable=True, status="live").all()
    purchasable = [c for c in items if c.acquisition == "purchase"]
    free_items = [c for c in items if c.acquisition == "free" and c.price_shards == 0 and c.price_gems == 0]
    owned = {e.cosmetic_id for e in db.query(m.Entitlement.cosmetic_id)
             .filter_by(user_id=user.id, status="active").all()}
    def out(c):
        return {"id": c.id, "category": c.category, "name": c.name, "rarity": c.rarity,
                "asset": c.asset, "performance_class": c.performance_class,
                "price_shards": c.price_shards, "price_gems": c.price_gems,
                "availability": c.availability, "theme_tags": c.theme_tags or [],
                "featured": c.featured, "set_id": c.set_id, "owned": c.id in owned,
                "expires_at": c.expires_at.isoformat() if c.expires_at else None}
    by_rarity = {r: [out(c) for c in purchasable if c.rarity == r] for r in m.RARITIES}
    bundles = [{"id": b.id, "name": b.name, "description": b.description,
                "cosmetic_ids": b.cosmetic_ids, "price_shards": b.price_shards,
                "price_gems": b.price_gems} for b in db.query(m.Bundle).filter_by(enabled=True).all()]
    packs = [{"id": p.id, "name": p.name, "gems": p.gems, "price_label": p.price_label}
             for p in db.query(m.CurrencyPack).filter_by(enabled=True).all()]
    return {
        "featured": [out(c) for c in purchasable if c.featured],
        "new": sorted([out(c) for c in purchasable], key=lambda x: x["id"])[-8:],
        "by_rarity": by_rarity,
        "bundles": bundles,
        "currency_packs": packs,
        "free": [out(c) for c in free_items if c.id not in owned],
    }


def _price(item) -> tuple[str, int]:
    if item.price_gems and item.price_shards:
        raise HTTPException(500, "Item has ambiguous pricing.")
    if item.price_gems:
        return "gems", item.price_gems
    if item.price_shards:
        return "shards", item.price_shards
    return "shards", 0


@router.post("/shop/purchase")
async def purchase(payload: dict, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Purchase flow: intent → verify → atomic grant → ledger (spec 74).
    Idempotent on idempotency_key (spec 75)."""
    rate_limit(f"purchase:{user.id}", 20, 3600)
    item_type = payload.get("item_type")
    item_id = payload.get("item_id")
    key = payload.get("idempotency_key") or secrets.token_hex(16)
    recipient_id = payload.get("recipient_id")  # gift-purchase: grant to a friend

    existing = db.query(m.Purchase).filter_by(idempotency_key=key).first()
    if existing:
        return {"ok": True, "purchase_id": existing.id, "status": existing.status, "duplicate": True}

    recipient = None
    if recipient_id:
        recipient = db.get(m.User, int(recipient_id))
        if not recipient or recipient.id == user.id:
            raise HTTPException(400, "Invalid gift recipient.")

    if item_type == "cosmetic":
        item = db.get(m.Cosmetic, item_id)
        if not item or not item.enabled or not item.obtainable \
                or item.acquisition not in ("purchase", "free") \
                or getattr(item, "status", "live") != "live":
            raise HTTPException(400, "Item not available for purchase.")
        currency, amount = _price(item)
        owner_id = recipient.id if recipient else user.id
        if has_entitlement(db, owner_id, item_id):
            raise HTTPException(400, "Already owned.")
        targets = [item_id]
    elif item_type == "bundle":
        item = db.get(m.Bundle, item_id)
        if not item or not item.enabled:
            raise HTTPException(400, "Bundle not available.")
        currency = "gems" if item.price_gems else "shards"
        amount = item.price_gems or item.price_shards
        owner_id = recipient.id if recipient else user.id
        targets = [c for c in (item.cosmetic_ids or []) if not has_entitlement(db, owner_id, c)]
        if not targets:
            raise HTTPException(400, "All bundle items already owned.")
    elif item_type == "currency_pack":
        item = db.get(m.CurrencyPack, item_id)
        if not item or not item.enabled:
            raise HTTPException(400, "Pack not available.")
        currency, amount, targets = "dev", 0, []
    else:
        raise HTTPException(400, "item_type must be cosmetic|bundle|currency_pack")

    purchase = m.Purchase(user_id=user.id, item_type=item_type, item_id=item_id,
                          price_currency=currency if currency != "dev" else "gems",
                          price_amount=amount, status="created",
                          idempotency_key=key, provider="dev")
    db.add(purchase)
    db.flush()

    try:
        # verify (dev provider: instant, honest placeholder for real billing)
        purchase.status = "pending"
        db.flush()
        purchase.status = "verified"
        purchase.verified_at = utcnow()
        db.flush()
        # atomic grant
        if amount > 0:
            debit(db, user.id, currency, amount, f"purchase:{item_id}", "purchase", str(purchase.id))
        if item_type == "currency_pack":
            credit(db, user.id, "gems", item.gems, f"pack:{item_id}", "purchase", str(purchase.id))
        else:
            for cid in targets:
                grant_entitlement(db, owner_id, cid, source="purchase", purchase_id=purchase.id)
        purchase.status = "granted"
        purchase.granted_at = utcnow()
        db.flush()
        audit(db, user.id, "purchase_granted", "purchase", str(purchase.id),
              {"item_type": item_type, "item_id": item_id, "recipient": owner_id})
        db.commit()
    except HTTPException:
        db.rollback()
        purchase.status = "failed"
        db.commit()
        raise

    await bump_event(db, user.id, "purchase_made")
    who = recipient.display_name if recipient else "you"
    await notify(db, user.id, "purchase", "Purchase complete ✅",
                 f"{item.name} is now yours." if not recipient else f"{item.name} gifted to {who}.",
                 {"kind": "purchase", "purchase_id": purchase.id})
    if recipient:
        await notify(db, recipient.id, "reward", f"🎁 {user.display_name} sent you a gift!",
                     item.name, {"kind": "gift", "purchase_id": purchase.id},
                     event_name="inventory.updated")
    db.commit()
    return {"ok": True, "purchase_id": purchase.id, "status": "granted",
            "balances": wallet_out(db, user.id)}


# ------------------------------------------------------------------ gifting

@router.post("/gifts")
async def send_gift(payload: dict, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Gift an owned, transferable cosmetic (spec 36)."""
    rate_limit(f"gift:{user.id}", 10, 3600)
    cosmetic_id = payload.get("cosmetic_id")
    recipient = db.get(m.User, int(payload.get("recipient_id", 0)))
    if not recipient or recipient.id == user.id:
        raise HTTPException(400, "Invalid recipient.")
    c = db.get(m.Cosmetic, cosmetic_id)
    if not c or not c.enabled:
        raise HTTPException(400, "Cosmetic not available.")
    if not has_entitlement(db, user.id, cosmetic_id):
        raise HTTPException(400, "You don't own this cosmetic.")
    if has_entitlement(db, recipient.id, cosmetic_id):
        raise HTTPException(400, "They already own it.")
    if not c.transferable:
        raise HTTPException(400, "This item can't be gifted.")
    gift = m.GiftTransaction(sender_id=user.id, recipient_id=recipient.id,
                             cosmetic_id=cosmetic_id, message=(payload.get("message") or "")[:256])
    db.add(gift)
    db.flush()
    # transfer ownership
    db.query(m.Entitlement).filter_by(user_id=user.id, cosmetic_id=cosmetic_id).delete()
    grant_entitlement(db, recipient.id, cosmetic_id, source="gift", gift_id=gift.id)
    gift.status = "completed"
    gift.completed_at = utcnow()
    audit(db, user.id, "gift_sent", "gift", str(gift.id),
          {"cosmetic_id": cosmetic_id, "recipient": recipient.id})
    db.commit()
    await bump_event(db, user.id, "gift_sent")
    await bump_event(db, recipient.id, "gift_received")
    await notify(db, recipient.id, "reward", f"🎁 {user.display_name} sent you {c.name}!",
                 payload.get("message") or "", {"kind": "gift", "gift_id": gift.id},
                 event_name="inventory.updated")
    db.commit()
    return {"ok": True, "gift_id": gift.id}


@router.get("/gifts")
def gift_history(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(m.GiftTransaction)
            .filter((m.GiftTransaction.sender_id == user.id) | (m.GiftTransaction.recipient_id == user.id))
            .order_by(m.GiftTransaction.id.desc()).limit(50).all())
    return [{"id": g.id, "sender_id": g.sender_id, "recipient_id": g.recipient_id,
             "cosmetic_id": g.cosmetic_id, "status": g.status, "message": g.message,
             "created_at": g.created_at.isoformat()} for g in rows]


# ------------------------------------------------------------- daily rewards

@router.get("/rewards/daily")
def daily_status(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    day = local_day(user.utc_offset_minutes)
    claimed = db.query(m.DailyClaim).filter_by(user_id=user.id, claim_date=day).first() is not None
    last = (db.query(m.DailyClaim).filter_by(user_id=user.id)
            .order_by(m.DailyClaim.id.desc()).first())
    ladder = db.query(m.DailyReward).order_by(m.DailyReward.day).all()
    next_day = 1
    if last:
        next_day = (last.day_number % 30) + 1
    return {
        "today": day, "claimed": claimed, "next_day": next_day,
        "ladder": [{"day": d.day, "shards": d.shards, "gems": d.gems,
                    "cosmetic_id": d.cosmetic_id} for d in ladder],
    }


@router.post("/rewards/daily/claim")
async def claim_daily(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Server-authoritative, idempotent, timezone-aware daily claim (spec 234)."""
    import datetime as dt
    rate_limit(f"daily:{user.id}", 5, 3600)
    day = local_day(user.utc_offset_minutes)
    if db.query(m.DailyClaim).filter_by(user_id=user.id, claim_date=day).first():
        raise HTTPException(400, "Already claimed today.")
    # streak continues if yesterday (local) was claimed
    yesterday_local = (dt.datetime.now(dt.timezone.utc)
                       + dt.timedelta(minutes=user.utc_offset_minutes)
                       - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    prev = db.query(m.DailyClaim).filter_by(user_id=user.id, claim_date=yesterday_local).first()
    day_number = ((prev.day_number % 30) + 1) if prev else 1
    ladder = db.get(m.DailyReward, day_number)
    if not ladder:
        raise HTTPException(500, "Reward ladder misconfigured.")
    claim = m.DailyClaim(user_id=user.id, claim_date=day, day_number=day_number)
    db.add(claim)
    db.flush()
    granted = {"shards": ladder.shards, "gems": ladder.gems, "cosmetic_id": ladder.cosmetic_id}
    if ladder.shards:
        credit(db, user.id, "shards", ladder.shards, f"daily:{day_number}", "daily", day)
    if ladder.gems:
        credit(db, user.id, "gems", ladder.gems, f"daily:{day_number}", "daily", day)
    if ladder.cosmetic_id:
        grant_entitlement(db, user.id, ladder.cosmetic_id, source="reward", reward_id=f"daily:{day_number}")
    audit(db, user.id, "daily_claimed", "daily_claim", str(claim.id),
          {"day": day, "day_number": day_number})
    db.commit()
    await bump_event(db, user.id, "daily_claimed")
    leveled = False
    if day_number in (7, 14, 30):
        from core import award_xp
        leveled = award_xp(db, user, 10, "daily_milestone")
    await notify(db, user.id, "reward", f"Daily reward — day {day_number} 🎁",
                 "Come back tomorrow to keep the streak going.",
                 {"kind": "daily", "day_number": day_number, "granted": granted},
                 event_name="reward.granted")
    db.commit()
    return {"ok": True, "day_number": day_number, "granted": granted,
            "balances": wallet_out(db, user.id), "leveled_up": leveled}
