"""STIP backend — v3 message requests.

First message to a non-contact creates a PENDING request instead of a
conversation the recipient can see: a shadow conversation + hidden message
are created (sender sees their own hidden copy), and the recipient gets
request.new. On accept the shadow becomes a real 1:1 conversation (hidden
flags cleared, friend_added bumps fire). On reject the shadow is deleted.

Recipients who turned message_requests off receive the conversation
directly instead of a request.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

import models as m
from auth import get_current_user, rate_limit
from core import audit, bump_event, notify, utcnow
from db import get_db
from ws import manager

router = APIRouter()

REQUEST_RATE = (10, 86400)  # 10 new requests/day per sender


def _message_requests_enabled(db: Session, user_id: int) -> bool:
    """message_requests setting, default True (mirrors app.DEFAULT_SETTINGS)."""
    row = db.query(m.UserSetting).filter_by(user_id=user_id, key="message_requests").first()
    return bool(row.value) if row else True


def _resolve_target(db: Session, payload: dict) -> m.User:
    target = None
    if payload.get("user_id"):
        target = db.get(m.User, int(payload["user_id"]))
    elif payload.get("username"):
        target = db.query(m.User).filter_by(
            username=str(payload["username"]).strip().lower()).first()
    if not target:
        raise HTTPException(400, "Recipient not found.")
    return target


def _existing_1_1(db: Session, a: int, b: int) -> m.Conversation | None:
    return (db.query(m.Conversation)
            .join(m.ConversationMember, m.ConversationMember.conversation_id == m.Conversation.id)
            .filter(m.Conversation.is_group == False,
                    m.ConversationMember.user_id.in_([a, b]))
            .group_by(m.Conversation.id)
            .having(func.count(m.ConversationMember.user_id) == 2).first())


def _request_out(db: Session, req: m.MessageRequest) -> dict:
    frm = db.get(m.User, req.from_user_id)
    msg = db.get(m.Message, req.message_id)
    return {
        "id": req.id, "from_user_id": req.from_user_id, "to_user_id": req.to_user_id,
        "conversation_id": req.conversation_id, "status": req.status,
        "from_user": {"id": frm.id, "username": frm.username,
                      "display_name": frm.display_name} if frm else None,
        "message_preview": (msg.body[:160] if msg and msg.body else f"[{msg.kind}]") if msg else None,
        "created_at": req.created_at.isoformat(),
        "decided_at": req.decided_at.isoformat() if req.decided_at else None,
    }


@router.post("/requests")
async def create_request(payload: dict, user: m.User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Send a first message to a non-contact. Creates a pending request +
    shadow conversation; the recipient only sees it after accepting."""
    rate_limit(f"msgreq:{user.id}", *REQUEST_RATE)
    target = _resolve_target(db, payload)
    if target.id == user.id:
        raise HTTPException(400, "You can't request yourself.")
    if target.is_suspended:
        raise HTTPException(400, "Recipient not available.")
    blocked = db.query(m.Block).filter(
        or_((m.Block.blocker_id == user.id) & (m.Block.blocked_id == target.id),
            (m.Block.blocker_id == target.id) & (m.Block.blocked_id == user.id))).first()
    if blocked:
        raise HTTPException(403, "Cannot contact this user.")
    if _existing_1_1(db, user.id, target.id):
        raise HTTPException(400, "You already have a conversation with this user.")
    if db.query(m.MessageRequest).filter_by(
            from_user_id=user.id, to_user_id=target.id, status="pending").first():
        raise HTTPException(400, "Request already pending.")

    body = (payload.get("body") or "").strip()
    if not body:
        raise HTTPException(400, "Message body required.")

    # recipient opted out of the request gate -> direct conversation + message
    if _message_requests_enabled(db, target.id) is False:
        conv = m.Conversation(is_group=False, created_by=user.id)
        db.add(conv)
        db.flush()
        db.add(m.ConversationMember(conversation_id=conv.id, user_id=user.id))
        db.add(m.ConversationMember(conversation_id=conv.id, user_id=target.id))
        db.flush()
        from core import next_seq
        msg = m.Message(conversation_id=conv.id, sender_id=user.id, kind="text",
                        body=body[:8000], server_sequence=next_seq(db, conv))
        db.add(msg)
        db.flush()
        db.commit()
        await bump_event(db, target.id, "friend_added")
        await bump_event(db, user.id, "friend_added")
        db.commit()
        await manager.send_to_user(target.id, {"type": "message.new",
                                               "conversation_id": conv.id,
                                               "message_id": msg.id})
        return {"ok": True, "direct": True, "conversation_id": conv.id, "message_id": msg.id}

    # shadow conversation: recipient's membership is hidden until accept
    conv = m.Conversation(is_group=False, created_by=user.id)
    db.add(conv)
    db.flush()
    db.add(m.ConversationMember(conversation_id=conv.id, user_id=user.id))
    db.add(m.ConversationMember(conversation_id=conv.id, user_id=target.id, hidden=True))
    # bubble snapshot at send time (visual only), like send_message
    bubble_id = None
    active = db.query(m.Loadout).filter_by(user_id=user.id, is_active=True).first()
    if active:
        item = db.query(m.LoadoutItem).filter_by(loadout_id=active.id, slot="BUBBLE").first()
        bubble_id = item.cosmetic_id if item else None
    from core import next_seq
    seq = next_seq(db, conv)
    msg = m.Message(conversation_id=conv.id, sender_id=user.id, kind="text",
                    body=body[:8000], cosmetic_id=bubble_id,
                    server_sequence=seq, hidden=True)
    db.add(msg)
    db.flush()
    req = m.MessageRequest(from_user_id=user.id, to_user_id=target.id,
                           conversation_id=conv.id, message_id=msg.id)
    db.add(req)
    db.flush()
    audit(db, user.id, "message_request_created", "message_request", str(req.id),
          {"to": target.id, "conversation": conv.id})
    db.commit()
    await notify(db, target.id, "request", "New message request",
                 f"{user.display_name} wants to message you.",
                 {"kind": "request", "request_id": req.id, "conversation_id": conv.id,
                  "request": _request_out(db, req)},
                 event_name="request.new")
    db.commit()
    return {"ok": True, "direct": False, "request": _request_out(db, req)}


