"""Gap exceptions that cannot quietly widen (ADR-021; pattern from the earlier Trishul attempt).

An exception is checked every time it is read, against the rule and the gap as they are now.
Nothing needs a scheduled job to retire it: it stops applying the moment it expires, the rule
it was written against changes, or the gap's value moves.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.content.load import Content
from app.models import EvidenceControlLink, GapException, GapRow

MAX_DAYS = 180  # an exception is a decision to revisit, not a setting

# What `state()` returns, and whether the exception currently waives its gap.
ACTIVE = "ACTIVE"
STATES = {ACTIVE, "REQUESTED", "REJECTED", "REVOKED", "EXPIRED", "RULE_CHANGED", "VALUE_CHANGED"}


def rule_hash(content: Content, framework: str, clause: str) -> str:
    """The requirement's whole definition, hashed: evidence requirements, mappings, delta
    conditions, validity. Any edit to the rule changes it."""
    req = content.requirement(framework, clause)
    body = req.model_dump(mode="json") if req is not None else None
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def value_fingerprint(framework: str, clause: str, attribute: str, kind: str,
                      actual_value: str | None) -> str:
    return hashlib.sha256(json.dumps([framework, clause, attribute, kind, actual_value]).encode()).hexdigest()


def gap_fingerprint(gap: GapRow, link: EvidenceControlLink) -> str:
    return value_fingerprint(link.framework, link.clause, gap.attribute, gap.kind, gap.actual_value)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def state(exc: GapException, content: Content, current_fingerprint: str | None = None,
          now: datetime | None = None) -> str:
    """Where this exception stands right now. Only ACTIVE waives anything.

    `current_fingerprint` is the fingerprint of the matching open gap today, or None when
    there is none to compare (a list view): then only rule and expiry are checked."""
    if exc.status != "APPROVED":
        return exc.status
    if _aware(exc.expires_at) <= (now or datetime.now(timezone.utc)):
        return "EXPIRED"
    if rule_hash(content, exc.framework, exc.clause) != exc.rule_hash:
        return "RULE_CHANGED"
    if current_fingerprint is not None and current_fingerprint != exc.value_fingerprint:
        return "VALUE_CHANGED"
    return ACTIVE


def active_exception(db: Session, content: Content, org_id: str, gap: GapRow,
                     link: EvidenceControlLink) -> GapException | None:
    """The approved, unexpired exception that still covers this exact gap, if any."""
    fingerprint = gap_fingerprint(gap, link)
    candidates = db.query(GapException).filter_by(
        org_id=org_id, framework=link.framework, clause=link.clause,
        attribute=gap.attribute, gap_kind=gap.kind, status="APPROVED",
    ).all()
    return next((e for e in candidates if state(e, content, fingerprint) == ACTIVE), None)
