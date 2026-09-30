"""STIP backend — cosmetic engine: catalog, inventory, loadouts, chat themes.

Server-authoritative: ownership and equip validity are always checked
server-side (spec 236). Messages carry only cosmetic_id; the client
resolves visuals from its local catalog cache (spec 12).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

import models as m
from auth import get_current_user
from core import (audit, bump_event, bump_stat, check_achievements, get_stat,
                  grant_entitlement, has_entitlement, notify, publish_due, utcnow)
from db import get_db

router = APIRouter()


def cosmetic_out(db: Session, c: m.Cosmetic, user_id: int | None = None) -> dict:
    owned = has_entitlement(db, user_id, c.id) if user_id else False
    return {
        "id": c.id, "category": c.category, "name": c.name, "description": c.description,
        "rarity": c.rarity, "version": c.version, "asset": c.asset,
        "asset_hash": c.asset_hash, "performance_class": c.performance_class,
        "fallback_id": c.fallback_id, "theme_tags": c.theme_tags or [],
        "availability": c.availability, "acquisition": c.acquisition,
        "price_shards": c.price_shards, "price_gems": c.price_gems,
        "event_id": c.event_id, "obtainable": c.obtainable, "transferable": c.transferable,
        "set_id": c.set_id, "evolves_from": c.evolves_from, "evolves_to": c.evolves_to,
        "featured": c.featured, "release_date": c.release_date.isoformat() if c.release_date else None,
        "expires_at": c.expires_at.isoformat() if c.expires_at else None,
        "status": getattr(c, "status", "live"),
        "publish_at": c.publish_at.isoformat() if getattr(c, "publish_at", None) else None,
        "owned": owned,
    }


# ------------------------------------------------------------------- catalog

@router.get("/catalog")
def catalog(category: str | None = None, rarity: str | None = None, theme: str | None = None,
            set_id: str | None = None, q: str | None = None,
            limit: int = Query(100, le=200), offset: int = 0,
            user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    # v3 publishing lifecycle: lazily flip due scheduled items to live
    publish_due(db)
    owned_ids = {e.cosmetic_id for e in db.query(m.Entitlement.cosmetic_id)
                 .filter_by(user_id=user.id, status="active").all()}
    query = db.query(m.Cosmetic).filter_by(enabled=True)
    # live items for everyone; owned items always visible (retired items keep
    # working for owners — spec 175)
    query = query.filter(or_(m.Cosmetic.status == "live",
                             m.Cosmetic.id.in_(owned_ids) if owned_ids else False))
    if category:
        query = query.filter(m.Cosmetic.category == category)
    if rarity:
        query = query.filter(m.Cosmetic.rarity == rarity)
    if set_id:
        query = query.filter(m.Cosmetic.set_id == set_id)
    if q:
        query = query.filter(m.Cosmetic.name.ilike(f"%{q}%"))
    items = query.order_by(m.Cosmetic.rarity.desc()).offset(offset).limit(limit).all()
    if theme:
        items = [c for c in items if theme in (c.theme_tags or [])]
    return [cosmetic_out(db, c, user.id) for c in items]


@router.get("/catalog/{cosmetic_id}")
def catalog_detail(cosmetic_id: str, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.get(m.Cosmetic, cosmetic_id)
    if not c or not c.enabled:
        raise HTTPException(404, "Cosmetic not found.")
    out = cosmetic_out(db, c, user.id)
    ent = db.query(m.Entitlement).filter_by(user_id=user.id, cosmetic_id=cosmetic_id).first()
    if not ent and getattr(c, "status", "live") != "live":
        # unpublished items are invisible unless owned
        raise HTTPException(404, "Cosmetic not found.")
    out["entitlement"] = ({"source": ent.source, "event_id": ent.event_id,
                           "granted_at": ent.granted_at.isoformat()} if ent else None)
    out["favorite"] = db.query(m.Favorite).filter_by(user_id=user.id, cosmetic_id=cosmetic_id).first() is not None
    return out


# ----------------------------------------------------------------- inventory

@router.get("/inventory")
def inventory(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ents = db.query(m.Entitlement).filter_by(user_id=user.id, status="active").all()
    out = []
    for e in ents:
        c = db.get(m.Cosmetic, e.cosmetic_id)
        if not c:
            continue
        item = cosmetic_out(db, c, user.id)
        item["source"] = e.source
        item["granted_at"] = e.granted_at.isoformat()
        out.append(item)
    return out


@router.get("/collection")
def collection_book(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Collection book: owned/unowned/favorites/sets/rarity groups (spec 22)."""
    publish_due(db)
    owned_ids = {e.cosmetic_id for e in db.query(m.Entitlement.cosmetic_id)
                 .filter_by(user_id=user.id, status="active").all()}
    fav_ids = {f.cosmetic_id for f in db.query(m.Favorite.cosmetic_id)
               .filter_by(user_id=user.id).all()}
    all_cos = db.query(m.Cosmetic).filter_by(enabled=True).filter(
        or_(m.Cosmetic.status == "live",
            m.Cosmetic.id.in_(owned_ids) if owned_ids else False)).all()
    items = []
    for c in all_cos:
        d = cosmetic_out(db, c, user.id)
        d["owned"] = c.id in owned_ids
        d["favorite"] = c.id in fav_ids
        items.append(d)
    sets = []
    for s in db.query(m.CosmeticSet).filter_by(enabled=True).all():
        members = [c for c in all_cos if c.set_id == s.id]
        have = sum(1 for c in members if c.id in owned_ids)
        sets.append({
            "id": s.id, "name": s.name, "description": s.description, "theme": s.theme,
            "total": len(members), "owned": have, "complete": have == len(members) and len(members) > 0,
            "completion_reward": s.completion_reward,
            "items": [cosmetic_out(db, c, user.id) for c in members],
        })
    return {
        "total": len(all_cos), "owned_count": len(owned_ids),
        "items": items, "sets": sets,
        "favorites": [i for i in items if i["favorite"]],
    }


