"""Append-only audit trail with a hash chain.

Every record links to the previous one by hash, so a silently edited or deleted
row breaks verification. Nothing here ever updates or deletes an existing row.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent


def _digest(prev_hash: str, payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(f"{prev_hash}{body}".encode()).hexdigest()


def record(
    db: Session,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity: str,
    org_id: str | None = None,
    detail: dict | None = None,
    before: dict | None = None,
    after: dict | None = None,
    reason: str = "",
    request_id: str = "",
) -> AuditEvent:
    db.flush()  # make events added earlier in this transaction visible to the chain
    prev = db.execute(
        select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)
    ).scalar_one_or_none()
    prev_hash = prev.entry_hash if prev else ""
    seq = (prev.seq + 1) if prev else 1

    payload = _payload(actor, action, entity_type, entity, org_id, detail or {},
                       before, after, reason)
    event = AuditEvent(
        org_id=org_id, actor=actor, action=action, entity_type=entity_type, entity=entity,
        detail=detail or {}, before=before, after=after, reason=reason, request_id=request_id,
        seq=seq, prev_hash=prev_hash, entry_hash=_digest(prev_hash, payload),
    )
    db.add(event)
    return event


def _payload(actor, action, entity_type, entity, org_id, detail, before, after, reason) -> dict:
    """Exactly the fields the chain commits to. One definition, used for both
    writing and verifying, so the two can never disagree."""
    return {
        "actor": actor, "action": action, "entity_type": entity_type, "entity": entity,
        "org_id": org_id, "detail": detail, "before": before, "after": after,
        "reason": reason,
    }


def verify_chain(db: Session) -> bool:
    """True when every entry still hashes to what it claims. Catches tampering."""
    prev_hash = ""
    for event in db.execute(select(AuditEvent).order_by(AuditEvent.seq)).scalars():
        payload = _payload(event.actor, event.action, event.entity_type, event.entity,
                           event.org_id, event.detail, event.before, event.after, event.reason)
        if event.prev_hash != prev_hash or event.entry_hash != _digest(prev_hash, payload):
            return False
        prev_hash = event.entry_hash
    return True
