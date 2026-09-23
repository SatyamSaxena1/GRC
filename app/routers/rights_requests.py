"""Operational data-principal rights / grievance request tracking
(DPDP Act s.11-13, Rules 9 & 14).

app/content/dpdp-2023.yaml's rights/grievance clause only checks that a
PRIVACY_NOTICE *states* a rights_request_link/grievance_process/
nomination_process exists. This router is the operational counterpart: an
org logs an actual incoming request and tracks it to an SLA, instead of the
attribute just being words in a document.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit_log
from app.auth import Actor, current_actor, deny_read_only
from app.db import get_session
from app.models import OrgCommitment, RightsRequest, TaskRow

router = APIRouter(prefix="/rights-requests", tags=["rights-requests"])

DEFAULT_SLA_DAYS = 30


def _sla_days(db: Session, org_id: str) -> int:
    commitment = (
        db.query(OrgCommitment)
        .filter_by(org_id=org_id, attribute="rights_request_sla_days")
        .one_or_none()
    )
    if commitment is not None:
        try:
            value = int(commitment.value)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    return DEFAULT_SLA_DAYS


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite hands datetimes back naive; Postgres doesn't. Normalize to UTC
    before any comparison — same fix app/monitor.py already applies."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _out(r: RightsRequest, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    due = _aware(r.due_at)
    return {
        "id": r.id, "kind": r.kind, "requester_name": r.requester_name,
        "requester_contact": r.requester_contact, "details": r.details,
        "received_at": r.received_at.isoformat(),
        "due_at": r.due_at.isoformat() if r.due_at else None,
        "overdue": bool(due and r.status == "OPEN" and now > due),
        "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
        "resolution_note": r.resolution_note, "status": r.status,
        "created_by": r.created_by, "created_at": r.created_at.isoformat(),
    }


class RequestCreate(BaseModel):
    kind: Literal["ACCESS", "CORRECTION", "ERASURE", "NOMINATION", "GRIEVANCE"]
    requester_name: str = ""
    requester_contact: str = ""
    details: str = ""
    received_at: datetime


@router.post("", status_code=201)
def create_rights_request(body: RequestCreate, actor: Actor = Depends(current_actor),
                          db: Session = Depends(get_session)):
    if not actor.can_write:
        raise deny_read_only(actor, "log a rights request")

    received_at = body.received_at if body.received_at.tzinfo else body.received_at.replace(tzinfo=timezone.utc)
    due_at = received_at + timedelta(days=_sla_days(db, actor.org_id))

    request = RightsRequest(
        org_id=actor.org_id, kind=body.kind, requester_name=body.requester_name,
        requester_contact=body.requester_contact, details=body.details,
        received_at=received_at, due_at=due_at, created_by=actor.label(),
    )
    db.add(request)
    db.flush()

    task = TaskRow(
        org_id=actor.org_id, title=f"{body.kind} request from {body.requester_name or 'data principal'}",
        description=f"rights_request_id={request.id}", due_at=due_at, priority="HIGH",
        created_by=actor.label(),
    )
    db.add(task)
    db.flush()
    request.task_id = task.id

    audit_log.record(
        db, actor=actor.label(), request_id=actor.request_id, action="RIGHTS_REQUEST_LOGGED",
        entity_type="rights_request", entity=request.id, org_id=actor.org_id,
        detail={"kind": body.kind, "due_at": due_at.isoformat()},
    )
    db.commit()
    return _out(request)


@router.get("")
def list_rights_requests(status: str | None = None, actor: Actor = Depends(current_actor),
                         db: Session = Depends(get_session)):
    q = db.query(RightsRequest).filter_by(org_id=actor.org_id)
    if status:
        q = q.filter_by(status=status)
    return [_out(r) for r in q.order_by(RightsRequest.received_at.desc()).all()]


@router.get("/{request_id}")
def get_rights_request(request_id: str, actor: Actor = Depends(current_actor),
                       db: Session = Depends(get_session)):
    request = db.get(RightsRequest, request_id)
    if request is None or request.org_id != actor.org_id:
        raise HTTPException(404)
    return _out(request)


class CloseBody(BaseModel):
    resolution_note: str = ""


@router.post("/{request_id}/close")
def close_rights_request(request_id: str, body: CloseBody, actor: Actor = Depends(current_actor),
                         db: Session = Depends(get_session)):
    if not actor.can_write:
        raise deny_read_only(actor, "close a rights request")
    request = db.get(RightsRequest, request_id)
    if request is None or request.org_id != actor.org_id:
        raise HTTPException(404)

    before = {"status": request.status}
    request.status = "CLOSED"
    request.resolved_at = datetime.now(timezone.utc)
    request.resolution_note = body.resolution_note
    if request.task_id:
        task = db.get(TaskRow, request.task_id)
        if task:
            task.status = "DONE"

    audit_log.record(
        db, actor=actor.label(), request_id=actor.request_id, action="RIGHTS_REQUEST_CLOSED",
        entity_type="rights_request", entity=request.id, org_id=actor.org_id,
        before=before, after={"status": "CLOSED"}, detail={"resolution_note": body.resolution_note},
    )
    db.commit()
    return _out(request)
