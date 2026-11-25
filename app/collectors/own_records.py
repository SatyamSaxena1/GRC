"""Facts about an organisation, read from the records this product already keeps for it (ADR-071).

No upload and no outside system: the rights-request log, vendor register, training module, policy library, breach log
and audit log are counted by fixed rules. Every attribute is always returned; the value is None when there is nothing
to judge (no rights request has ever been logged, say). A rule treats None as "not found", never as zero, so an empty
record can read as missing evidence but can never read as a pass.
"""

from __future__ import annotations

from datetime import datetime, timezone

ATTRIBUTES = (
    "rights_requests_late", "erasure_requests_unfinished", "correction_requests_unfinished",
    "personal_data_vendors_not_current", "members_without_current_training", "approved_policies_unacknowledged",
    "breaches_reported_late", "audit_log_verifies",
)


def _naive(at: datetime | None) -> datetime | None:
    return at.replace(tzinfo=None) if at is not None and at.tzinfo else at


def _late(received_due: datetime | None, resolved_at: datetime | None, now: datetime) -> bool:
    """Past its due date: answered after it, or still open after it."""
    due = _naive(received_due)
    if due is None:
        return False
    return (_naive(resolved_at) or now) > due


def _unfinished(r, now: datetime) -> bool:
    """Open past its due date, or closed with nothing written down about what was done."""
    if r.status != "CLOSED":
        return _late(r.due_at, None, now)
    return not (r.resolution_note or "").strip()


def collect(db, org_id: str, now: datetime | None = None) -> dict:
    from app import audit_log, vendors
    from app.models import BreachEvent, PolicyDoc, RightsRequest, TrainingCourse, User
    from app.routers import policies as policy_router
    from app.routers import training

    now = _naive(now or datetime.now(timezone.utc))
    out: dict = {name: None for name in ATTRIBUTES}

    requests = db.query(RightsRequest).filter_by(org_id=org_id).all()
    if requests:
        out["rights_requests_late"] = sum(_late(r.due_at, r.resolved_at, now) for r in requests)
    for kind, name in (("ERASURE", "erasure_requests_unfinished"), ("CORRECTION", "correction_requests_unfinished")):
        mine = [r for r in requests if r.kind == kind]
        if mine:
            out[name] = sum(_unfinished(r, now) for r in mine)

    # An active vendor that handles personal data and has no review, or one overdue (the same states as the Vendors page).
    states = [(v, rv) for v, rv in vendors.review_states(db, org_id, now.replace(tzinfo=timezone.utc))
              if v.data_access in ("PERSONAL", "SENSITIVE")]
    if states:
        out["personal_data_vendors_not_current"] = sum(rv["state"] in ("NEVER_REVIEWED", "OVERDUE") for _, rv in states)

    people = training._people(db, org_id)
    courses = db.query(TrainingCourse).filter_by(org_id=org_id).all()
    if courses and people:
        behind: set[str] = set()
        for c in courses:
            latest = training._latest(db, c)
            behind |= {uid for uid in people if training.state(latest.get(uid), c.cycle_days, now)[0] in ("NOT_DONE", "OVERDUE")}
        out["members_without_current_training"] = len(behind)

    approved = db.query(PolicyDoc).filter_by(org_id=org_id, status="APPROVED").filter(PolicyDoc.archived_at.is_(None)).all()
    if approved and people:
        out["approved_policies_unacknowledged"] = sum(
            len(set(people) - policy_router._accepted(db, p)) for p in approved)

    breaches = db.query(BreachEvent).filter_by(org_id=org_id).all()
    if breaches:
        def board_late(b) -> bool:
            return _late(b.board_notify_due_at, b.board_notified_at, now)

        def affected_late(b) -> bool:
            return b.affected_notify_due_at is not None and _late(b.affected_notify_due_at, b.affected_notified_at, now)
        out["breaches_reported_late"] = sum(board_late(b) or affected_late(b) for b in breaches)

    report = audit_log.verify(db, audit_log.chain_of(org_id))
    if report.events:     # an organisation with no recorded events has nothing to verify
        out["audit_log_verifies"] = report.ok

    return {"attributes": out, "collection": {"complete": True, "region": "platform"}}
