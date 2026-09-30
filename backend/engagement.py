"""STIP backend — engagement: streaks, notifications, events, achievements."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models as m
from auth import get_current_user
from core import (audit, credit, feature_enabled, grant_entitlement, notify,
                  streak_pair, utcnow)
from db import get_db

router = APIRouter()


# ------------------------------------------------------------------ streaks

@router.get("/streaks")
def my_streaks(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(m.Streak).filter(
        (m.Streak.user_a == user.id) | (m.Streak.user_b == user.id)).all()
    out = []
    for s in rows:
        other_id = s.user_b if s.user_a == user.id else s.user_a
        other = db.get(m.User, other_id)
        fs = db.query(m.FriendshipStat).filter_by(
            user_a=min(s.user_a, s.user_b), user_b=max(s.user_a, s.user_b)).first()
        out.append({
            "with_user": {"id": other.id, "username": other.username,
                          "display_name": other.display_name} if other else None,
            "count": s.count, "longest": s.longest,
            "last_active_day": s.last_active_day,
            "message_count": fs.message_count if fs else 0,
            "milestones": fs.milestones if fs else [],
        })
    return sorted(out, key=lambda x: -x["count"])


@router.get("/streaks/{other_id}")
def streak_detail(other_id: int, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    a, b = streak_pair(user.id, other_id)
    s = db.query(m.Streak).filter_by(user_a=a, user_b=b).first()
    fs = db.query(m.FriendshipStat).filter_by(user_a=a, user_b=b).first()
    return {"count": s.count if s else 0, "longest": s.longest if s else 0,
            "last_active_day": s.last_active_day if s else None,
            "message_count": fs.message_count if fs else 0,
            "first_message_at": fs.first_message_at.isoformat() if fs and fs.first_message_at else None,
            "milestones": fs.milestones if fs else []}


# ------------------------------------------------------------- notifications

@router.get("/notifications")
def notifications(unread_only: bool = False, limit: int = 50,
                  user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(m.Notification).filter_by(user_id=user.id)
    if unread_only:
        q = q.filter_by(read=False)
    rows = q.order_by(m.Notification.id.desc()).limit(min(limit, 100)).all()
    unread = db.query(m.Notification).filter_by(user_id=user.id, read=False).count()
    return {"unread": unread,
            "items": [{"id": n.id, "type": n.type, "title": n.title, "body": n.body,
                       "data": n.data or {}, "read": n.read,
                       "created_at": n.created_at.isoformat()} for n in rows]}


@router.post("/notifications/read")
def notifications_read(payload: dict, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ids = payload.get("ids") or []
    if ids == "all":
        db.query(m.Notification).filter_by(user_id=user.id, read=False).update({"read": True})
    else:
        db.query(m.Notification).filter(m.Notification.user_id == user.id,
                                        m.Notification.id.in_([int(i) for i in ids])).update({"read": True},
                                        synchronize_session=False)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ events

def event_out(db: Session, ev: m.Event, user_id: int) -> dict:
    now = utcnow()
    is_live = ev.status == "live" and (not ev.start_at or now >= ev.start_at) and (not ev.end_at or now <= ev.end_at)
    challenges = []
    for ch in (ev.challenges or []):
        prog = db.query(m.EventProgress).filter_by(user_id=user_id, event_id=ev.id,
                                                   challenge_id=ch["id"]).first()
        target = int((ch.get("rule") or {}).get("count", 1))
        challenges.append({
            "id": ch["id"], "name": ch.get("name", ch["id"]), "rule": ch.get("rule", {}),
            "reward": ch.get("reward", {}),
            "progress": prog.progress if prog else 0, "target": target,
            "completed": bool(prog and prog.completed_at),
        })
    pts = db.query(m.EventPoints).filter_by(user_id=user_id, event_id=ev.id).first()
    shop = []
    for item in (ev.shop_items or []):
        c = db.get(m.Cosmetic, item.get("cosmetic_id"))
        if c:
            shop.append({"cosmetic_id": c.id, "name": c.name, "rarity": c.rarity,
                         "asset": c.asset, "price_shards": item.get("price_shards", 0),
                         "price_gems": item.get("price_gems", 0)})
    return {
        "id": ev.id, "name": ev.name, "description": ev.description, "theme": ev.theme,
        "status": ev.status, "is_live": is_live,
        "start_at": ev.start_at.isoformat() if ev.start_at else None,
        "end_at": ev.end_at.isoformat() if ev.end_at else None,
        "banner_asset": ev.banner_asset or {},
        "challenges": challenges, "shop_items": shop,
        "points": pts.points if pts else 0,
        "tiers_claimed": pts.tiers_claimed if pts else [],
        "progression_track": ev.progression_track or [],
    }


@router.get("/events")
def events(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(m.Event).filter(m.Event.status.in_(["live", "scheduled", "paused", "ended"])).all()
    return [event_out(db, e, user.id) for e in rows]


@router.get("/events/{event_id}")
def event_detail(event_id: str, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ev = db.get(m.Event, event_id)
    if not ev:
        raise HTTPException(404, "Event not found.")
    return event_out(db, ev, user.id)


@router.post("/events/{event_id}/tiers/claim")
async def claim_event_tier(event_id: str, payload: dict,
                           user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Claim a progression-track tier reward. Idempotent: the tiers_claimed
    list is the uniqueness guard — a retried request can't double-grant.
    Points accrue server-side while the event is live (core.bump_event)."""
    ev = db.get(m.Event, event_id)
    if not ev:
        raise HTTPException(404, "Event not found.")
    track = ev.progression_track or []
    tier_index = payload.get("tier_index")
    if not isinstance(tier_index, int) or not (0 <= tier_index < len(track)):
        raise HTTPException(400, "Invalid tier_index.")
    tier = track[tier_index]
    pts = db.query(m.EventPoints).filter_by(user_id=user.id, event_id=ev.id).first()
    claimed = list(pts.tiers_claimed or []) if pts else []
    if tier_index in claimed:
        raise HTTPException(400, "Tier already claimed.")
    need = int((tier or {}).get("points", 0))
    have = pts.points if pts else 0
    if have < need:
        raise HTTPException(400, f"Not enough event points ({have}/{need}).")
    if pts is None:
        pts = m.EventPoints(user_id=user.id, event_id=ev.id)
        db.add(pts)
        db.flush()
    reward = (tier or {}).get("reward", {})
    if reward.get("cosmetic_id"):
        grant_entitlement(db, user.id, reward["cosmetic_id"], source="event",
                          event_id=ev.id, reward_id=f"tier:{tier_index}")
    if reward.get("shards"):
        credit(db, user.id, "shards", int(reward["shards"]),
               f"event:{ev.id}:tier:{tier_index}", "event", f"tier:{tier_index}")
    if reward.get("gems"):
        credit(db, user.id, "gems", int(reward["gems"]),
               f"event:{ev.id}:tier:{tier_index}", "event", f"tier:{tier_index}")
    claimed.append(tier_index)
    pts.tiers_claimed = claimed
    audit(db, user.id, "event_tier_claimed", "event", ev.id, {"tier": tier_index})
    db.commit()
    await notify(db, user.id, "event", "Event tier claimed! 🏆",
                 f"{ev.name} — tier {tier_index + 1}",
                 {"kind": "event_tier", "event_id": ev.id, "tier_index": tier_index},
                 event_name="event.updated")
    db.commit()
    return {"ok": True, "tier_index": tier_index, "reward": reward}


