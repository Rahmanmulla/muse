"""STIP backend — cross-cutting core services.

Server-authoritative by construction: ownership, balances, rewards, rarity
are all decided here, never by client input. All currency movement goes
through the append-only ledger.
"""
from __future__ import annotations

import datetime as dt

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models as m
from ws import manager

# --------------------------------------------------------------------- time

def utcnow():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def local_day(offset_minutes: int) -> str:
    """User's local YYYY-MM-DD for daily rewards (spec 234: timezone-aware)."""
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=offset_minutes)).strftime("%Y-%m-%d")


def today_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


# -------------------------------------------------------------------- audit

def audit(db: Session, actor_id: int | None, action: str, target_type: str | None = None,
          target_id: str | None = None, details: dict | None = None):
    db.add(m.AuditLog(actor_id=actor_id, action=action, target_type=target_type,
                      target_id=str(target_id) if target_id is not None else None,
                      details=details or {}))
    db.flush()


# ---------------------------------------------------------------- notifications

async def notify(db: Session, user_id: int, ntype: str, title: str, body: str = "",
                 data: dict | None = None, event_name: str = "notification.new"):
    notif = m.Notification(user_id=user_id, type=ntype, title=title, body=body, data=data or {})
    db.add(notif)
    db.flush()
    await manager.send_to_user(user_id, {
        "type": event_name,
        "notification": {"id": notif.id, "type": ntype, "title": title, "body": body,
                         "data": data or {}, "created_at": notif.created_at.isoformat()},
    })
    return notif


# ------------------------------------------------------------ wallet ledger

def get_wallet(db: Session, user_id: int, currency: str) -> m.Wallet:
    w = db.query(m.Wallet).filter_by(user_id=user_id, currency=currency).first()
    if w is None:
        w = m.Wallet(user_id=user_id, currency=currency, balance=0)
        db.add(w)
        db.flush()
    return w


def credit(db: Session, user_id: int, currency: str, amount: int, reason: str,
           source: str, reference_id: str | None = None) -> m.WalletTransaction:
    """Add currency via append-only ledger (spec 73)."""
    if amount < 0:
        raise HTTPException(400, "Credit amount must be positive.")
    w = get_wallet(db, user_id, currency)
    w.balance += amount
    w.updated_at = utcnow()
    tx = m.WalletTransaction(user_id=user_id, currency=currency, amount_delta=amount,
                             balance_after=w.balance, reason=reason, source=source,
                             reference_id=reference_id)
    db.add(tx)
    db.flush()
    return tx


def debit(db: Session, user_id: int, currency: str, amount: int, reason: str,
          source: str, reference_id: str | None = None) -> m.WalletTransaction:
    """Subtract currency; never allow negative balances (spec 231)."""
    if amount < 0:
        raise HTTPException(400, "Debit amount must be positive.")
    w = get_wallet(db, user_id, currency)
    if w.balance < amount:
        raise HTTPException(400, f"Not enough {currency}.")
    w.balance -= amount
    w.updated_at = utcnow()
    tx = m.WalletTransaction(user_id=user_id, currency=currency, amount_delta=-amount,
                             balance_after=w.balance, reason=reason, source=source,
                             reference_id=reference_id)
    db.add(tx)
    db.flush()
    return tx


# --------------------------------------------------------------- entitlements

def has_entitlement(db: Session, user_id: int, cosmetic_id: str) -> bool:
    return db.query(m.Entitlement).filter_by(
        user_id=user_id, cosmetic_id=cosmetic_id, status="active").first() is not None


def grant_entitlement(db: Session, user_id: int, cosmetic_id: str, source: str,
                      purchase_id: int | None = None, event_id: str | None = None,
                      reward_id: str | None = None, gift_id: int | None = None) -> m.Entitlement | None:
    """Idempotent grant (spec 127). Returns None if already owned."""
    cosmetic = db.get(m.Cosmetic, cosmetic_id)
    if cosmetic is None or not cosmetic.enabled:
        raise HTTPException(400, "Cosmetic not available.")
    existing = db.query(m.Entitlement).filter_by(user_id=user_id, cosmetic_id=cosmetic_id).first()
    if existing is not None:
        return None
    ent = m.Entitlement(user_id=user_id, cosmetic_id=cosmetic_id, source=source,
                        purchase_id=purchase_id, event_id=event_id,
                        reward_id=reward_id, gift_id=gift_id)
    db.add(ent)
    db.flush()
    return ent


# ----------------------------------------------------------- stats / xp / ach

ACHIEVEMENT_EVENTS = {
    "message_sent", "cosmetic_equipped", "cosmetic_owned", "streak_days",
    "daily_claimed", "event_challenge_completed", "event_points", "friend_added",
    "gift_sent", "gift_received", "purchase_made", "profile_customized",
    "sticker_used", "reaction_sent", "loadout_created", "set_completed",
}


