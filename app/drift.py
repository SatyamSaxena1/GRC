"""What changed, from what is already stored (ADR-058): controls that turned worse, connectors gone quiet.

Evidence going stale is already answered by app/monitor.py (the 30-day look-ahead), so it is not repeated here.

The one thing the platform did not keep was a control's verdict over time: a link's `evaluated_at` is overwritten
on every run, and VerdictRecord (ADR-029) holds only an auditor's decisions. So `control_verdict_changes` is written
whenever a control's verdict differs from the last one recorded, by the same rule the Controls page uses. Two writers:
the evaluation pipeline (for the requirements it just judged) and `snapshot`, run by the weekly report for every
control, which also catches what no evaluation touches (an auditor locking or reopening a control).

"Turned worse" is a net comparison over the window, not an event count: the verdict at the start of the week against
the verdict now. PASS -> FAIL -> PASS inside one week is not reported, and moving from NO_EVIDENCE up is never worse.
A control first recorded inside the window is compared with its first row, so one that appeared as PASS and failed
three days later is caught, and one that merely appeared is not. History starts when this ships: nothing is invented
for the weeks before it.
"""

from __future__ import annotations

import collections
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import analytics
from app.models import CollectionRun, ControlVerdictChange, Evidence, EvidenceControlLink, OrgControl, Organization

# How long a connector may go without a run before it is called quiet. Customer-run scripts are usually weekly, so a
# fortnight is one missed run plus slack: tighter would nag, looser would hide a collector that has stopped.
CONNECTOR_STALE_DAYS = 14

WEEK = timedelta(days=7)
RANK = analytics._RANK  # the one ordering of verdicts, best last; ponytail: private name, promote if a third module needs it


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC, as every stored datetime reads back on SQLite


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def _iso(dt: datetime) -> str:
    return _naive(dt).replace(tzinfo=timezone.utc).isoformat()  # say it is UTC so a browser shows the right local time


def clause_verdict(db: Session, org_id: str, framework: str, clause: str) -> str:
    """One control's verdict now, by the rule the Controls page and trust page use (routers/analytics.best_verdict):
    an auditor's lock counts as its mapped verdict, and whole-estate evidence decides by its worst. A test holds the
    two equal."""
    rows = (db.query(EvidenceControlLink.verdict, Evidence.artefact_type, Evidence.lifecycle_status, Evidence.deleted_at)
            .join(Evidence, Evidence.id == EvidenceControlLink.evidence_id)
            .filter(Evidence.org_id == org_id, EvidenceControlLink.framework == framework,
                    EvidenceControlLink.clause == clause))
    return analytics.combine_verdicts([
        (analytics.AUDITOR_VERDICT.get(verdict, verdict), kind, status == "CURRENT" and deleted is None)
        for verdict, kind, status, deleted in rows])


def _history(db: Session, org_id: str) -> dict[tuple[str, str], list[ControlVerdictChange]]:
    by: dict[tuple[str, str], list[ControlVerdictChange]] = collections.defaultdict(list)
    for row in (db.query(ControlVerdictChange).filter_by(org_id=org_id)
                .order_by(ControlVerdictChange.at, ControlVerdictChange.id)):
        by[(row.framework, row.clause)].append(row)
    return by


def record(db: Session, org_id: str, clauses, *, now: datetime | None = None) -> int:
    """Write a row for each of these controls whose verdict differs from the last one recorded. The caller commits.
    Returns how many rows were written."""
    history, at, written = _history(db, org_id), now or _utcnow(), 0
    for framework, clause in sorted(set(clauses)):
        verdict = clause_verdict(db, org_id, framework, clause)
        seen = history.get((framework, clause))
        if not seen or seen[-1].verdict != verdict:
            db.add(ControlVerdictChange(org_id=org_id, framework=framework, clause=clause, verdict=verdict, at=at))
            written += 1
    return written


def snapshot(db: Session, org_id: str, *, now: datetime | None = None) -> int:
    """`record` for every control the organisation has. For the weekly run; the pipeline records only what it judged."""
    return record(db, org_id, [(c.framework, c.clause) for c in db.query(OrgControl).filter_by(org_id=org_id)], now=now)


def controls_worse(db: Session, org_id: str, *, now: datetime | None = None, window: timedelta = WEEK) -> list[dict]:
    """Controls whose verdict ranks lower now than at the start of the window, worst first."""
    until = _naive(now or _utcnow())
    since = until - window
    ids = {(c.framework, c.clause): c.id for c in db.query(OrgControl).filter_by(org_id=org_id)}
    out = []
    for (framework, clause), rows in _history(db, org_id).items():
        rows = [r for r in rows if r.at <= until]  # the position as of `until`: nothing later has happened yet
        if not rows:
            continue
        before = [r for r in rows if r.at <= since]
        start, end = (before[-1] if before else rows[0]), rows[-1]
        if RANK.get(end.verdict, 0) < RANK.get(start.verdict, 0):
            out.append({"control_id": ids.get((framework, clause)), "framework": framework, "clause": clause,
                        "was": start.verdict, "now": end.verdict, "changed_at": _iso(end.at)})
    return sorted(out, key=lambda c: (RANK.get(c["now"], 0), c["framework"], c["clause"]))


def stale_connectors(db: Session, org: Organization, *, now: datetime | None = None,
                     days: int = CONNECTOR_STALE_DAYS) -> list[dict]:
    """Sources this organisation has used whose last refresh is `days` or more ago. A FAILED run is not a refresh; a
    source that has only ever failed is dated from its latest attempt. A source the organisation scoped out of DPDP
    readiness is its own decision and is skipped, and a source never used is not "gone quiet" (onboarding says so)."""
    from app.routers.connectors import SOURCES  # lazy: connectors imports the pipeline, which imports this module

    now = _naive(now or _utcnow())
    refreshed: dict[str, datetime] = {}
    attempted: dict[str, datetime] = {}
    for source, status, at in db.query(CollectionRun.source, CollectionRun.status, CollectionRun.started_at).filter_by(org_id=org.id):
        at = _naive(at)
        attempted[source] = max(at, attempted.get(source, at))
        if status != "FAILED":
            refreshed[source] = max(at, refreshed.get(source, at))
    out = []
    for source, tried in attempted.items():
        last = refreshed.get(source, tried)
        age = (now - last).days
        if age >= days and source not in (org.dpdp_na_sources or []):
            out.append({"source": source, "label": SOURCES[source][0] if source in SOURCES else source,
                        "days": age, "last_run": _iso(last)})
    return sorted(out, key=lambda c: -c["days"])
