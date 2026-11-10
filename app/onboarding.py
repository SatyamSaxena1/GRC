"""The first-week checklist for an organisation admin (ADR-058). Every step is read from data that exists; there is no
stored "done" flag anywhere, so nothing can be ticked without having been done, and undoing the work (unpublishing the
trust page) un-ticks it. The card hides itself once the required steps are done.

It also reports time-to-first-verdict, the activation number: how long from the organisation existing to its first
evaluation that rested on facts the platform read (Organization.first_verdict_at, set by the pipeline).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.connections import KIND_CHAT
from app.models import CollectionRun, Connection, ControlAssignment, Evidence, OrgControl, Organization, User

PEOPLE_TO_INVITE = 2


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def minutes_to_first_verdict(org: Organization) -> int | None:
    """None until there is a first verdict, and for an organisation that predates the start time being recorded."""
    if org.created_at is None or org.first_verdict_at is None:
        return None
    return max(0, round((_naive(org.first_verdict_at) - _naive(org.created_at)).total_seconds() / 60))


def _outstanding_partial_runs(db: Session, org_id: str) -> tuple[int, int]:
    """(sources that have run, of those the ones whose latest run is PARTIAL). A PARTIAL run waits for a person to
    accept the smaller scope (ADR-046) or fix the collector; the next COMPLETE run, accepted or real, clears it."""
    latest: dict[str, tuple[datetime, str]] = {}
    for source, status, at in db.query(CollectionRun.source, CollectionRun.status, CollectionRun.started_at).filter_by(org_id=org_id):
        if source not in latest or _naive(at) > latest[source][0]:
            latest[source] = (_naive(at), status)
    return len(latest), sum(1 for _, status in latest.values() if status == "PARTIAL")


def checklist(db: Session, org: Organization, user_id: str | None) -> dict:
    sources = (db.query(func.count(Connection.id)).filter(Connection.org_id == org.id, Connection.kind != KIND_CHAT).scalar() or 0)
    ran, partial = _outstanding_partial_runs(db, org.id)
    others = (db.query(func.count(User.id)).filter(User.org_id == org.id, User.active.is_(True), User.id != (user_id or ""))
              .scalar() or 0)
    steps = [
        {"id": "source", "title": "Connect a source", "link": "/connections", "optional": False,
         "done": bool(sources or ran),
         "hint": "AWS, Microsoft 365, Google Workspace, HR or GitHub. Evidence arrives without anyone uploading a file."},
        {"id": "policy", "title": "Upload a policy", "link": "/evidence", "optional": False,
         "done": (db.query(func.count(Evidence.id)).filter(
             Evidence.org_id == org.id, Evidence.deleted_at.is_(None), Evidence.artefact_type.like("%POLICY")).scalar() or 0) > 0,
         "hint": "Your first verdict comes from reading one real document against your frameworks."},
        {"id": "scope", "title": "Settle any partial collection", "link": "/connections", "optional": True,
         "done": bool(ran) and partial == 0,
         "hint": "Only if a collection came back smaller than last time: accept the smaller scope with a reason, or fix the collector."
                 + (f" {partial} waiting." if partial else "")},
        {"id": "people", "title": f"Invite {PEOPLE_TO_INVITE} people", "link": "/admin#invite-user", "optional": False,
         "done": others >= PEOPLE_TO_INVITE,
         "hint": f"{min(others, PEOPLE_TO_INVITE)} of {PEOPLE_TO_INVITE} invited. Someone to own controls, someone to read."},
        {"id": "trust", "title": "Publish your trust page", "link": "/admin#trust", "optional": False,
         "done": org.trust_token is not None,
         "hint": "Counts only, shared by a link you can switch off. Customers stop asking for a spreadsheet."},
        {"id": "owner", "title": "Give a control an owner", "link": "/controls", "optional": False,
         "done": (db.query(func.count(ControlAssignment.id)).join(OrgControl, OrgControl.id == ControlAssignment.org_control_id)
                  .filter(OrgControl.org_id == org.id).scalar() or 0) > 0,
         "hint": "Open a control and choose who is accountable for it."},
    ]
    required = [s for s in steps if not s["optional"]]
    return {
        "steps": steps,
        "done": sum(s["done"] for s in required), "total": len(required),
        "complete": all(s["done"] for s in required),
        "first_verdict": {"at": org.first_verdict_at, "minutes_from_start": minutes_to_first_verdict(org)},
    }