def bump_stat(db: Session, user_id: int, key: str, delta: int = 1) -> int:
    stat = db.query(m.UserStat).filter_by(user_id=user_id, key=key).first()
    if stat is None:
        stat = m.UserStat(user_id=user_id, key=key, value=0)
        db.add(stat)
        db.flush()
    stat.value += delta
    db.flush()
    return stat.value


def get_stat(db: Session, user_id: int, key: str) -> int:
    stat = db.query(m.UserStat).filter_by(user_id=user_id, key=key).first()
    return stat.value if stat else 0


def award_xp(db: Session, user: m.User, amount: int, reason: str = "") -> bool:
    """Returns True if leveled up. Level curve: 100 * level xp per level."""
    if amount <= 0:
        return False
    user.xp += amount
    leveled = False
    while user.xp >= 100 * user.level:
        user.xp -= 100 * user.level
        user.level += 1
        leveled = True
    db.flush()
    return leveled


async def check_achievements(db: Session, user_id: int, event: str):
    """Advance achievements listening on `event`; grant rewards on unlock."""
    if event not in ACHIEVEMENT_EVENTS:
        return []
    unlocked = []
    for ach in db.query(m.Achievement).filter_by(enabled=True).all():
        rule = ach.rule or {}
        if rule.get("event") != event:
            continue
        target = int(rule.get("count", 1))
        ua = db.query(m.UserAchievement).filter_by(user_id=user_id, achievement_id=ach.id).first()
        if ua is None:
            ua = m.UserAchievement(user_id=user_id, achievement_id=ach.id)
            db.add(ua)
            db.flush()
        if ua.unlocked_at is not None:
            continue
        stat_key = f"ach_{event}"
        progress = get_stat(db, user_id, stat_key)
        ua.progress = min(progress, target)
        if progress >= target:
            ua.unlocked_at = utcnow()
            unlocked.append(ach)
            if ach.reward_shards:
                credit(db, user_id, "shards", ach.reward_shards, f"achievement:{ach.id}", "achievement", ach.id)
            if ach.reward_gems:
                credit(db, user_id, "gems", ach.reward_gems, f"achievement:{ach.id}", "achievement", ach.id)
            if ach.reward_cosmetic_id:
                grant_entitlement(db, user_id, ach.reward_cosmetic_id, source="achievement", reward_id=ach.id)
            user = db.get(m.User, user_id)
            if user:
                leveled = award_xp(db, user, 25, f"achievement:{ach.id}")
                await notify(db, user_id, "reward", "Achievement unlocked!",
                             f"{ach.name} — {ach.description}",
                             {"kind": "achievement", "achievement_id": ach.id, "leveled_up": leveled})
    db.flush()
    return unlocked


async def bump_event(db: Session, user_id: int, event: str, delta: int = 1):
    """Record a product event: stats, achievements, live-event challenges."""
    bump_stat(db, user_id, f"ach_{event}", delta)
    await check_achievements(db, user_id, event)
    # live event challenges listen on product events too
    live = db.query(m.Event).filter_by(status="live").all()
    now = utcnow()
    for ev in live:
        if ev.start_at and now < ev.start_at:
            continue
        if ev.end_at and now > ev.end_at:
            continue
        # v3: event points accrue per product event while the event is live
        # (server-time eligibility check above; delta is server-computed)
        if delta:
            pts = db.query(m.EventPoints).filter_by(user_id=user_id, event_id=ev.id).first()
            if pts is None:
                pts = m.EventPoints(user_id=user_id, event_id=ev.id)
                db.add(pts)
                db.flush()
            pts.points += delta
            db.flush()
        for ch in (ev.challenges or []):
            rule = (ch or {}).get("rule", {})
            if rule.get("event") != event:
                continue
            prog = db.query(m.EventProgress).filter_by(
                user_id=user_id, event_id=ev.id, challenge_id=ch["id"]).first()
            if prog is None:
                prog = m.EventProgress(user_id=user_id, event_id=ev.id, challenge_id=ch["id"])
                db.add(prog)
                db.flush()
            if prog.completed_at is not None:
                continue
            prog.progress += delta
            target = int(rule.get("count", 1))
            if prog.progress >= target:
                prog.completed_at = utcnow()
                await claim_challenge_reward(db, user_id, ev, ch, prog)
    db.flush()


