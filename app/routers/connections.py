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


def _row(db: Session, org_id: str, kind: str = connections.KIND_CHAT) -> Connection | None:
    return db.query(Connection).filter_by(org_id=org_id, kind=kind).one_or_none()


def _view(row: Connection | None, kind: str = connections.KIND_CHAT) -> dict:
    """The only shape that ever leaves this module: status facts, never the secret."""
    return {"kind": kind, "configured": row is not None,
            "hint": row.hint if row else "", "status": row.status if row else "NONE",
            "last_tested_at": row.last_tested_at.isoformat() if row and row.last_tested_at else None,
            "last_error": row.last_error if row else ""}


def _aws_view(row: Connection | None) -> dict:
    """The AWS card also needs what the customer must put in their role: the platform identity to trust and the
    external ID. Neither is a secret (ADR-048); the role ARN is shown back so they can check it."""
    v = _view(row, connections.KIND_AWS)
    v["details"] = {"platform_principal": connections.platform_principal(), "external_id": "", "role_arn": "", "region": ""}
    if row is not None:
        try:
            v["details"].update(connections.unpack_aws(connections.decrypt(row.config_encrypted)))
        except ValueError:
            pass
    return v


def _state(db: Session, org_id: str) -> dict:
    return {"key_configured": connections.available(),
            "connections": [_view(_row(db, org_id)),
                            _view(_row(db, org_id, connections.KIND_GITHUB), connections.KIND_GITHUB),
                            _aws_view(_row(db, org_id, connections.KIND_AWS))]}


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


class GithubIn(BaseModel):
    token: str = Field(min_length=10, max_length=300)
    repos: list[str] = Field(min_length=1, max_length=connections.MAX_REPOS)


@router.put("/github")
def set_github(body: GithubIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """Token and repositories for the change-control collector (ADR-045). Write-only, like the chat webhook."""
    _admin(actor)
    _need_key()
    try:
        token, repos = connections.validate_github(body.token, body.repos)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    kind = connections.KIND_GITHUB
    row = _row(db, actor.org_id, kind)
    replaced = row is not None
    if row is None:
        row = Connection(org_id=actor.org_id, kind=kind, created_by=actor.label(), created_at=_now())
        db.add(row)
    row.config_encrypted, row.hint = connections.encrypt(connections.pack_github(token, repos)), connections.github_hint(token, repos)
    row.status, row.last_tested_at, row.last_error, row.updated_at = "UNTESTED", None, "", _now()
    db.flush()
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="CONNECTION_SET",
                     entity_type="connection", entity=row.id, org_id=actor.org_id,
                     detail={"kind": kind, "hint": row.hint, "replaced": replaced, "repositories": repos})
    db.commit()
    return _state(db, actor.org_id)


@router.delete("/github")
def remove_github(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    _admin(actor)
    row = _row(db, actor.org_id, connections.KIND_GITHUB)
    if row is not None:
        audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="CONNECTION_REMOVED",
                         entity_type="connection", entity=row.id, org_id=actor.org_id, detail={"kind": row.kind})
        db.delete(row)
        db.commit()
    return _state(db, actor.org_id)


@router.post("/github/test")
def test_github(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    _admin(actor)
    _need_key()
    row = _row(db, actor.org_id, connections.KIND_GITHUB)
    if row is None:
        raise HTTPException(404, "no GitHub connection is saved")
    try:
        token, repos = connections.unpack_github(connections.decrypt(row.config_encrypted))
    except ValueError as exc:
        ok, reason = False, str(exc)
    else:
        ok, reason = connections.github_test(token, repos)
    row.status, row.last_error, row.last_tested_at = ("OK" if ok else "FAILED"), reason, _now()
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="CONNECTION_TESTED",
                     entity_type="connection", entity=row.id, org_id=actor.org_id,
                     detail={"kind": row.kind, "ok": ok, "reason": reason})
    db.commit()
    return _state(db, actor.org_id)


class AwsIn(BaseModel):
    role_arn: str = Field(min_length=10, max_length=600)
    region: str = Field(min_length=5, max_length=30)


def _aws_cfg(row: Connection) -> dict:
    return connections.unpack_aws(connections.decrypt(row.config_encrypted))


def _save_aws(db: Session, actor: Actor, cfg: dict, action_detail: dict) -> Connection:
    kind = connections.KIND_AWS
    cfg = {"role_arn": "", "region": "", **cfg}
    row = _row(db, actor.org_id, kind)
    replaced = row is not None
    if row is None:
        row = Connection(org_id=actor.org_id, kind=kind, created_by=actor.label(), created_at=_now())
        db.add(row)
    row.config_encrypted, row.hint = connections.encrypt(connections.pack_aws(**cfg)), connections.aws_hint(cfg)
    row.status, row.last_tested_at, row.last_error, row.updated_at = "UNTESTED", None, "", _now()
    db.flush()
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="CONNECTION_SET",
                     entity_type="connection", entity=row.id, org_id=actor.org_id,
                     detail={"kind": kind, "hint": row.hint, "replaced": replaced, **action_detail})
    return row


@router.post("/aws/prepare")
def prepare_aws(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """Step one: generate this organisation's external ID, so the customer can put it in their role's trust policy
    before creating the role. Idempotent: asking again returns the same ID."""
    _admin(actor)
    _need_key()
    if not connections.platform_principal():
        raise HTTPException(503, "this server has no AWS identity set up for connecting customer accounts")
    row = _row(db, actor.org_id, connections.KIND_AWS)
    if row is None:
        _save_aws(db, actor, {"external_id": connections.new_external_id()}, {"step": "prepared"})
        db.commit()
    return _state(db, actor.org_id)


@router.put("/aws")
def set_aws(body: AwsIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    _admin(actor)
    _need_key()
    try:
        role_arn, region = connections.validate_aws(body.role_arn, body.region)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    row = _row(db, actor.org_id, connections.KIND_AWS)
    external_id = _aws_cfg(row)["external_id"] if row is not None else connections.new_external_id()
    _save_aws(db, actor, {"external_id": external_id, "role_arn": role_arn, "region": region},
              {"role_arn": role_arn, "region": region})
    db.commit()
    return _state(db, actor.org_id)


@router.delete("/aws")
def remove_aws(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    _admin(actor)
    row = _row(db, actor.org_id, connections.KIND_AWS)
    if row is not None:
        audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="CONNECTION_REMOVED",
                         entity_type="connection", entity=row.id, org_id=actor.org_id, detail={"kind": row.kind})
        db.delete(row)
        db.commit()
    return _state(db, actor.org_id)


@router.post("/aws/test")
def test_aws(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """Can the platform assume the customer's role? What the role may read is checked when evidence is collected."""
    _admin(actor)
    _need_key()
    row = _row(db, actor.org_id, connections.KIND_AWS)
    if row is None:
        raise HTTPException(404, "no AWS connection is saved")
    try:
        cfg = _aws_cfg(row)
        if not cfg["role_arn"]:
            raise ValueError("paste the role ARN first")
        connections.aws_assume(cfg)
    except ValueError as exc:
        ok, reason = False, str(exc)
    else:
        ok, reason = True, ""
    row.status, row.last_error, row.last_tested_at = ("OK" if ok else "FAILED"), reason, _now()
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="CONNECTION_TESTED",
                     entity_type="connection", entity=row.id, org_id=actor.org_id,
                     detail={"kind": row.kind, "ok": ok, "reason": reason})
    db.commit()
    return _state(db, actor.org_id)
