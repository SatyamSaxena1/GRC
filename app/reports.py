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

from app import risks, vendors
from app.models import (
    AuditEvent, Evidence, EvidenceControlLink, GapRow, Organization, Risk, TaskRow, Vendor, VendorReport,
)
from app.routers import trust

WEEK = timedelta(days=7)


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def vendor_counts(db: Session, org: Organization, now: datetime) -> dict:
    """How many active vendors are overdue for review or due soon, by the same rules as the Vendors page. Counts
    only: a vendor's name says who the organisation buys from, so it never goes in a report."""
    rows = vendors.review_states(db, org.id, now)
    overdue = sum(r["state"] in ("OVERDUE", "NEVER_REVIEWED") for _, r in rows)
    soon = sum(r["state"] == "DUE_SOON" for _, r in rows)
    return {"active": len(rows), "reviews_overdue": overdue, "reviews_due_soon": soon}


def risk_counts(db: Session, org: Organization, now: datetime) -> dict:
    """Open risks, how many are high or critical, and how many are overdue for review, by the same rules as the
    Risks page. Counts only: a risk's title can say what the organisation is worried about, so it never goes in
    a report."""
    rows = db.query(Risk).filter_by(org_id=org.id).all()
    open_rows = [r for r in rows if r.status != "CLOSED"]
    serious = sum(risks.band(risks.score(*risks.position(r))) in ("HIGH", "CRITICAL") for r in open_rows)
    return {"open": len(open_rows), "high_or_critical": serious,
            "reviews_overdue": risks.overdue_count(rows, now.date())}


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
        "vendors": vendor_counts(db, org, now),
        "risks": risk_counts(db, org, now),
    }


def _vendor_sentence(v: dict) -> str:
    """Said only when the organisation keeps a vendor register at all."""
    if not v["active"]:
        return ""
    return f" Vendors: {v['active']} active, {v['reviews_overdue']} reviews overdue, {v['reviews_due_soon']} due soon."


def _risk_sentence(k: dict) -> str:
    """Said only when the organisation keeps a risk register at all."""
    if not k["open"]:
        return ""
    return f" Risks: {k['open']} open, {k['high_or_critical']} high or critical, {k['reviews_overdue']} reviews overdue."


def text(report: dict) -> str:
    c, w, o = report["now"]["controls"], report["this_week"], report["open_now"]
    p = report["period"]
    return (f"Weekly compliance report for {report['organisation']} ({p['from']} to {p['to']}). "
            f"Controls: {c['total']}; meeting requirements {c['meeting_requirements']}, partly {c['partly_meeting']}, "
            f"not meeting {c['not_meeting']}, awaiting evidence {c['awaiting_evidence']}; "
            f"locked by an auditor {c['reviewed_and_locked_by_an_auditor']}. "
            f"This week: {w['new_gaps']} new gaps, {w['gaps_resolved']} resolved, "
            f"{w['evidence_collected_or_uploaded']} evidence collections or uploads, {w['controls_locked']} controls locked. "
            f"Open now: {o['gaps']} gaps, {o['tasks_overdue']} overdue tasks."
            + _vendor_sentence(report["vendors"]) + _risk_sentence(report["risks"]))


def markdown(report: dict) -> str:
    c, w, o, p = report["now"]["controls"], report["this_week"], report["open_now"], report["period"]
    rows = "\n".join(f"| {f['framework']} | {f['requirements_met']} of {f['requirements']} | {f['readiness_percent']}% |"
                     for f in report["now"]["frameworks"]) or "| none | | |"
    v = report["vendors"]
    vendor_md = (f"\n## Vendors\n- Active: {v['active']}\n- Reviews overdue or never done: {v['reviews_overdue']}\n"
                 f"- Reviews due within 30 days: {v['reviews_due_soon']}\n") if v["active"] else ""
    k = report["risks"]
    risk_md = (f"\n## Risks\n- Open: {k['open']}\n- High or critical: {k['high_or_critical']}\n"
               f"- Reviews overdue: {k['reviews_overdue']}\n") if k["open"] else ""
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
{vendor_md}{risk_md}"""
