"""Operational breach-notification tracking (DPDP Act s.8(6) / Rule 7).

app/content/dpdp-2023.yaml's "Rule 7" clause only checks that a POLICY document
*states* a breach process exists and names a board-notification hour figure.
This router is the operational counterpart: an org logs an actual breach and
the two DPDP-mandated deadlines become real due dates tracked to completion,
not just words in a PDF.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit_log
from app.auth import Actor, current_actor, deny_read_only
from app.db import get_session
from app.models import BreachEvent, OrgCommitment, TaskRow

router = APIRouter(prefix="/breach-events", tags=["breach"])

STATUTORY_BOARD_NOTIFICATION_HOURS = 72


def _board_notification_hours(db: Session, org_id: str) -> int:
    """The org's own stated commitment if it exists and is at least as strict
    as the statutory ceiling, else the statutory ceiling itself."""
    commitment = (
        db.query(OrgCommitment)
        .filter_by(org_id=org_id, attribute="board_notification_hours")
        .one_or_none()
    )
    if commitment is not None:
        try:
            value = int(commitment.value)
            if 0 < value <= STATUTORY_BOARD_NOTIFICATION_HOURS:
                return value
        except (TypeError, ValueError):
            pass
    return STATUTORY_BOARD_NOTIFICATION_HOURS


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite hands datetimes back naive; Postgres doesn't. Normalize to UTC
    before any comparison — same fix app/monitor.py already applies."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _out(b: BreachEvent, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    board_due, affected_due = _aware(b.board_notify_due_at), _aware(b.affected_notify_due_at)
    return {
        "id": b.id, "title": b.title, "description": b.description,
        "detected_at": b.detected_at.isoformat(),
        "personal_data_categories": b.personal_data_categories,
        "affected_count_estimate": b.affected_count_estimate,
        "board_notify_due_at": b.board_notify_due_at.isoformat(),
        "board_notified_at": b.board_notified_at.isoformat() if b.board_notified_at else None,
        "board_overdue": b.board_notified_at is None and now > board_due,
        "affected_notify_due_at": b.affected_notify_due_at.isoformat() if b.affected_notify_due_at else None,
        "affected_notified_at": b.affected_notified_at.isoformat() if b.affected_notified_at else None,
        "affected_overdue": bool(
            affected_due and b.affected_notified_at is None and now > affected_due
        ),
        "status": b.status, "created_by": b.created_by, "created_at": b.created_at.isoformat(),
    }


class BreachCreate(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    detected_at: datetime
    personal_data_categories: str = ""
    affected_count_estimate: int | None = None


@router.post("", status_code=201)
def create_breach_event(body: BreachCreate, actor: Actor = Depends(current_actor),
                        db: Session = Depends(get_session)):
    if actor.role != "ORG_ADMIN":
        raise HTTPException(403, "only an organisation admin may declare a breach")

    detected_at = body.detected_at if body.detected_at.tzinfo else body.detected_at.replace(tzinfo=timezone.utc)
    hours = _board_notification_hours(db, actor.org_id)
    board_due = detected_at + timedelta(hours=hours)
    # DPDP sets no fixed hour count for affected-person notice ("without
    # delay") — only compute a due date if the org has stated its own.
    affected_hours_row = (
        db.query(OrgCommitment)
        .filter_by(org_id=actor.org_id, attribute="affected_person_notification_hours")
        .one_or_none()
    )
    affected_due = None
    if affected_hours_row is not None:
        try:
            affected_due = detected_at + timedelta(hours=int(affected_hours_row.value))
        except (TypeError, ValueError):
            affected_due = None

    breach = BreachEvent(
        org_id=actor.org_id, title=body.title, description=body.description,
        detected_at=detected_at, personal_data_categories=body.personal_data_categories,
        affected_count_estimate=body.affected_count_estimate,
        board_notify_due_at=board_due, affected_notify_due_at=affected_due,
        created_by=actor.label(),
    )
    db.add(breach)
    db.flush()

    board_task = TaskRow(
        org_id=actor.org_id, title=f"Notify Board of breach: {body.title}",
        description=f"breach_event_id={breach.id}", due_at=board_due, priority="CRITICAL",
        created_by=actor.label(),
    )
    db.add(board_task)
    db.flush()
    breach.board_task_id = board_task.id

    if affected_due is not None:
        affected_task = TaskRow(
            org_id=actor.org_id, title=f"Notify affected persons of breach: {body.title}",
            description=f"breach_event_id={breach.id}", due_at=affected_due, priority="CRITICAL",
            created_by=actor.label(),
        )
        db.add(affected_task)
        db.flush()
        breach.affected_task_id = affected_task.id

    audit_log.record(
        db, actor=actor.label(), request_id=actor.request_id, action="BREACH_LOGGED",
        entity_type="breach_event", entity=breach.id, org_id=actor.org_id,
        detail={"title": body.title, "detected_at": detected_at.isoformat(),
                "board_notify_due_at": board_due.isoformat()},
    )
    db.commit()
    return _out(breach)


@router.get("")
def list_breach_events(status: str | None = None, actor: Actor = Depends(current_actor),
                       db: Session = Depends(get_session)):
    q = db.query(BreachEvent).filter_by(org_id=actor.org_id)
    if status:
        q = q.filter_by(status=status)
    return [_out(b) for b in q.order_by(BreachEvent.detected_at.desc()).all()]


@router.get("/{breach_id}")
def get_breach_event(breach_id: str, actor: Actor = Depends(current_actor),
                     db: Session = Depends(get_session)):
    breach = db.get(BreachEvent, breach_id)
    if breach is None or breach.org_id != actor.org_id:
        raise HTTPException(404)
    return _out(breach)


def _get_owned(db: Session, actor: Actor, breach_id: str) -> BreachEvent:
    breach = db.get(BreachEvent, breach_id)
    if breach is None or breach.org_id != actor.org_id:
        raise HTTPException(404)
    if not actor.can_write:
        raise deny_read_only(actor, "update a breach event")
    return breach


class NotifyBody(BaseModel):
    note: str = ""


@router.post("/{breach_id}/notify-board")
def notify_board(breach_id: str, body: NotifyBody, actor: Actor = Depends(current_actor),
                 db: Session = Depends(get_session)):
    breach = _get_owned(db, actor, breach_id)
    breach.board_notified_at = datetime.now(timezone.utc)
    breach.status = "AFFECTED_NOTIFIED" if breach.affected_notified_at else "BOARD_NOTIFIED"
    if breach.board_task_id:
        task = db.get(TaskRow, breach.board_task_id)
        if task:
            task.status = "DONE"
    audit_log.record(
        db, actor=actor.label(), request_id=actor.request_id, action="BREACH_BOARD_NOTIFIED",
        entity_type="breach_event", entity=breach.id, org_id=actor.org_id, detail={"note": body.note},
    )
    db.commit()
    return _out(breach)


@router.post("/{breach_id}/notify-affected")
def notify_affected(breach_id: str, body: NotifyBody, actor: Actor = Depends(current_actor),
                    db: Session = Depends(get_session)):
    breach = _get_owned(db, actor, breach_id)
    breach.affected_notified_at = datetime.now(timezone.utc)
    breach.status = "AFFECTED_NOTIFIED" if breach.board_notified_at else breach.status
    if breach.affected_task_id:
        task = db.get(TaskRow, breach.affected_task_id)
        if task:
            task.status = "DONE"
    audit_log.record(
        db, actor=actor.label(), request_id=actor.request_id, action="BREACH_AFFECTED_NOTIFIED",
        entity_type="breach_event", entity=breach.id, org_id=actor.org_id, detail={"note": body.note},
    )
    db.commit()
    return _out(breach)


class CloseBody(BaseModel):
    resolution_note: str = ""


@router.post("/{breach_id}/close")
def close_breach_event(breach_id: str, body: CloseBody, actor: Actor = Depends(current_actor),
                       db: Session = Depends(get_session)):
    if actor.role != "ORG_ADMIN":
        raise HTTPException(403, "only an organisation admin may close a breach event")
    breach = db.get(BreachEvent, breach_id)
    if breach is None or breach.org_id != actor.org_id:
        raise HTTPException(404)
    breach.status = "CLOSED"
    audit_log.record(
        db, actor=actor.label(), request_id=actor.request_id, action="BREACH_CLOSED",
        entity_type="breach_event", entity=breach.id, org_id=actor.org_id,
        detail={"resolution_note": body.resolution_note},
    )
    db.commit()
    return _out(breach)
