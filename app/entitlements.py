"""What an organisation's plan lets it do (ADR-054). No payment code: an operator sets the plan by hand.

Three questions, answered here and nowhere else: may it subscribe another framework, may it add another seat,
and is its trial over. An organisation with no plan (every row that existed before this layer) has no limits.
An ended trial makes the organisation read-only: writes are refused, nothing is deleted, and reads still work.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import Actor
from app.authorization import deny
from app.models import CollectionRun, Evidence, Organization, User

# plan -> (frameworks, seats). The operator may override either number for one organisation.
PLANS: dict[str, tuple[int | None, int | None]] = {
    "TRIAL": (3, 5), "DPDP_STARTER": (1, 5), "GROWTH": (3, 15), "SCALE": (10, 50),
}
TRIAL_DAYS = 14


def _utc(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)  # SQLite hands datetimes back naive


def trial_over(org: Organization, now: datetime | None = None) -> bool:
    return (org.plan == "TRIAL" and org.trial_ends_at is not None
            and _utc(org.trial_ends_at) <= (now or datetime.now(timezone.utc)))


def seats_used(db: Session, org_id: str) -> int:
    return db.query(func.count(User.id)).filter(User.org_id == org_id, User.active.is_(True)).scalar() or 0


def apply_plan(org: Organization, plan: str, *, trial_days: int | None = None,
               frameworks_limit: int | None = None, seats_limit: int | None = None) -> None:
    """Set a plan and its limits (defaults from PLANS unless overridden). A TRIAL gets an end date."""
    if plan not in PLANS:
        raise ValueError(f"plan must be one of {', '.join(PLANS)}")
    org.plan = plan
    org.frameworks_limit = frameworks_limit if frameworks_limit is not None else PLANS[plan][0]
    org.seats_limit = seats_limit if seats_limit is not None else PLANS[plan][1]
    org.trial_ends_at = (datetime.now(timezone.utc) + timedelta(days=trial_days or TRIAL_DAYS)
                         if plan == "TRIAL" else None)


def assert_writable(db: Session, actor: Actor) -> None:
    """Called for every non-read request by a signed-in caller: an ended trial keeps the data and closes the writes."""
    org = db.get(Organization, actor.org_id) if actor.org_id else None
    if org is not None and trial_over(org):
        raise deny(db, actor, f"org:{org.id}", status=402, reason="trial ended",
                   detail="Your trial has ended, so this workspace is read-only. Nothing has been deleted. "
                          "Ask your GRC contact to move you to a plan.")


def assert_may_subscribe(db: Session, actor: Actor, org: Organization, framework: str) -> None:
    if framework in org.frameworks:
        return
    if org.frameworks_limit is not None and len(org.frameworks) >= org.frameworks_limit:
        raise deny(db, actor, f"org:{org.id}", status=402, reason="framework limit", framework=framework,
                   detail=f"Your plan includes {org.frameworks_limit} framework(s) and you already have "
                          f"{len(org.frameworks)}. Ask your GRC contact to move you to a bigger plan.")


def assert_seat_free(db: Session, actor: Actor | None, org: Organization) -> None:
    if org.seats_limit is not None and seats_used(db, org.id) >= org.seats_limit:
        raise deny(db, actor, f"org:{org.id}", status=402, reason="seat limit",
                   detail=f"Your plan includes {org.seats_limit} seat(s) and all are in use. Deactivate someone "
                          "or ask your GRC contact to move you to a bigger plan.")


def usage(db: Session, org: Organization) -> dict:
    last = db.query(func.max(CollectionRun.started_at)).filter_by(org_id=org.id).scalar()
    return {
        "plan": org.plan, "trial_ends_at": org.trial_ends_at, "trial_over": trial_over(org),
        "frameworks": {"used": len(org.frameworks), "limit": org.frameworks_limit, "names": list(org.frameworks)},
        "seats": {"used": seats_used(db, org.id), "limit": org.seats_limit},
        "evidence_count": db.query(func.count(Evidence.id)).filter(
            Evidence.org_id == org.id, Evidence.deleted_at.is_(None)).scalar() or 0,
        "last_collection": last,
    }
