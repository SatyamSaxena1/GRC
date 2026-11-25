"""DPDP duty-level not applicable: an organisation says, in writing, that one duty does not apply to it.

The duty-level twin of Organization.dpdp_na_sources (a whole connector source). The reason is at least six words, who and
when are recorded, the audit log carries it, the duty leaves the DPDP score (app/analytics.py), and it can be reversed.
Only an organisation admin may change it. A guidance-only clause is never scored, so there is nothing to mark.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app import audit_log
from app.actor_names import resolve_actors
from app.analytics import duty_na_in_force
from app.auth import Actor, current_actor
from app.content.load import load as load_content
from app.db import get_session
from app.models import DpdpDutyNa

router = APIRouter(prefix="/duty-na", tags=["duty-na"])
CONTENT = load_content()
FRAMEWORK = "DPDP"
MIN_WORDS = 6


def _out(row: DpdpDutyNa, live: bool, names: dict[str, str] | None = None) -> dict:
    return {"marked_by_display": (names or {}).get(row.marked_by, row.marked_by), "id": row.id, "framework": row.framework, "clause": row.clause, "reason": row.reason,
            "marked_by": row.marked_by, "marked_at": row.marked_at.isoformat(),
            "reversed_by": row.reversed_by, "reversed_at": row.reversed_at.isoformat() if row.reversed_at else None,
            "current": live}


@router.get("")
def list_duty_na(framework: str = FRAMEWORK, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """Every mark for one framework, newest first, with which are in force."""
    live = {r.id for r in duty_na_in_force(db, actor.org_id, framework).values()}
    rows = (db.query(DpdpDutyNa).filter_by(org_id=actor.org_id, framework=framework)
            .order_by(DpdpDutyNa.marked_at.desc()).all())
    names = resolve_actors(db, (r.marked_by for r in rows))
    return [_out(r, r.id in live, names) for r in rows]


class DutyNaIn(BaseModel):
    framework: str = FRAMEWORK
    clause: str
    reason: str

    @field_validator("reason")
    @classmethod
    def _enough_words(cls, v: str) -> str:
        if len(v.split()) < MIN_WORDS:
            raise ValueError(f"give a written reason of at least {MIN_WORDS} words")
        return v.strip()


def _admin_only(actor: Actor) -> None:
    if actor.role != "ORG_ADMIN" or actor.is_auditor or actor.engagement_id:
        raise HTTPException(403, "only an organisation admin may mark a duty not applicable")


@router.post("", status_code=201)
def mark(body: DutyNaIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    _admin_only(actor)
    if body.framework != FRAMEWORK:
        raise HTTPException(422, "only DPDP duties can be marked not applicable")
    req = CONTENT.requirement(body.framework, body.clause)
    if req is None:
        raise HTTPException(404, "no such duty")
    if req.guidance_only:
        raise HTTPException(409, "guidance-only items are not scored, so there is nothing to mark")
    if body.clause in duty_na_in_force(db, actor.org_id, body.framework):
        raise HTTPException(409, "already marked not applicable")
    row = DpdpDutyNa(org_id=actor.org_id, framework=body.framework, clause=body.clause, reason=body.reason,
                     marked_by=actor.label())
    db.add(row)
    db.flush()
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="DUTY_MARKED_NA",
                     entity_type="organization", entity=actor.org_id, org_id=actor.org_id, reason=body.reason,
                     detail={"duty_na_id": row.id, "framework": body.framework, "clause": body.clause})
    db.commit()
    return _out(row, True)


@router.post("/{duty_na_id}/reverse")
def reverse(duty_na_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    _admin_only(actor)
    row = db.get(DpdpDutyNa, duty_na_id)
    if row is None or row.org_id != actor.org_id:
        raise HTTPException(404)
    if row.reversed_at is not None:
        raise HTTPException(409, "already reversed")
    row.reversed_by, row.reversed_at = actor.label(), datetime.now(timezone.utc).replace(tzinfo=None)
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="DUTY_NA_REVERSED",
                     entity_type="organization", entity=actor.org_id, org_id=actor.org_id,
                     detail={"duty_na_id": row.id, "framework": row.framework, "clause": row.clause})
    db.commit()
    return _out(row, False)
