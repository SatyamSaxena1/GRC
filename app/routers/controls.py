"""Control views. Every read here goes through authorization, so an unassigned
control is invisible rather than merely non-editable."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import audit_log, authorization
from app.auth import Actor, current_actor
from app.content.load import load as load_content
from app.db import get_session
from app.ingest import draft_remediation
from app.models import (
    AuditEvent, ControlAssignment, ControlMessage, Evidence, EvidenceControlLink, GapRow,
    OrgControl, TaskRow, User,
)
from app.service import link_commitment_stale

router = APIRouter(prefix="/controls", tags=["controls"])
CONTENT = load_content()


def _requirement_text(framework: str, clause: str) -> tuple[str, str]:
    """(title, text) from the content pack, or ("", "") if the clause was
    registered manually (app/routers/admin.py) rather than from a pack."""
    try:
        pack = CONTENT.framework(framework)
    except KeyError:
        return "", ""
    for req in pack.requirements:
        if req.clause == clause:
            return req.title, req.text
    return "", ""


def _owner_emails(db: Session, control_id: str) -> list[str]:
    return [
        user.email
        for user in db.query(User)
        .join(ControlAssignment, ControlAssignment.user_id == User.id)
        .filter(ControlAssignment.org_control_id == control_id)
        .order_by(User.email)
    ]


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
    title, text = _requirement_text(control.framework, control.clause)
    return {
        "id": control.id, "framework": control.framework, "clause": control.clause,
        "title": title, "text": text,
        "owner_emails": _owner_emails(db, control.id),
        "locked": any(l.locked for l in links),
        "links": [_control_link_out(db, l, actor) for l in links],
    }


def _control_link_out(db: Session, link: EvidenceControlLink, actor: Actor) -> dict:
    out = {"id": link.id, "evidence_id": link.evidence_id, "verdict": link.verdict,
           "auditor_verdict": link.auditor_verdict, "locked": link.locked}
    # Same one-field redaction as app/routers/evidence.py::_link_payload — see
    # docs/adr/012-auditor-only-ai-nutshell.md.
    if actor.is_auditor:
        out["nutshell"] = link.nutshell
    # Not a redaction — every role sees this. See ADR-013.
    stale, reason = link_commitment_stale(db, CONTENT, actor.org_id, link)
    out["commitment_stale"] = stale
    out["stale_reason"] = reason
    return out


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
    # Events recorded against either the control itself (CONTROL_SUBMITTED) or
    # one of its evidence links (AUDITOR_VERDICT, CONTROL_LOCKED, ...) — using
    # only link ids here silently dropped every submission from its own
    # control's history.
    link_ids = [l.id for l in _links_for(db, control)]
    entity_ids = [control.id, *link_ids]
    events = db.query(AuditEvent).filter(
        AuditEvent.entity.in_(entity_ids)
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


@gaps_router.post("/{gap_id}/draft-remediation")
def draft_gap_remediation(gap_id: str, actor: Actor = Depends(current_actor),
                          db: Session = Depends(get_session)):
    """Suggested wording that would close this gap, plus what an auditor would
    want as proof it operates.

    Explicitly a drafting aid and nothing more: it writes nothing to the
    record, cannot close the gap, and cannot move a verdict — the evaluator
    still decides that from evidence (ADR-004). POST rather than GET because
    it costs a model call, not because it changes state.
    """
    gap = db.get(GapRow, gap_id)
    if gap is None:
        raise HTTPException(404)
    link = db.get(EvidenceControlLink, gap.link_id)
    evidence = db.get(Evidence, link.evidence_id) if link else None
    if evidence is None or evidence.org_id != actor.org_id:
        raise authorization.deny(db, actor, f"gap:{gap_id}", reason="cross-tenant gap access")
    # Same control-scoping every other read of this clause goes through.
    authorization.assert_may_access_control(db, actor, link.framework, link.clause)

    title, text = _requirement_text(link.framework, link.clause)
    return draft_remediation(
        link.framework, link.clause, title, text,
        {"kind": gap.kind, "attribute": gap.attribute, "detail": gap.detail,
         "actual_value": gap.actual_value, "required_value": gap.required_value},
    )


tasks_router = APIRouter(prefix="/tasks", tags=["tasks"])


def _task_query(db: Session, actor: Actor):
    """Every task in the org — visibility is filtered afterwards per row, since
    a manual task's visibility rule (owner-only) can't be expressed as one SQL
    filter alongside a gap-derived task's (control-scoped) rule."""
    return (
        db.query(TaskRow)
        .outerjoin(GapRow, GapRow.id == TaskRow.gap_id)
        .filter(TaskRow.org_id == actor.org_id)
    )