@router.get("/requests/inbox")
def request_inbox(user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(m.MessageRequest)
            .filter_by(to_user_id=user.id, status="pending")
            .order_by(m.MessageRequest.id.desc()).all())
    return [_request_out(db, r) for r in rows]


@router.post("/requests/{request_id}/accept")
async def accept_request(request_id: int, user: m.User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Recipient accepts: shadow becomes a real conversation, hidden messages
    are revealed, friendship bumps fire."""
    req = db.get(m.MessageRequest, request_id)
    if not req or req.status != "pending":
        raise HTTPException(404, "Request not found.")
    if req.to_user_id != user.id:
        raise HTTPException(403, "Only the recipient can accept.")
    req.status = "accepted"
    req.decided_at = utcnow()
    # reveal membership + all messages from the sender
    db.query(m.ConversationMember).filter_by(
        conversation_id=req.conversation_id, user_id=user.id).update({"hidden": False})
    db.query(m.Message).filter(m.Message.conversation_id == req.conversation_id,
                               m.Message.hidden == True).update({"hidden": False},
                               synchronize_session=False)
    audit(db, user.id, "message_request_accepted", "message_request", str(req.id), {})
    db.commit()
    await bump_event(db, req.to_user_id, "friend_added")
    await bump_event(db, req.from_user_id, "friend_added")
    db.commit()
    for uid in (req.from_user_id, req.to_user_id):
        await manager.send_to_user(uid, {"type": "request.accepted",
                                         "request_id": req.id,
                                         "conversation_id": req.conversation_id})
    await notify(db, req.from_user_id, "request", "Request accepted ✅",
                 f"{user.display_name} accepted your message request.",
                 {"kind": "request", "request_id": req.id, "conversation_id": req.conversation_id})
    db.commit()
    return {"ok": True, "conversation_id": req.conversation_id}


@router.post("/requests/{request_id}/reject")
async def reject_request(request_id: int, payload: dict,
                         user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Recipient rejects: the shadow conversation is deleted. Optionally
    files a report against the sender."""
    req = db.get(m.MessageRequest, request_id)
    if not req or req.status != "pending":
        raise HTTPException(404, "Request not found.")
    if req.to_user_id != user.id:
        raise HTTPException(403, "Only the recipient can reject.")
    req.status = "rejected"
    req.decided_at = utcnow()
    if payload.get("report"):
        db.add(m.Report(reporter_id=user.id, target_type="user",
                        target_id=str(req.from_user_id),
                        reason=(payload.get("reason") or "message request")[:2000]))
    conv_id = req.conversation_id
    from_id = req.from_user_id
    audit(db, user.id, "message_request_rejected", "message_request", str(req.id), {})
    db.commit()
    # delete the shadow conversation (SQLite FK enforcement is off, so clean
    # up members/messages/statuses explicitly)
    msg_ids = [r[0] for r in db.query(m.Message.id).filter_by(conversation_id=conv_id).all()]
    if msg_ids:
        db.query(m.MessageStatus).filter(m.MessageStatus.message_id.in_(msg_ids)).delete(
            synchronize_session=False)
    db.query(m.ConversationMember).filter_by(conversation_id=conv_id).delete()
    db.query(m.Message).filter_by(conversation_id=conv_id).delete()
    conv = db.get(m.Conversation, conv_id)
    if conv:
        db.delete(conv)
    db.commit()
    await manager.send_to_user(from_id, {"type": "request.rejected", "request_id": request_id})
    return {"ok": True}
