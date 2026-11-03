"""Auditor findings on a control (ADR-032): an auditor raises one, the auditee responds, the auditor
closes it or reopens it. The platform never decides a finding: it records who said what, when, and
keeps every transition in the audit chain with before and after state.

A finding belongs to one control (one clause of one framework) in one organisation. Visibility
follows the control: an auditor sees findings only on controls their engagement covers, an auditee
sees findings on the controls they may see. Raising and closing need an auditor; responding needs
a writer on the auditee side (an organisation admin or an assigned control owner).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit_log, authorization, notify
from app.actor_names import resolve_actors
from app.auth import Actor, current_actor, deny_read_only
from app.db import get_session
from app.models import Finding, OrgControl
from app.routers.controls import _control

router = APIRouter(tags=["findings"])

SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
MIN_CHARS, MIN_WORDS = 15, 3


def _specific(text: str, what: str) -> str:
    text = (text or "").strip()
    if len(text) < MIN_CHARS or len(re.findall(r"\w+", text)) < MIN_WORDS:
        raise HTTPException(422, f"{what} must say what, in at least {MIN_WORDS} words and {MIN_CHARS} characters")
    return text


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _out(f: Finding, control: OrgControl, names: dict[str, str]) -> dict:
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    return {
        "id": f.id, "org_control_id": f.org_control_id, "framework": control.framework, "clause": control.clause,
        "title": f.title, "severity": f.severity, "description": f.description, "status": f.status,
        "raised_by": f.raised_by, "raised_by_display": names.get(f.raised_by, f.raised_by), "raised_at": iso(f.raised_at),
        "response": f.response, "responded_by": f.responded_by,
        "responded_by_display": names.get(f.responded_by, f.responded_by) if f.responded_by else None,
        "responded_at": iso(f.responded_at),
        "closed_by": f.closed_by, "closed_by_display": names.get(f.closed_by, f.closed_by) if f.closed_by else None,
        "closed_at": iso(f.closed_at), "close_note": f.close_note,
    }


def _state(f: Finding) -> dict:
    return {"status": f.status, "severity": f.severity, "response": f.response, "close_note": f.close_note}


def _record(db: Session, actor: Actor, action: str, f: Finding, control: OrgControl, before: dict | None, reason: str = "") -> None:
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action=action, entity_type="finding",
                     entity=f.id, org_id=actor.org_id, before=before, after=_state(f), reason=reason,
                     detail={"framework": control.framework, "clause": control.clause, "severity": f.severity,
                             "org_control_id": control.id})


def _load(db: Session, actor: Actor, finding_id: str) -> tuple[Finding, OrgControl]:
    finding = db.get(Finding, finding_id)
    if finding is None or finding.org_id != actor.org_id:
        raise HTTPException(404)
    return finding, _control(db, actor, finding.org_control_id)  # the control's own access rules apply


def _require_auditor(actor: Actor, what: str) -> None:
    if not actor.is_auditor:
        raise HTTPException(403, f"only an auditor under an engagement may {what}")


class FindingIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    description: str


class ResponseIn(BaseModel):
    response: str


class NoteIn(BaseModel):
    note: str


@router.get("/controls/{control_id}/findings")
def list_control_findings(control_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    control = _control(db, actor, control_id)
    rows = db.query(Finding).filter_by(org_id=actor.org_id, org_control_id=control.id).order_by(Finding.raised_at.desc()).all()
    names = resolve_actors(db, [x for f in rows for x in (f.raised_by, f.responded_by, f.closed_by) if x])
    return [_out(f, control, names) for f in rows]


@router.get("/findings")
def list_findings(status: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """Every finding this caller may see, newest first, optionally one status."""
    if not actor.org_id:
        return []
    allowed = authorization.visible_clauses(db, actor)
    query = db.query(Finding).filter_by(org_id=actor.org_id)
    if status:
        query = query.filter_by(status=status)
    out, controls = [], {}
    rows = query.order_by(Finding.raised_at.desc()).all()
    names = resolve_actors(db, [x for f in rows for x in (f.raised_by, f.responded_by, f.closed_by) if x])
    for f in rows:
        control = controls.setdefault(f.org_control_id, db.get(OrgControl, f.org_control_id))
        if allowed is None or (control.framework, control.clause) in allowed:
            out.append(_out(f, control, names))
    return out


@router.post("/controls/{control_id}/findings", status_code=201)
def raise_finding(control_id: str, body: FindingIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    _require_auditor(actor, "raise a finding")
    control = _control(db, actor, control_id)
    finding = Finding(org_id=actor.org_id, org_control_id=control.id, title=body.title.strip(), severity=body.severity,
                      description=_specific(body.description, "the description"), status="OPEN",
                      raised_by=actor.label(), raised_at=_now())
    db.add(finding)
    db.flush()
    _record(db, actor, "FINDING_RAISED", finding, control, None)
    db.commit()
    notify.event("FINDING_RAISED", "high" if body.severity in ("HIGH", "CRITICAL") else "medium",
                 f"A {body.severity.lower()} finding was raised on {control.framework} {control.clause}",
                 f"/controls/{control.id}", actor.org_id)
    return _out(finding, control, resolve_actors(db, [finding.raised_by]))


@router.post("/findings/{finding_id}/respond")
def respond_to_finding(finding_id: str, body: ResponseIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    if actor.is_auditor:
        raise HTTPException(403, "an auditor raises and closes findings; the auditee responds")
    if not actor.can_write:
        raise deny_read_only(actor, "respond to a finding")
    finding, control = _load(db, actor, finding_id)
    if finding.status == "CLOSED":
        raise HTTPException(409, "this finding is closed; ask the auditor to reopen it")
    before = _state(finding)
    finding.response = _specific(body.response, "the response")
    finding.responded_by, finding.responded_at, finding.status = actor.label(), _now(), "RESPONDED"
    _record(db, actor, "FINDING_RESPONDED", finding, control, before, finding.response)
    db.commit()
    return _out(finding, control, resolve_actors(db, [finding.raised_by, finding.responded_by]))


@router.post("/findings/{finding_id}/close")
def close_finding(finding_id: str, body: NoteIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    _require_auditor(actor, "close a finding")
    finding, control = _load(db, actor, finding_id)
    if finding.status == "CLOSED":
        raise HTTPException(409, "this finding is already closed")
    before = _state(finding)
    finding.close_note = _specific(body.note, "the closing note")
    finding.closed_by, finding.closed_at, finding.status = actor.label(), _now(), "CLOSED"
    _record(db, actor, "FINDING_CLOSED", finding, control, before, finding.close_note)
    db.commit()
    return _out(finding, control, resolve_actors(db, [finding.raised_by, finding.responded_by, finding.closed_by]))


@router.post("/findings/{finding_id}/reopen")
def reopen_finding(finding_id: str, body: NoteIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    _require_auditor(actor, "reopen a finding")
    finding, control = _load(db, actor, finding_id)
    if finding.status != "CLOSED":
        raise HTTPException(409, "only a closed finding can be reopened")
    before = _state(finding)
    reason = _specific(body.note, "the reason for reopening")
    finding.status, finding.closed_at = "OPEN", None
    _record(db, actor, "FINDING_REOPENED", finding, control, before, reason)
    db.commit()
    return _out(finding, control, resolve_actors(db, [finding.raised_by, finding.responded_by, finding.closed_by]))
