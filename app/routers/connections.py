"""Connections an organisation sets up itself (ADR-044). Slice 1: one chat webhook (Discord or Slack).

The secret is write-only: no response here contains it, the audit log never does, and a failed test records a
status and an error class, not the address. Only an organisation admin may see or change a connection.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit_log, connections
from app.auth import Actor, current_actor
from app.db import get_session
from app.models import Connection

router = APIRouter(prefix="/connections", tags=["connections"])


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _admin(actor: Actor) -> Actor:
    if actor.role != "ORG_ADMIN" or actor.engagement_id or not actor.org_id:
        raise HTTPException(403, "only an organisation admin can manage connections")
    return actor


def _row(db: Session, org_id: str) -> Connection | None:
    return db.query(Connection).filter_by(org_id=org_id, kind=connections.KIND_CHAT).one_or_none()


def _view(row: Connection | None) -> dict:
    """The only shape that ever leaves this module: status facts, never the secret."""
    return {"kind": connections.KIND_CHAT, "configured": row is not None,
            "hint": row.hint if row else "", "status": row.status if row else "NONE",
            "last_tested_at": row.last_tested_at.isoformat() if row and row.last_tested_at else None,
            "last_error": row.last_error if row else ""}


def _state(db: Session, org_id: str) -> dict:
    return {"key_configured": connections.available(), "connections": [_view(_row(db, org_id))]}


def _need_key() -> None:
    if not connections.available():
        raise HTTPException(503, "connections are switched off until the server has CONNECTIONS_KEY set")


class ChatWebhookIn(BaseModel):
    url: str = Field(min_length=10, max_length=400)


@router.get("")
def list_connections(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    return _state(db, _admin(actor).org_id)


@router.put("/chat-webhook")
def set_chat_webhook(body: ChatWebhookIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    _admin(actor)
    _need_key()
    try:
        url = connections.validate_chat_webhook(body.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    row = _row(db, actor.org_id)
    replaced = row is not None
    if row is None:
        row = Connection(org_id=actor.org_id, kind=connections.KIND_CHAT, created_by=actor.label(), created_at=_now())
        db.add(row)
    row.config_encrypted, row.hint = connections.encrypt(url), connections.hint(url)
    row.status, row.last_tested_at, row.last_error, row.updated_at = "UNTESTED", None, "", _now()
    db.flush()
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="CONNECTION_SET",
                     entity_type="connection", entity=row.id, org_id=actor.org_id,
                     detail={"kind": row.kind, "hint": row.hint, "replaced": replaced})
    db.commit()
    return _state(db, actor.org_id)


@router.delete("/chat-webhook")
def remove_chat_webhook(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    _admin(actor)
    row = _row(db, actor.org_id)
    if row is not None:
        audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="CONNECTION_REMOVED",
                         entity_type="connection", entity=row.id, org_id=actor.org_id, detail={"kind": row.kind})
        db.delete(row)
        db.commit()
    return _state(db, actor.org_id)


@router.post("/chat-webhook/test")
def test_chat_webhook(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """Send one line and record how it went. The page shows the status and a short reason, nothing else."""
    _admin(actor)
    _need_key()
    row = _row(db, actor.org_id)
    if row is None:
        raise HTTPException(404, "no chat webhook is connected")
    try:
        url = connections.decrypt(row.config_encrypted)
    except ValueError as exc:
        ok, reason = False, str(exc)
    else:
        ok, reason = connections.send(url, "[INFO] GRC connection test: this channel will receive your alerts and weekly report.")
    row.status, row.last_error, row.last_tested_at = ("OK" if ok else "FAILED"), reason, _now()
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="CONNECTION_TESTED",
                     entity_type="connection", entity=row.id, org_id=actor.org_id,
                     detail={"kind": row.kind, "ok": ok, "reason": reason})
    db.commit()
    return _state(db, actor.org_id)
