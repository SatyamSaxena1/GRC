"""Control views. Every read here goes through authorization, so an unassigned
control is invisible rather than merely non-editable."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import audit_log, authorization
from app.auth import Actor, current_actor
from app.db import get_session
from app.models import AuditEvent, Evidence, EvidenceControlLink, GapRow, OrgControl, TaskRow, User

router = APIRouter(prefix="/controls", tags=["controls"])


def _control(db: Session, actor: Actor, control_id: str) -> OrgControl:
    control = db.get(OrgControl, control_id)
    if control is None or control.org_id != actor.org_id:
        raise HTTPException(404)
    return authorization.assert_may_access_control(db, actor, control.framework, control.clause)


def _links_for(db: Session, control: OrgControl):
    return (
        db.query(EvidenceControlLink)
        .join(Evidence, Evidence.id == EvidenceControlLink.evidence_id)
        .filter(Evidence.org_id == control.org_id,
                EvidenceControlLink.framework == control.framework,
                EvidenceControlLink.clause == control.clause)
        .all()
    )


@router.get("")
def list_controls(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    allowed = authorization.visible_clauses(db, actor)
    controls = db.query(OrgControl).filter_by(org_id=actor.org_id).all()
    if allowed is not None:
        controls = [c for c in controls if (c.framework, c.clause) in allowed]
    return [{"id": c.id, "framework": c.framework, "clause": c.clause} for c in controls]


@router.get("/{control_id}")
def get_control(control_id: str, actor: Actor = Depends(current_actor),
                db: Session = Depends(get_session)):
    control = _control(db, actor, control_id)
    links = _links_for(db, control)
    return {
        "id": control.id, "framework": control.framework, "clause": control.clause,
        "locked": any(l.locked for l in links),
        "links": [{"id": l.id, "evidence_id": l.evidence_id, "verdict": l.verdict,
                   "auditor_verdict": l.auditor_verdict, "locked": l.locked} for l in links],
    }


@router.get("/{control_id}/evidence")
def control_evidence(control_id: str, actor: Actor = Depends(current_actor),
                     db: Session = Depends(get_session)):
    control = _control(db, actor, control_id)
    out = []
    for link in _links_for(db, control):
        evidence = db.get(Evidence, link.evidence_id)
        out.append({"evidence_id": evidence.id, "version": evidence.version,
                    "lifecycle_status": evidence.lifecycle_status,
                    "original_filename": evidence.original_filename,
                    "verdict": link.verdict, "locked": link.locked})
    return out


@router.get("/{control_id}/history")
def control_history(control_id: str, actor: Actor = Depends(current_actor),
                    db: Session = Depends(get_session)):
    control = _control(db, actor, control_id)
    link_ids = [l.id for l in _links_for(db, control)]
    events = db.query(AuditEvent).filter(
        AuditEvent.entity.in_(link_ids or [""])
    ).order_by(AuditEvent.at).all()
    return [{"action": e.action, "actor": e.actor, "detail": e.detail,
             "reason": e.reason, "at": e.at.isoformat()} for e in events]


@router.post("/{control_id}/submit")
def submit_control(control_id: str, actor: Actor = Depends(current_actor),
                   db: Session = Depends(get_session)):
    """Auditee submits a control for review. Refused once an auditor has locked it —
    enforced in the backend, not by hiding a button."""
    control = _control(db, actor, control_id)
    if actor.is_auditor:
        raise HTTPException(403, "auditors do not submit controls")

    links = _links_for(db, control)
    if any(l.locked for l in links):
        raise HTTPException(423, "control is locked by an auditor verdict and cannot be modified")

    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="CONTROL_SUBMITTED",
                     entity_type="org_control", entity=control.id, org_id=actor.org_id,
                     detail={"framework": control.framework, "clause": control.clause})
    db.commit()
    return {"id": control.id, "submitted": True}


gaps_router = APIRouter(prefix="/gaps", tags=["gaps"])


@gaps_router.get("")
def list_gaps(status: str | None = None, actor: Actor = Depends(current_actor),
              db: Session = Depends(get_session)):
    allowed = authorization.visible_clauses(db, actor)
    query = (
        db.query(GapRow, EvidenceControlLink)
        .join(EvidenceControlLink, EvidenceControlLink.id == GapRow.link_id)
        .join(Evidence, Evidence.id == EvidenceControlLink.evidence_id)
        .filter(Evidence.org_id == actor.org_id)
    )
    if status:
        query = query.filter(GapRow.status == status)
    return [
        {"id": g.id, "framework": l.framework, "clause": l.clause, "kind": g.kind,
         "attribute": g.attribute, "detail": g.detail, "actual_value": g.actual_value,
         "required_value": g.required_value, "required_action": g.required_action,
         "status": g.status, "evidence_id": l.evidence_id,
         "resolved_by_evidence_id": g.resolved_by_evidence_id,
         "resolved_at": g.resolved_at.isoformat() if g.resolved_at else None}
        for g, l in query.all()
        if allowed is None or (l.framework, l.clause) in allowed
    ]


tasks_router = APIRouter(prefix="/tasks", tags=["tasks"])


def _task_query(db: Session, actor: Actor):
    return (
        db.query(TaskRow, GapRow, EvidenceControlLink)
        .join(GapRow, GapRow.id == TaskRow.gap_id)
        .join(EvidenceControlLink, EvidenceControlLink.id == GapRow.link_id)
        .join(Evidence, Evidence.id == EvidenceControlLink.evidence_id)
        .filter(Evidence.org_id == actor.org_id)
    )


def _task_context(db: Session, actor: Actor, task_id: str):
    row = _task_query(db, actor).filter(TaskRow.id == task_id).one_or_none()
    if row is None:
        raise HTTPException(404)
    task, gap, link = row
    allowed = authorization.visible_clauses(db, actor)
    if allowed is not None and (link.framework, link.clause) not in allowed:
        raise authorization.deny(db, actor, f"task:{task_id}", reason="task outside assigned controls")
    return task, gap, link


def _task_out(db: Session, task: TaskRow, gap: GapRow, link: EvidenceControlLink):
    owner = db.get(User, task.owner_user_id) if task.owner_user_id else None
    return {
        "id": task.id, "title": task.title, "status": task.status, "gap_id": gap.id,
        "framework": link.framework, "clause": link.clause,
        "required_action": gap.required_action, "detail": gap.detail,
        "actual_value": gap.actual_value, "required_value": gap.required_value,
        "evidence_id": link.evidence_id, "priority": task.priority,
        "owner_user_id": task.owner_user_id, "owner_email": owner.email if owner else None,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "created_at": task.created_at.isoformat(),
    }


@tasks_router.get("")
def list_tasks(status: str | None = None, priority: str | None = None,
               owner_user_id: str | None = None, q: str | None = None,
               actor: Actor = Depends(current_actor),
               db: Session = Depends(get_session)):
    allowed = authorization.visible_clauses(db, actor)
    query = _task_query(db, actor)
    if status:
        query = query.filter(TaskRow.status == status)
    if priority:
        query = query.filter(TaskRow.priority == priority)
    if owner_user_id:
        query = query.filter(TaskRow.owner_user_id == owner_user_id)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        query = query.filter(or_(TaskRow.title.ilike(pattern), GapRow.detail.ilike(pattern),
                                 GapRow.required_action.ilike(pattern)))
    return [
        _task_out(db, t, g, l)
        for t, g, l in query.all()
        if allowed is None or (l.framework, l.clause) in allowed
    ]


@tasks_router.get("/owners")
def list_task_owners(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    if actor.role == "CONTROL_OWNER":
        users = [db.get(User, actor.user_id)] if actor.user_id else []
    else:
        users = db.query(User).filter_by(org_id=actor.org_id).order_by(User.email).all()
    return [{"id": user.id, "email": user.email} for user in users if user is not None]


@tasks_router.get("/{task_id}")
def get_task(task_id: str, actor: Actor = Depends(current_actor),
             db: Session = Depends(get_session)):
    task, gap, link = _task_context(db, actor, task_id)
    result = _task_out(db, task, gap, link)
    events = db.query(AuditEvent).filter_by(entity_type="task", entity=task.id).order_by(AuditEvent.at).all()
    result["history"] = [
        {"action": event.action, "actor": event.actor, "before": event.before,
         "after": event.after, "at": event.at.isoformat()}
        for event in events
    ]
    return result


class TaskUpdate(BaseModel):
    owner_user_id: str | None = None
    due_at: datetime | None = None
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = None


@tasks_router.patch("/{task_id}")
def update_task(task_id: str, body: TaskUpdate, actor: Actor = Depends(current_actor),
                db: Session = Depends(get_session)):
    task, gap, link = _task_context(db, actor, task_id)
    if actor.role != "ORG_ADMIN":
        raise authorization.deny(db, actor, f"task:{task_id}", status=403,
                                 detail="only an organisation admin may assign or schedule tasks",
                                 reason="task update requires organisation admin")

    before = {"owner_user_id": task.owner_user_id,
              "due_at": task.due_at.isoformat() if task.due_at else None,
              "priority": task.priority}
    if "owner_user_id" in body.model_fields_set:
        if body.owner_user_id:
            owner = db.get(User, body.owner_user_id)
            if owner is None or owner.org_id != actor.org_id:
                raise HTTPException(422, "assignee must belong to this organisation")
        task.owner_user_id = body.owner_user_id
    if "due_at" in body.model_fields_set:
        task.due_at = body.due_at
    if body.priority is not None:
        task.priority = body.priority

    after = {"owner_user_id": task.owner_user_id,
             "due_at": task.due_at.isoformat() if task.due_at else None,
             "priority": task.priority}
    if after != before:
        audit_log.record(db, actor=actor.label(), request_id=actor.request_id,
                         action="TASK_UPDATED", entity_type="task", entity=task.id,
                         org_id=actor.org_id, before=before, after=after,
                         detail={"framework": link.framework, "clause": link.clause,
                                 "gap_id": gap.id})
        db.commit()
    return _task_out(db, task, gap, link)