async def claim_challenge_reward(db: Session, user_id: int, ev: m.Event, ch: dict, prog: m.EventProgress):
    if prog.reward_claimed:
        return
    prog.reward_claimed = True
    reward = ch.get("reward", {})
    if reward.get("cosmetic_id"):
        grant_entitlement(db, user_id, reward["cosmetic_id"], source="event",
                          event_id=ev.id, reward_id=ch["id"])
    if reward.get("shards"):
        credit(db, user_id, "shards", int(reward["shards"]), f"event:{ev.id}:{ch['id']}", "event", ch["id"])
    if reward.get("gems"):
        credit(db, user_id, "gems", int(reward["gems"]), f"event:{ev.id}:{ch['id']}", "event", ch["id"])
    await bump_event(db, user_id, "event_challenge_completed")
    await notify(db, user_id, "event", "Event challenge complete!",
                 f"{ch.get('name', ch['id'])} — {ev.name}",
                 {"kind": "event_challenge", "event_id": ev.id, "challenge_id": ch["id"]})
    audit(db, user_id, "event_reward_granted", "event", ev.id, {"challenge": ch["id"]})


# ------------------------------------------------------ effective chat style

def resolve_chat_style(db: Session, user_id: int, conversation_id: int) -> dict:
    """Bubble/wallpaper/effect resolution chain (spec 17):
    personal theme → shared theme → active loadout defaults → starter defaults."""
    style: dict[str, str | None] = {
        "wallpaper_id": None, "bubble_id": None, "send_effect_id": None,
        "reaction_effect_id": None, "typing_effect_id": None, "scope": "loadout",
    }
    theme = db.query(m.ChatTheme).filter_by(user_id=user_id, conversation_id=conversation_id).first()
    if theme:
        style.update({
            "wallpaper_id": theme.wallpaper_id, "bubble_id": theme.bubble_id,
            "send_effect_id": theme.send_effect_id, "reaction_effect_id": theme.reaction_effect_id,
            "typing_effect_id": theme.typing_effect_id, "scope": theme.scope,
        })
        if any(style[k] for k in ("wallpaper_id", "bubble_id", "send_effect_id",
                                  "reaction_effect_id", "typing_effect_id")):
            return style
    # shared theme set by the other participant
    conv = db.get(m.Conversation, conversation_id)
    if conv:
        member_ids = [r.user_id for r in
                      db.query(m.ConversationMember.user_id).filter_by(conversation_id=conversation_id).all()]
        for other in member_ids:
            if other == user_id:
                continue
            shared = db.query(m.ChatTheme).filter_by(
                user_id=other, conversation_id=conversation_id, scope="shared").first()
            if shared:
                style.update({
                    "wallpaper_id": shared.wallpaper_id, "bubble_id": shared.bubble_id,
                    "send_effect_id": shared.send_effect_id, "reaction_effect_id": shared.reaction_effect_id,
                    "typing_effect_id": shared.typing_effect_id, "scope": "shared",
                })
                break
    if style["bubble_id"]:
        return style
    # active loadout defaults
    loadout = db.query(m.Loadout).filter_by(user_id=user_id, is_active=True).first()
    if loadout:
        items = {i.slot: i.cosmetic_id for i in db.query(m.LoadoutItem).filter_by(loadout_id=loadout.id).all()}
        for k, slot in (("wallpaper_id", "WALLPAPER"), ("bubble_id", "BUBBLE"),
                        ("send_effect_id", "SEND_EFFECT"), ("reaction_effect_id", "REACTION_EFFECT"),
                        ("typing_effect_id", "TYPING_EFFECT")):
            if items.get(slot):
                style[k] = items[slot]
        style["scope"] = "loadout"
    return style


# --------------------------------------------------------------- misc utils

def next_seq(db: Session, conv: m.Conversation) -> int:
    """Allocate the next server_sequence for a conversation (spec 244):
    bump the conversation's own counter and return it. Monotonic per
    conversation even under concurrency."""
    conv.seq = (conv.seq or 0) + 1
    db.flush()
    return conv.seq


def publish_due(db: Session) -> int:
    """Lazy publishing lifecycle: flip scheduled cosmetics whose publish_at
    has passed to live. Called by catalog/shop/collection reads so there is
    no background worker to operate."""
    now = utcnow()
    rows = db.query(m.Cosmetic).filter(m.Cosmetic.status == "scheduled",
                                       m.Cosmetic.publish_at <= now).all()
    for c in rows:
        c.status = "live"
    if rows:
        db.flush()
    return len(rows)


def streak_pair(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def feature_enabled(db: Session, key: str, user_id: int) -> bool:
    """Feature flag with percentage rollout (stable per-user bucket)."""
    flag = db.get(m.FeatureFlag, key)
    if flag is None:
        return False
    if not flag.enabled:
        return False
    if flag.rollout_percent >= 100:
        return True
    return (user_id * 2654435761 % 100) < flag.rollout_percent
