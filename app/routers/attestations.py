"""Attested controls (ADR-060): a person's dated statement for a clause no rule judges yet.

A rule-less clause (app/content/load.py: Requirement.attestation_only) is never matched against evidence. It is met
only by a named person saying it is in place, until a date no more than a year away, optionally pointing at evidence
already uploaded. It reads ATTESTED, never PASS: the auditor judges it, the rules do not. A clause that has a rule
cannot be attested; its evidence decides it (ADR-004).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit_log, authorization
from app.actor_names import resolve_actors
from app.auth import Actor, current_actor, deny_read_only
from app.content.load import load as load_content
from app.db import get_session
from app.models import ControlAttestation, Evidence, Organization
from app.service import _ensure_org_control

router = APIRouter(prefix="/attestations", tags=["attestations"])
CONTENT = load_content()
MAX_DAYS = 366


def _today() -> date:
    return datetime.now(timezone.utc).date()


def current(db: Session, org_id: str, framework: str, today: date | None = None) -> dict[str, ControlAttestation]:
    """clause -> the newest attestation still in force (not withdrawn, not past its date)."""
    today = today or _today()
    found: dict[str, ControlAttestation] = {}
    for row in (db.query(ControlAttestation)
                .filter_by(org_id=org_id, framework=framework, revoked_at=None)
                .order_by(ControlAttestation.attested_at.desc())):
        if row.valid_until >= today:
            found.setdefault(row.clause, row)
    return found


def _out(row: ControlAttestation, live: bool, names: dict[str, str] | None = None) -> dict:
    return {"id": row.id, "framework": row.framework, "clause": row.clause, "statement": row.statement,
            "evidence_id": row.evidence_id, "attested_by": row.attested_by,
            "attested_by_display": (names or {}).get(row.attested_by, row.attested_by),
            "attested_at": row.attested_at.isoformat(), "valid_until": row.valid_until.isoformat(),
            "revoked_by": row.revoked_by, "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
            "current": live}


@router.get("")
def list_attestations(framework: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """Every attestation for one framework, newest first, with which one is in force per clause."""
    allowed = authorization.visible_clauses(db, actor)
    live = {r.id for r in current(db, actor.org_id, framework).values()}
    rows = [r for r in (db.query(ControlAttestation).filter_by(org_id=actor.org_id, framework=framework)
                        .order_by(ControlAttestation.attested_at.desc()))
            if allowed is None or (r.framework, r.clause) in allowed]
    names = resolve_actors(db, (r.attested_by for r in rows))
    return [_out(r, r.id in live, names) for r in rows]


class AttestIn(BaseModel):
    framework: str
    clause: str
    statement: str = Field(min_length=20, max_length=4000)
    valid_until: date
    evidence_id: str | None = None


def _may_attest(db: Session, actor: Actor, framework: str, clause: str) -> None:
    """An organisation admin, or the owner of that control. Never an auditor: they judge the statement."""
    if actor.is_auditor or actor.engagement_id:
        raise HTTPException(403, "an auditor reviews attestations and does not make them")
    if not actor.can_write:
        raise deny_read_only(actor, "attest a control")
    if actor.role != "ORG_ADMIN":
        allowed = authorization.visible_clauses(db, actor)
        if allowed is not None and (framework, clause) not in allowed:
            raise authorization.deny(db, actor, f"control:{framework}:{clause}", status=403,
                                     detail="only an organisation admin or this control's owner may attest it",
                                     reason="attestation outside assigned controls")


@router.post("", status_code=201)
def attest(body: AttestIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    req = CONTENT.requirement(body.framework, body.clause)
    if req is None:
        raise HTTPException(404, "no such clause")
    if not req.attestation_only:
        raise HTTPException(409, "this clause is judged by rules from evidence; upload evidence instead")
    _may_attest(db, actor, body.framework, body.clause)
    org = db.get(Organization, actor.org_id)
    if org is None or body.framework not in (org.frameworks or []):
        raise HTTPException(409, "subscribe to this framework first")
    today = _today()
    if not today < body.valid_until <= today + timedelta(days=MAX_DAYS):
        raise HTTPException(422, "valid_until must be after today and at most a year away")
    if body.evidence_id:
        ev = db.get(Evidence, body.evidence_id)
        if ev is None or ev.org_id != actor.org_id or ev.deleted_at is not None:
            raise HTTPException(422, "evidence not found in this organisation")
    control = _ensure_org_control(db, actor.org_id, body.framework, body.clause)
    row = ControlAttestation(org_id=actor.org_id, framework=body.framework, clause=body.clause,
                             statement=body.statement.strip(), evidence_id=body.evidence_id,
                             attested_by=actor.label(), valid_until=body.valid_until)
    db.add(row)
    db.flush()
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="CONTROL_ATTESTED",
                     entity_type="org_control", entity=control.id, org_id=actor.org_id,
                     detail={"attestation_id": row.id, "framework": body.framework, "clause": body.clause,
                             "valid_until": body.valid_until.isoformat(), "evidence_id": body.evidence_id})
    db.commit()
    return _out(row, True)


@router.post("/{attestation_id}/revoke")
def revoke(attestation_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    row = db.get(ControlAttestation, attestation_id)
    if row is None or row.org_id != actor.org_id:
        raise HTTPException(404)
    _may_attest(db, actor, row.framework, row.clause)
    if row.revoked_at is not None:
        raise HTTPException(409, "already withdrawn")
    row.revoked_by, row.revoked_at = actor.label(), datetime.now(timezone.utc).replace(tzinfo=None)
    control = _ensure_org_control(db, actor.org_id, row.framework, row.clause)
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="CONTROL_ATTESTATION_REVOKED",
                     entity_type="org_control", entity=control.id, org_id=actor.org_id,
                     detail={"attestation_id": row.id, "framework": row.framework, "clause": row.clause})
    db.commit()
    return _out(row, False)
