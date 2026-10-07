"""Requesting and deciding gap exceptions (ADR-021).

Who may do what:
- request: the auditee side, with write access (not an auditor, not a compliance viewer);
- approve / reject: an auditor on the engagement, and never the user who requested it;
- revoke: either side, at any time. Withdrawing an accepted risk needs no second person.

The gap is never edited. Whether an exception applies is computed on every read
(app/exceptions.py::state), so expiry, a rule change or a change in the gap's value retires it
without a scheduled job.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit_log, authorization
from app.auth import Actor, current_actor, deny_read_only
from app.content.load import load as load_content
from app.db import get_session
from app.exceptions import (
    MAX_DAYS, gap_fingerprint, rule_hash, state,
)
from app.models import Evidence, EvidenceControlLink, GapException, GapRow

router = APIRouter(tags=["exceptions"])
CONTENT = load_content()


def _payload(exc: GapException, current_state: str | None = None) -> dict:
    return {
        "id": exc.id, "framework": exc.framework, "clause": exc.clause,
        "attribute": exc.attribute, "gap_kind": exc.gap_kind, "actual_value": exc.actual_value,
        "justification": exc.justification, "compensating_control": exc.compensating_control,
        "status": exc.status, "state": current_state or state(exc, CONTENT),
        "requested_by": exc.requested_by, "requested_at": exc.requested_at.isoformat(),
        "expires_at": exc.expires_at.isoformat(),
        "decided_by": exc.decided_by, "decided_at": exc.decided_at.isoformat() if exc.decided_at else None,
        "decision_note": exc.decision_note,
    }


def _visible(db: Session, actor: Actor, framework: str, clause: str) -> bool:
    allowed = authorization.visible_clauses(db, actor)
    return allowed is None or (framework, clause) in allowed


def _gap(db: Session, actor: Actor, gap_id: str) -> tuple[GapRow, EvidenceControlLink]:
    row = (db.query(GapRow, EvidenceControlLink)
           .join(EvidenceControlLink, EvidenceControlLink.id == GapRow.link_id)
           .join(Evidence, Evidence.id == EvidenceControlLink.evidence_id)
           .filter(GapRow.id == gap_id, Evidence.org_id == actor.org_id).one_or_none())
    if row is None or not _visible(db, actor, row[1].framework, row[1].clause):
        raise HTTPException(404)
    return row


def _exception(db: Session, actor: Actor, exception_id: str) -> GapException:
    exc = db.get(GapException, exception_id)
    if exc is None or exc.org_id != actor.org_id or not _visible(db, actor, exc.framework, exc.clause):
        raise HTTPException(404)
    return exc


class ExceptionIn(BaseModel):
    justification: str = Field(min_length=20)
    compensating_control: str = ""
    expires_at: datetime


@router.post("/gaps/{gap_id}/exceptions", status_code=201)
def request_exception(gap_id: str, body: ExceptionIn, actor: Actor = Depends(current_actor),
                      db: Session = Depends(get_session)):
    if not actor.can_write:
        raise deny_read_only(actor, "request an exception")
    gap, link = _gap(db, actor, gap_id)
    if gap.status != "OPEN":
        raise HTTPException(409, "only an open gap can be excepted")
    now = datetime.now(timezone.utc)
    expires = body.expires_at if body.expires_at.tzinfo else body.expires_at.replace(tzinfo=timezone.utc)
    if not now < expires <= now + timedelta(days=MAX_DAYS):
        raise HTTPException(422, f"expires_at must be in the future and at most {MAX_DAYS} days away")

    exc = GapException(
        org_id=actor.org_id, framework=link.framework, clause=link.clause,
        attribute=gap.attribute, gap_kind=gap.kind, actual_value=gap.actual_value,
        rule_hash=rule_hash(CONTENT, link.framework, link.clause),
        value_fingerprint=gap_fingerprint(gap, link),
        justification=body.justification, compensating_control=body.compensating_control,
        requested_by=actor.label(), requested_by_user_id=actor.user_id, expires_at=expires,
    )
    db.add(exc)
    db.flush()  # assigns exc.id, which the audit event below must reference
    audit_log.record(db, actor=actor.label(), action="EXCEPTION_REQUESTED", entity_type="gap_exception",
                     entity=exc.id, org_id=actor.org_id, request_id=actor.request_id,
                     after={"gap_id": gap.id, "framework": link.framework, "clause": link.clause,
                            "attribute": gap.attribute, "expires_at": expires.isoformat()})
    db.commit()
    return _payload(exc)


class DecisionIn(BaseModel):
    note: str = Field(min_length=1)


def _decide(exception_id: str, body: DecisionIn, actor: Actor, db: Session, approve: bool) -> dict:
    if not actor.is_auditor:
        raise HTTPException(403, "only an auditor on the engagement can decide an exception")
    exc = _exception(db, actor, exception_id)
    if exc.status != "REQUESTED":
        raise HTTPException(409, f"already {exc.status.lower()}")
    if actor.user_id and actor.user_id == exc.requested_by_user_id:
        raise HTTPException(403, "the person who requested an exception cannot decide it")
    if approve and rule_hash(CONTENT, exc.framework, exc.clause) != exc.rule_hash:
        raise HTTPException(409, "the rule changed after this was requested; request it again")
    exc.status = "APPROVED" if approve else "REJECTED"
    exc.decided_by, exc.decided_by_user_id = actor.label(), actor.user_id
    exc.decided_at, exc.decision_note = datetime.now(timezone.utc), body.note
    audit_log.record(db, actor=actor.label(), action=f"EXCEPTION_{exc.status}", entity_type="gap_exception",
                     entity=exc.id, org_id=exc.org_id, request_id=actor.request_id,
                     after={"status": exc.status, "note": body.note})
    db.commit()
    return _payload(exc)


@router.post("/exceptions/{exception_id}/approve")
def approve_exception(exception_id: str, body: DecisionIn, actor: Actor = Depends(current_actor),
                      db: Session = Depends(get_session)):
    return _decide(exception_id, body, actor, db, approve=True)


@router.post("/exceptions/{exception_id}/reject")
def reject_exception(exception_id: str, body: DecisionIn, actor: Actor = Depends(current_actor),
                     db: Session = Depends(get_session)):
    return _decide(exception_id, body, actor, db, approve=False)


@router.post("/exceptions/{exception_id}/revoke")
def revoke_exception(exception_id: str, body: DecisionIn, actor: Actor = Depends(current_actor),
                     db: Session = Depends(get_session)):
    if not (actor.is_auditor or actor.can_write):
        raise deny_read_only(actor, "revoke an exception")
    exc = _exception(db, actor, exception_id)
    if exc.status not in ("REQUESTED", "APPROVED"):
        raise HTTPException(409, f"already {exc.status.lower()}")
    exc.status = "REVOKED"
    exc.decided_by, exc.decided_by_user_id = actor.label(), actor.user_id
    exc.decided_at, exc.decision_note = datetime.now(timezone.utc), body.note
    audit_log.record(db, actor=actor.label(), action="EXCEPTION_REVOKED", entity_type="gap_exception",
                     entity=exc.id, org_id=exc.org_id, request_id=actor.request_id,
                     after={"status": "REVOKED", "note": body.note})
    db.commit()
    return _payload(exc)


@router.get("/exceptions")
def list_exceptions(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    rows = db.query(GapException).filter_by(org_id=actor.org_id).order_by(GapException.requested_at.desc())
    return [_payload(e) for e in rows if _visible(db, actor, e.framework, e.clause)]
