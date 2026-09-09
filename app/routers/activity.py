"""A single chronological, authorised view of everything that happened across
the org — today `AuditEvent` is only ever browsed scoped to one control or
evidence item at a time (see `evidence_history`/`control_history`). Same
shape, no new authorization rule, just not scoped to one entity.

Firm-side actors with no engagement selected (org_id == "") get an empty list
rather than an error — firm-wide activity would need AuditEvent to carry
audit_firm_id, which it does not today. Noted as a v1 limitation, not solved
here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import Actor, current_actor
from app.db import get_session
from app.models import AuditEvent

router = APIRouter(prefix="/activity", tags=["activity"])

LIMIT = 200


@router.get("")
def list_activity(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    if not actor.org_id:
        return []
    events = (
        db.query(AuditEvent)
        .filter_by(org_id=actor.org_id)
        .order_by(AuditEvent.at.desc())
        .limit(LIMIT)
        .all()
    )
    return [
        {"action": e.action, "actor": e.actor, "entity_type": e.entity_type,
         "entity": e.entity, "detail": e.detail, "reason": e.reason,
         "at": e.at.isoformat()}
        for e in events
    ]