@router.post("/favorites/{cosmetic_id}")
def add_favorite(cosmetic_id: str, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not has_entitlement(db, user.id, cosmetic_id):
        raise HTTPException(400, "You don't own this cosmetic.")
    if db.query(m.Favorite).filter_by(user_id=user.id, cosmetic_id=cosmetic_id).first() is None:
        db.add(m.Favorite(user_id=user.id, cosmetic_id=cosmetic_id))
    db.commit()
    return {"ok": True}


@router.delete("/favorites/{cosmetic_id}")
def remove_favorite(cosmetic_id: str, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(m.Favorite).filter_by(user_id=user.id, cosmetic_id=cosmetic_id).delete()
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ loadouts

def loadout_out(db: Session, lo: m.Loadout) -> dict:
    items = {i.slot: i.cosmetic_id for i in db.query(m.LoadoutItem).filter_by(loadout_id=lo.id).all()}
    resolved = {}
    for slot, cid in items.items():
        c = db.get(m.Cosmetic, cid) if cid else None
        resolved[slot] = {"id": c.id, "name": c.name, "rarity": c.rarity,
                          "category": c.category, "asset": c.asset} if c else None
    return {"id": lo.id, "name": lo.name, "is_active": lo.is_active, "items": resolved,
            "created_at": lo.created_at.isoformat()}


@router.get("/loadouts")
def list_loadouts(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [loadout_out(db, lo) for lo in
            db.query(m.Loadout).filter_by(user_id=user.id).order_by(m.Loadout.id).all()]


@router.post("/loadouts")
async def create_loadout(payload: dict, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    name = (payload.get("name") or "Loadout").strip()[:64]
    existing = db.query(m.Loadout).filter_by(user_id=user.id).count()
    if existing >= 10:
        raise HTTPException(400, "Maximum 10 loadouts.")
    # copy from active loadout if requested
    lo = m.Loadout(user_id=user.id, name=name)
    db.add(lo)
    db.flush()
    src_id = payload.get("copy_from")
    if src_id:
        src = db.get(m.Loadout, int(src_id))
        if src and src.user_id == user.id:
            for item in db.query(m.LoadoutItem).filter_by(loadout_id=src.id).all():
                db.add(m.LoadoutItem(loadout_id=lo.id, slot=item.slot, cosmetic_id=item.cosmetic_id))
    else:
        active = db.query(m.Loadout).filter_by(user_id=user.id, is_active=True).first()
        if active:
            for item in db.query(m.LoadoutItem).filter_by(loadout_id=active.id).all():
                db.add(m.LoadoutItem(loadout_id=lo.id, slot=item.slot, cosmetic_id=item.cosmetic_id))
    db.commit()
    await bump_event(db, user.id, "loadout_created")
    db.commit()
    return loadout_out(db, lo)


@router.post("/loadouts/{loadout_id}/activate")
def activate_loadout(loadout_id: int, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    lo = db.get(m.Loadout, loadout_id)
    if not lo or lo.user_id != user.id:
        raise HTTPException(404, "Loadout not found.")
    db.query(m.Loadout).filter_by(user_id=user.id).update({"is_active": False})
    lo.is_active = True
    db.commit()
    return loadout_out(db, lo)


@router.put("/loadouts/{loadout_id}")
async def set_loadout_item(loadout_id: int, payload: dict,
                           user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Equip a cosmetic into a loadout slot. Ownership verified server-side (spec 236)."""
    lo = db.get(m.Loadout, loadout_id)
    if not lo or lo.user_id != user.id:
        raise HTTPException(404, "Loadout not found.")
    slot = payload.get("slot")
    cosmetic_id = payload.get("cosmetic_id")
    if slot not in m.LOADOUT_SLOTS:
        raise HTTPException(400, f"Unknown slot. Valid: {m.LOADOUT_SLOTS}")
    if cosmetic_id:
        c = db.get(m.Cosmetic, cosmetic_id)
        if not c or not c.enabled:
            raise HTTPException(400, "Cosmetic not available.")
        allowed = m.SLOT_CATEGORY_MAP.get(slot, [])
        if c.category not in allowed:
            raise HTTPException(400, f"{c.name} cannot go in slot {slot}.")
        if not has_entitlement(db, user.id, cosmetic_id):
            raise HTTPException(403, "You don't own this cosmetic.")
    item = db.query(m.LoadoutItem).filter_by(loadout_id=lo.id, slot=slot).first()
    if item is None:
        item = m.LoadoutItem(loadout_id=lo.id, slot=slot, cosmetic_id=cosmetic_id)
        db.add(item)
    else:
        item.cosmetic_id = cosmetic_id
    db.commit()
    if cosmetic_id:
        await bump_event(db, user.id, "cosmetic_equipped")
        db.commit()
    audit(db, user.id, "cosmetic_equipped", "loadout", str(lo.id),
          {"slot": slot, "cosmetic_id": cosmetic_id})
    db.commit()
    return loadout_out(db, lo)


@router.delete("/loadouts/{loadout_id}")
def delete_loadout(loadout_id: int, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    lo = db.get(m.Loadout, loadout_id)
    if not lo or lo.user_id != user.id:
        raise HTTPException(404, "Loadout not found.")
    if lo.is_active:
        raise HTTPException(400, "Cannot delete the active loadout.")
    db.query(m.LoadoutItem).filter_by(loadout_id=lo.id).delete()
    db.delete(lo)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------- chat themes

CHAT_THEME_FIELDS = ["wallpaper_id", "bubble_id", "send_effect_id", "reaction_effect_id", "typing_effect_id"]
THEME_CATEGORY = {"wallpaper_id": "chat.wallpaper", "bubble_id": "chat.bubble",
                  "send_effect_id": "chat.send_effect", "reaction_effect_id": "chat.reaction",
                  "typing_effect_id": "chat.typing"}


@router.get("/conversations/{conv_id}/theme")
def get_chat_theme(conv_id: int, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app import require_member
    require_member(db, conv_id, user.id)
    from core import resolve_chat_style
    style = resolve_chat_style(db, user.id, conv_id)
    resolved = {}
    for k in CHAT_THEME_FIELDS:
        cid = style.get(k)
        c = db.get(m.Cosmetic, cid) if cid else None
        resolved[k] = {"id": c.id, "name": c.name, "rarity": c.rarity, "asset": c.asset} if c else None
    resolved["scope"] = style.get("scope")
    return resolved


@router.put("/conversations/{conv_id}/theme")
async def set_chat_theme(conv_id: int, payload: dict,
                         user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Per-chat customization: personal view or shared theme (spec 17, 134)."""
    from app import require_member
    require_member(db, conv_id, user.id)
    scope = payload.get("scope", "personal")
    if scope not in ("personal", "shared"):
        raise HTTPException(400, "scope must be personal|shared")
    theme = db.query(m.ChatTheme).filter_by(user_id=user.id, conversation_id=conv_id).first()
    if theme is None:
        theme = m.ChatTheme(user_id=user.id, conversation_id=conv_id, scope=scope)
        db.add(theme)
    theme.scope = scope
    for field in CHAT_THEME_FIELDS:
        if field in payload:
            cid = payload[field]
            if cid:
                c = db.get(m.Cosmetic, cid)
                if not c or c.category != THEME_CATEGORY[field] or not c.enabled:
                    raise HTTPException(400, f"Invalid cosmetic for {field}.")
                if not has_entitlement(db, user.id, cid):
                    raise HTTPException(403, f"You don't own {c.name}.")
            setattr(theme, field, cid)
    theme.updated_at = utcnow()
    db.commit()
    await bump_event(db, user.id, "cosmetic_equipped")
    db.commit()
    audit(db, user.id, "chat_theme_updated", "conversation", str(conv_id), {"scope": scope})
    db.commit()
    return {"ok": True, "scope": scope}


@router.delete("/conversations/{conv_id}/theme")
def reset_chat_theme(conv_id: int, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app import require_member
    require_member(db, conv_id, user.id)
    db.query(m.ChatTheme).filter_by(user_id=user.id, conversation_id=conv_id).delete()
    db.commit()
    return {"ok": True}
