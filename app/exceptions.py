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


# Trishul's operational rule: rising exceptions on one rule usually mean the rule is
# miscalibrated, not that the risk is acceptable. At this many on one rule, say so.
MISCALIBRATION_THRESHOLD = 3
_OPEN, _ENDED = {ACTIVE, "REQUESTED"}, {"EXPIRED", "REVOKED", "RULE_CHANGED", "VALUE_CHANGED"}


def open_gap_fingerprints(db: Session, org_id: str) -> set[str]:
    """The value fingerprints of this organisation's open gaps, as they are now."""
    from app.models import Evidence
    rows = (db.query(GapRow, EvidenceControlLink)
            .join(EvidenceControlLink, EvidenceControlLink.id == GapRow.link_id)
            .join(Evidence, Evidence.id == EvidenceControlLink.evidence_id)
            .filter(Evidence.org_id == org_id, GapRow.status == "OPEN"))
    return {gap_fingerprint(g, l) for g, l in rows}


_GONE = "no-open-gap"  # never a real fingerprint


def rule_pressure(rows: list[GapException], content: Content,
                  open_fingerprints: set[str]) -> dict[tuple[str, str, str], dict]:
    """Per rule (framework, clause, attribute): exceptions open now, and ones that ended, which
    is what renewing one leaves behind. Rejected requests are not counted. An approved one whose
    gap no longer has the accepted value (or is closed) has ended, as active_exception sees it."""
    out: dict[tuple[str, str, str], dict] = {}
    for exc in rows:
        key = (exc.framework, exc.clause, exc.attribute)
        counts = out.setdefault(key, {"open": 0, "ended": 0})
        fingerprint = exc.value_fingerprint if exc.value_fingerprint in open_fingerprints else _GONE
        current = state(exc, content, fingerprint)
        if current in _OPEN:
            counts["open"] += 1
        elif current in _ENDED:
            counts["ended"] += 1
    for counts in out.values():
        counts["miscalibration_suspected"] = counts["open"] + counts["ended"] >= MISCALIBRATION_THRESHOLD
    return out