# -------------------------------------------------------------- achievements

@router.get("/achievements")
def achievements(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    out = []
    for a in db.query(m.Achievement).filter_by(enabled=True).all():
        ua = db.query(m.UserAchievement).filter_by(user_id=user.id, achievement_id=a.id).first()
        out.append({
            "id": a.id, "name": a.name, "description": a.description,
            "target": int((a.rule or {}).get("count", 1)),
            "progress": ua.progress if ua else 0,
            "unlocked": bool(ua and ua.unlocked_at),
            "unlocked_at": ua.unlocked_at.isoformat() if ua and ua.unlocked_at else None,
            "reward": {"shards": a.reward_shards, "gems": a.reward_gems,
                       "cosmetic_id": a.reward_cosmetic_id},
        })
    return out


@router.get("/profile/progress")
def progress(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Level, XP, collection stats — the progression snapshot (spec 130-131)."""
    owned = db.query(m.Entitlement).filter_by(user_id=user.id, status="active").count()
    total = db.query(m.Cosmetic).filter_by(enabled=True).count()
    legendary = db.query(m.Entitlement).join(m.Cosmetic, m.Entitlement.cosmetic_id == m.Cosmetic.id).filter(
        m.Entitlement.user_id == user.id, m.Cosmetic.rarity.in_(["legendary", "mythic"])).count()
    stats = {s.key: s.value for s in db.query(m.UserStat).filter_by(user_id=user.id).all()}
    titles = []
    if legendary >= 5:
        titles.append("Legendary Collector")
    if owned >= 25:
        titles.append("Collector")
    if stats.get("ach_event_challenge_completed", 0) >= 3:
        titles.append("Event Collector")
    return {
        "level": user.level, "xp": user.xp, "xp_for_next": 100 * user.level,
        "collection": {"owned": owned, "total": total,
                       "percent": round(100 * owned / total, 1) if total else 0},
        "legendary_count": legendary, "titles": titles, "stats": stats,
    }


# ------------------------------------------------------------ feature flags

@router.get("/flags")
def flags(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {f.key: feature_enabled(db, f.key, user.id)
            for f in db.query(m.FeatureFlag).all()}