def _task_control(db: Session, task: TaskRow) -> OrgControl | None:
    return db.get(OrgControl, task.org_control_id) if task.org_control_id else None


def _task_visible(actor: Actor, allowed: set | None, control: OrgControl | None, task: TaskRow) -> bool:
    if actor.role == "ORG_ADMIN":
        return True
    if control is not None:
        # Scoped to a control, gap-derived or not: same rule as any other
        # control-scoped read (assigned controls only; engagement coverage).
        return allowed is None or (control.framework, control.clause) in allowed
    # No control context: a free-standing "go do this" task is internal work,
    # not audit evidence — never visible to an auditor, and only to the
    # employee it was actually handed to.
    return not actor.is_auditor and actor.user_id is not None and actor.user_id == task.owner_user_id


def _task_context(db: Session, actor: Actor, task_id: str) -> TaskRow:
    task = db.query(TaskRow).filter_by(id=task_id, org_id=actor.org_id).one_or_none()
    if task is None:
        raise HTTPException(404)
    allowed = authorization.visible_clauses(db, actor)
    if not _task_visible(actor, allowed, _task_control(db, task), task):
        raise authorization.deny(db, actor, f"task:{task_id}",
                                 reason="task outside assigned controls or not owned by this user")
    return task


def _task_out(db: Session, task: TaskRow) -> dict:
    owner = db.get(User, task.owner_user_id) if task.owner_user_id else None
    gap = db.get(GapRow, task.gap_id) if task.gap_id else None
    link = db.get(EvidenceControlLink, gap.link_id) if gap else None
    control = _task_control(db, task)
    return {
        "id": task.id, "title": task.title, "status": task.status, "gap_id": task.gap_id,
        "is_manual": task.gap_id is None,
        "framework": control.framework if control else None,
        "clause": control.clause if control else None,
        "required_action": gap.required_action if gap else task.description,
        "detail": gap.detail if gap else task.description,
        "actual_value": gap.actual_value if gap else None,
        "required_value": gap.required_value if gap else None,
        "evidence_id": link.evidence_id if link else None,
        "priority": task.priority,
        "owner_user_id": task.owner_user_id, "owner_email": owner.email if owner else None,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "created_by": task.created_by,
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
        query = query.filter(or_(TaskRow.title.ilike(pattern), TaskRow.description.ilike(pattern),
                                 GapRow.detail.ilike(pattern), GapRow.required_action.ilike(pattern)))
    return [
        _task_out(db, task) for task in query.all()
        if _task_visible(actor, allowed, _task_control(db, task), task)
    ]


@tasks_router.get("/owners")
def list_task_owners(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    if actor.role == "CONTROL_OWNER":
        users = [db.get(User, actor.user_id)] if actor.user_id else []
    else:
        users = db.query(User).filter_by(org_id=actor.org_id).order_by(User.email).all()
    return [{"id": user.id, "email": user.email} for user in users if user is not None]


class TaskCreate(BaseModel):
    """An org admin handing work straight to an employee — no gap involved."""
    title: str = Field(min_length=1)
    description: str = ""
    owner_user_id: str | None = None
    due_at: datetime | None = None
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    org_control_id: str | None = None  # optional: "this is about that control"


@tasks_router.post("", status_code=201)
def create_task(body: TaskCreate, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    if actor.role != "ORG_ADMIN":
        raise HTTPException(403, "only an organisation admin may assign a task")

    if body.owner_user_id:
        owner = db.get(User, body.owner_user_id)
        if owner is None or owner.org_id != actor.org_id:
            raise HTTPException(422, "assignee must belong to this organisation")

    control = None
    if body.org_control_id:
        control = db.get(OrgControl, body.org_control_id)
        if control is None or control.org_id != actor.org_id:
            raise HTTPException(422, "control must belong to this organisation")

    task = TaskRow(org_id=actor.org_id, org_control_id=control.id if control else None,
                  title=body.title, description=body.description, owner_user_id=body.owner_user_id,
                  due_at=body.due_at, priority=body.priority, created_by=actor.label())
    db.add(task)
    db.flush()
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="TASK_CREATED",
                     entity_type="task", entity=task.id, org_id=actor.org_id,
                     detail={"title": body.title, "owner_user_id": body.owner_user_id,
                             "org_control_id": task.org_control_id})
    db.commit()
    return _task_out(db, task)


@tasks_router.get("/{task_id}")
def get_task(task_id: str, actor: Actor = Depends(current_actor),
             db: Session = Depends(get_session)):
    task = _task_context(db, actor, task_id)
    result = _task_out(db, task)
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
    status: Literal["OPEN", "DONE"] | None = None


@tasks_router.patch("/{task_id}")
def update_task(task_id: str, body: TaskUpdate, actor: Actor = Depends(current_actor),
                db: Session = Depends(get_session)):
    task = _task_context(db, actor, task_id)

    assignment_fields = {"owner_user_id", "due_at", "priority"} & body.model_fields_set
    if assignment_fields and actor.role != "ORG_ADMIN":
        raise authorization.deny(db, actor, f"task:{task_id}", status=403,
                                 detail="only an organisation admin may assign or schedule tasks",
                                 reason="task update requires organisation admin")

    before = {"owner_user_id": task.owner_user_id,
              "due_at": task.due_at.isoformat() if task.due_at else None,
              "priority": task.priority, "status": task.status}

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

    if "status" in body.model_fields_set and body.status != task.status:
        if task.gap_id is not None:
            raise HTTPException(409, "status is evidence-driven for a task created from a gap; "
                                     "upload corrected evidence instead")
        is_owner = actor.user_id is not None and actor.user_id == task.owner_user_id
        if actor.role != "ORG_ADMIN" and not is_owner:
            raise authorization.deny(db, actor, f"task:{task_id}", status=403,
                                     detail="only an organisation admin or the assigned owner may "
                                            "update this task's status",
                                     reason="task status update requires admin or owner")
        task.status = body.status

    after = {"owner_user_id": task.owner_user_id,
             "due_at": task.due_at.isoformat() if task.due_at else None,
             "priority": task.priority, "status": task.status}
    if after != before:
        control = _task_control(db, task)
        audit_log.record(db, actor=actor.label(), request_id=actor.request_id,
                         action="TASK_UPDATED", entity_type="task", entity=task.id,
                         org_id=actor.org_id, before=before, after=after,
                         detail={"framework": control.framework if control else None,
                                 "clause": control.clause if control else None,
                                 "gap_id": task.gap_id})
        db.commit()
    return _task_out(db, task)


# --------------------------------------------------------------------------- messages
#
# The auditor<->auditee conversation about a control that isn't a deterministic
# verdict: a request for evidence before any exists, an auditee's request to
# reopen a locked control, or a plain comment. See app/models.py:ControlMessage.

messages_router = APIRouter(tags=["control-messages"])

MessageKind = Literal["EVIDENCE_REQUEST", "UNLOCK_REQUEST", "COMMENT"]


class MessageCreate(BaseModel):
    kind: MessageKind
    body: str = Field(min_length=1)


class MessageResolve(BaseModel):
    resolution_note: str = ""


def _message_out(m: ControlMessage) -> dict:
    return {
        "id": m.id, "org_control_id": m.org_control_id, "kind": m.kind, "body": m.body,
        "status": m.status, "created_by": m.created_by, "created_at": m.created_at.isoformat(),
        "resolved_at": m.resolved_at.isoformat() if m.resolved_at else None,
        "resolved_by": m.resolved_by, "resolution_note": m.resolution_note,
    }


@messages_router.get("/controls/{control_id}/messages")
def list_control_messages(control_id: str, actor: Actor = Depends(current_actor),
                          db: Session = Depends(get_session)):
    control = _control(db, actor, control_id)
    rows = (
        db.query(ControlMessage).filter_by(org_control_id=control.id)
        .order_by(ControlMessage.created_at).all()
    )
    return [_message_out(m) for m in rows]


@messages_router.post("/controls/{control_id}/messages", status_code=201)
def create_control_message(control_id: str, body: MessageCreate, actor: Actor = Depends(current_actor),
                           db: Session = Depends(get_session)):
    control = _control(db, actor, control_id)

    if body.kind == "EVIDENCE_REQUEST" and not actor.is_auditor:
        raise HTTPException(403, "only an auditor may request evidence")
    if body.kind == "UNLOCK_REQUEST":
        if actor.is_auditor:
            raise HTTPException(403, "an auditor unlocks directly; only the auditee requests it")
        if not any(l.locked for l in _links_for(db, control)):
            raise HTTPException(409, "control is not locked; nothing to request unlocking")

    message = ControlMessage(org_id=actor.org_id, org_control_id=control.id, kind=body.kind,
                             body=body.body, created_by=actor.label())
    db.add(message)
    db.flush()
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id,
                     action="CONTROL_MESSAGE_CREATED", entity_type="control_message", entity=message.id,
                     org_id=actor.org_id,
                     detail={"kind": body.kind, "framework": control.framework, "clause": control.clause})
    db.commit()
    return _message_out(message)


@messages_router.patch("/controls/{control_id}/messages/{message_id}/resolve")
def resolve_control_message(control_id: str, message_id: str, body: MessageResolve,
                            actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    control = _control(db, actor, control_id)
    if not actor.is_auditor:
        raise HTTPException(403, "only an auditor may resolve a request")

    message = db.query(ControlMessage).filter_by(id=message_id, org_control_id=control.id).one_or_none()
    if message is None:
        raise HTTPException(404)
    if message.status == "RESOLVED":
        raise HTTPException(409, "already resolved")

    message.status = "RESOLVED"
    message.resolved_at = datetime.now(timezone.utc)
    message.resolved_by = actor.label()
    message.resolution_note = body.resolution_note
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id,
                     action="CONTROL_MESSAGE_RESOLVED", entity_type="control_message", entity=message.id,
                     org_id=actor.org_id, detail={"kind": message.kind}, reason=body.resolution_note)
    db.commit()
    return _message_out(message)


requests_router = APIRouter(tags=["control-messages"])


@requests_router.get("/requests")
def list_requests(status: str | None = None, kind: str | None = None,
                  actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """Cross-control view of messages/requests — the auditee's 'requested from
    you' queue and the auditor's 'open requests' queue, from one endpoint."""
    allowed = authorization.visible_clauses(db, actor)
    query = (
        db.query(ControlMessage, OrgControl)
        .join(OrgControl, OrgControl.id == ControlMessage.org_control_id)
        .filter(OrgControl.org_id == actor.org_id)
        .filter(ControlMessage.kind.in_([kind] if kind else ["EVIDENCE_REQUEST", "UNLOCK_REQUEST"]))
    )
    if status:
        query = query.filter(ControlMessage.status == status)
    return [
        {**_message_out(m), "framework": c.framework, "clause": c.clause}
        for m, c in query.order_by(ControlMessage.created_at.desc()).all()
        if allowed is None or (c.framework, c.clause) in allowed
    ]
