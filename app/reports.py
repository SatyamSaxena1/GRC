"""The weekly compliance report (ADR-041): counts only, built from what is already stored.

No new table. The current position is the same content-free summary the trust page shows; "what changed
this week" comes from timestamps that already exist (gaps raised and resolved, audit events for collections
and locks). The report names no file, person or evidence text, so it is safe to post to a chat webhook.
It is delivered by the existing webhook (app/notify.py) from the monitor cron, once per organisation per
week, and the same figures can be read in the app.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AuditEvent, EvidenceControlLink, Evidence, GapRow, Organization, TaskRow
from app.routers import trust

WEEK = timedelta(days=7)


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def build(db: Session, org: Organization, now: datetime | None = None) -> dict:
    now = _naive(now or datetime.now(timezone.utc))
    since = now - WEEK
    gaps = (db.query(GapRow).join(EvidenceControlLink, GapRow.link_id == EvidenceControlLink.id)
            .join(Evidence, EvidenceControlLink.evidence_id == Evidence.id).filter(Evidence.org_id == org.id))
    events = db.query(func.count(AuditEvent.id)).filter(AuditEvent.org_id == org.id, AuditEvent.at >= since)
    current = trust.summary(db, org)
    return {
        "organisation": org.name,
        "period": {"from": since.date().isoformat(), "to": now.date().isoformat()},
        "now": {"controls": current["controls"], "frameworks": current["frameworks"]},
        "this_week": {
            "new_gaps": gaps.filter(GapRow.created_at >= since).count(),
            "gaps_resolved": gaps.filter(GapRow.resolved_at >= since).count(),
            "evidence_collected_or_uploaded": events.filter(
                AuditEvent.action.in_(["CONNECTOR_SYNCED", "EVIDENCE_UPLOADED"])).scalar(),
            "controls_locked": events.filter(AuditEvent.action == "CONTROL_LOCKED").scalar(),
        },
        "open_now": {
            "gaps": gaps.filter(GapRow.status == "OPEN").count(),
            "tasks_overdue": db.query(TaskRow).filter(TaskRow.org_id == org.id, TaskRow.status == "OPEN",
                                                      TaskRow.due_at.isnot(None), TaskRow.due_at < now).count(),
        },
    }


def text(report: dict) -> str:
    c, w, o = report["now"]["controls"], report["this_week"], report["open_now"]
    p = report["period"]
    return (f"Weekly compliance report for {report['organisation']} ({p['from']} to {p['to']}). "
            f"Controls: {c['total']}; meeting requirements {c['meeting_requirements']}, partly {c['partly_meeting']}, "
            f"not meeting {c['not_meeting']}, awaiting evidence {c['awaiting_evidence']}; "
            f"locked by an auditor {c['reviewed_and_locked_by_an_auditor']}. "
            f"This week: {w['new_gaps']} new gaps, {w['gaps_resolved']} resolved, "
            f"{w['evidence_collected_or_uploaded']} evidence collections or uploads, {w['controls_locked']} controls locked. "
            f"Open now: {o['gaps']} gaps, {o['tasks_overdue']} overdue tasks.")


def markdown(report: dict) -> str:
    c, w, o, p = report["now"]["controls"], report["this_week"], report["open_now"], report["period"]
    rows = "\n".join(f"| {f['framework']} | {f['requirements_met']} of {f['requirements']} | {f['readiness_percent']}% |"
                     for f in report["now"]["frameworks"]) or "| none | | |"
    return f"""# Weekly compliance report: {report['organisation']}

{p['from']} to {p['to']}

## Where things stand
| Controls | Meeting requirements | Partly | Not meeting | Awaiting evidence | Locked by an auditor |
|---|---|---|---|---|---|
| {c['total']} | {c['meeting_requirements']} | {c['partly_meeting']} | {c['not_meeting']} | {c['awaiting_evidence']} | {c['reviewed_and_locked_by_an_auditor']} |

| Framework | Requirements met | Readiness |
|---|---|---|
{rows}

## This week
- New gaps: {w['new_gaps']}
- Gaps resolved: {w['gaps_resolved']}
- Evidence collections or uploads: {w['evidence_collected_or_uploaded']}
- Controls locked by an auditor: {w['controls_locked']}

## Open now
- Gaps: {o['gaps']}
- Overdue tasks: {o['tasks_overdue']}
"""
