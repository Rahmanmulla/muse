"""STIP backend — realtime connection manager.

One WebSocket per client: GET /ws?token=<jwt>. The server pushes events:
  message.new / message.edit / message.delete / reaction.added / reaction.removed
  typing.started / typing.stopped / presence.changed / inventory.updated
  reward.granted / streak.updated / notification.new / event.updated
  request.new / request.accepted / request.rejected   (v3 message requests)
Clients authenticate with the same JWT as REST.
"""
from __future__ import annotations

import json

import jwt
from fastapi import WebSocket
from sqlalchemy.orm import Session

from auth import JWT_ALG, JWT_SECRET
from db import SessionLocal
from models import Device, User


class ConnectionManager:
    def __init__(self):
        self.active: dict[int, set[WebSocket]] = {}

    async def connect(self, ws: WebSocket, user_id: int):
        await ws.accept()
        self.active.setdefault(user_id, set()).add(ws)

    def disconnect(self, ws: WebSocket, user_id: int):
        conns = self.active.get(user_id)
        if conns and ws in conns:
            conns.remove(ws)
            if not conns:
                del self.active[user_id]

    async def send_to_user(self, user_id: int, event: dict):
        for ws in list(self.active.get(user_id, ())):
            try:
                await ws.send_text(json.dumps(event))
            except Exception:
                self.disconnect(ws, user_id)

    async def broadcast_to_users(self, user_ids: list[int], event: dict, exclude: int | None = None):
        for uid in user_ids:
            if exclude is not None and uid == exclude:
                continue
            await self.send_to_user(uid, event)


manager = ConnectionManager()


def user_id_from_token(token: str) -> int | None:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.InvalidTokenError:
        return None
    db: Session = SessionLocal()
    try:
        user = db.get(User, int(payload["sub"]))
        dev = db.query(Device).filter_by(token_jti=payload.get("jti"), revoked=False).first()
        if user is None or dev is None or user.is_suspended:
            return None
        return user.id
    finally:
        db.close()
