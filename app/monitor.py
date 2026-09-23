"""Continuous checks over evidence already on file — the things that rot quietly.

Two silent failure modes this catches:

  - **Expiry.** Freshness is judged once, during `app/service.py::process_evidence`,
    which only ever runs on upload. A stored PASS is frozen at that moment, so a
    policy whose review date passes next month stays PASS in the database and
    nobody is told. Nothing here re-runs on its own, so this module exists to be
    called: `GET /analytics/attention`, or `python -m app.monitor` from cron /
    Task Scheduler.

  - **Stuck jobs.** Background processing is in-process (ADR-006). A process
    restart mid-run leaves a row in a non-terminal status with nothing to
    re-enqueue it, and the frontend polls it forever.

**The default (report) path never writes.** Expiry is reported, not applied:
auditors lock verdicts, and a job silently flipping a locked PASS to FAIL would
break the guarantee locking exists to provide. The report tells a human to
upload fresh evidence, which goes through the ordinary pipeline.

The one opt-in exception is `python -m app.monitor --retry-extractions`: it
re-runs the pipeline for evidence whose extraction ran while the analysis model
was unavailable (status NEEDS_REVIEW, latest AiRun UNAVAILABLE/ERROR, nothing
locked). That is the same thing `POST /evidence/{id}/reprocess` does by hand —
recovery from an outage, never a recomputation of a locked result.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.content.load import Content
from app.evaluate import evaluate
from app.models import (
    TERMINAL_EVIDENCE_STATUSES, AiRun, BreachEvent, Evidence, EvidenceControlLink, Organization,
    RightsRequest,
)

# Same approaching-deadline window for breach/DSR sweeps as notifications.py
# uses, and for the cron report — one source of truth for "soon" vs "overdue".
DEADLINE_WARNING_HOURS = 48

# How far ahead to warn. Matches the 30-day threshold app/quality.py::_freshness
# already uses to mark evidence as approaching expiry.
EXPIRY_HORIZON_DAYS = 30

# Beyond any legitimate run: OLLAMA_TIMEOUT_S defaults to 180s, and a slow VLM
# pass over a large scanned PDF is still minutes, not a quarter of an hour.
STUCK_AFTER_MINUTES = 15

# How long to wait after an outage-damaged run before auto-retrying it, so a
# still-down model isn't hammered and a human clicking "Re-run" first isn't
# raced.
RETRY_EXTRACTION_AFTER_MINUTES = 10


@dataclass(frozen=True)
class ExpiringEvidence:
    evidence_id: str
    original_filename: str
    artefact_type: str
    # Which requirements are driving it, so the fix is obvious from the report.
    clauses: tuple[str, ...] = field(default=())
    detail: str = ""

    def to_dict(self) -> dict:
        return {"evidence_id": self.evidence_id, "original_filename": self.original_filename,
                "artefact_type": self.artefact_type, "clauses": list(self.clauses),
                "detail": self.detail}


@dataclass(frozen=True)
class StalledEvidence:
    evidence_id: str
    original_filename: str
    status: str
    age_minutes: int
    detail: str = ""

    def to_dict(self) -> dict:
        return {"evidence_id": self.evidence_id, "original_filename": self.original_filename,
                "status": self.status, "age_minutes": self.age_minutes, "detail": self.detail}


@dataclass(frozen=True)
class DeadlineItem:
    id: str
    title: str
    due_at: str
    overdue: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "due_at": self.due_at,
                "overdue": self.overdue, "detail": self.detail}


@dataclass(frozen=True)
class AttentionReport:
    org_id: str
    checked_at: str
    horizon_days: int
    expired: tuple[ExpiringEvidence, ...] = field(default=())
    expiring_soon: tuple[ExpiringEvidence, ...] = field(default=())
    stuck: tuple[StalledEvidence, ...] = field(default=())
    failed: tuple[StalledEvidence, ...] = field(default=())
    breach: tuple[DeadlineItem, ...] = field(default=())
    dsr: tuple[DeadlineItem, ...] = field(default=())

    @property
    def total(self) -> int:
        return (len(self.expired) + len(self.expiring_soon) + len(self.stuck) + len(self.failed)
                + len(self.breach) + len(self.dsr))

    def to_dict(self) -> dict:
        return {
            "org_id": self.org_id, "checked_at": self.checked_at,
            "horizon_days": self.horizon_days, "total": self.total,
            "expired": [e.to_dict() for e in self.expired],
            "expiring_soon": [e.to_dict() for e in self.expiring_soon],
            "stuck": [s.to_dict() for s in self.stuck],
            "failed": [s.to_dict() for s in self.failed],
            "breach": [b.to_dict() for b in self.breach],
            "dsr": [d.to_dict() for d in self.dsr],
        }


def breach_and_dsr_attention(db: Session, org_id: str, *, now: datetime | None = None) -> dict:
    """Open breach-notification and DSR deadlines that are overdue or due
    within DEADLINE_WARNING_HOURS — the single place that window is defined,
    shared by the cron report and app/routers/notifications.py so the two
    never disagree about what counts as "soon"."""
    now = now or datetime.now(timezone.utc)
    horizon = now + timedelta(hours=DEADLINE_WARNING_HOURS)

    def aware(dt: datetime | None) -> datetime | None:
        # SQLite hands these back naive.
        return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt

    breach_items: list[DeadlineItem] = []
    for b in db.query(BreachEvent).filter_by(org_id=org_id).filter(BreachEvent.status != "CLOSED").all():
        board_due = aware(b.board_notify_due_at)
        if b.board_notified_at is None and board_due <= horizon:
            breach_items.append(DeadlineItem(
                id=b.id, title=f"Notify Board: {b.title}", due_at=b.board_notify_due_at.isoformat(),
                overdue=now > board_due, detail="board notification",
            ))
        affected_due = aware(b.affected_notify_due_at)
        if affected_due is not None and b.affected_notified_at is None and affected_due <= horizon:
            breach_items.append(DeadlineItem(
                id=b.id, title=f"Notify affected persons: {b.title}",
                due_at=b.affected_notify_due_at.isoformat(),
                overdue=now > affected_due, detail="affected-person notification",
            ))

    dsr_items: list[DeadlineItem] = []
    for r in db.query(RightsRequest).filter_by(org_id=org_id, status="OPEN").all():
        due = aware(r.due_at)
        if due is not None and due <= horizon:
            dsr_items.append(DeadlineItem(
                id=r.id, title=f"{r.kind} request from {r.requester_name or 'data principal'}",
                due_at=r.due_at.isoformat(), overdue=now > due, detail=r.kind,
            ))

    return {"breach": breach_items, "dsr": dsr_items}


def _stale_clauses(evidence: Evidence, content: Content, frameworks: list[str],
                   as_of: date) -> dict[str, str]:
    """{'PCI-DSS 11.3.2': 'evidence expired ...'} for this evidence at `as_of`.

    Runs the ordinary evaluator rather than reading an expiry date directly, so
    "expired" keeps exactly one definition. That also gets per-requirement
    windows right for free: the same scan report is valid 90 days under PCI-DSS
    but a year under GDPR, because validity is a property of the requirement,
    not of the document.
    """
    attributes = evidence.attribute_values()
    return {
        f"{link.framework} {link.clause}": gap.detail
        for link in evaluate(attributes, evidence.artefact_type, frameworks, content, as_of)
        for gap in link.gaps
        if gap.kind == "STALE"
    }


def attention_report(db: Session, org_id: str, content: Content, *,
                     as_of: date | None = None, now: datetime | None = None,
                     horizon_days: int = EXPIRY_HORIZON_DAYS,
                     stuck_after_minutes: int = STUCK_AFTER_MINUTES) -> AttentionReport:
    """Everything about this organisation's evidence that needs a human, today.

    `as_of` is today, deliberately not `service._audit_as_of`'s engagement period
    end — that answers a different question ("was this valid for the period under
    audit"). This one asks "has this rotted by now".
    """
    as_of = as_of or date.today()
    now = now or datetime.now(timezone.utc)
    org = db.get(Organization, org_id)
    frameworks = list(org.frameworks) if org else []

    expired: list[ExpiringEvidence] = []
    expiring_soon: list[ExpiringEvidence] = []

    if frameworks:
        pool = db.query(Evidence).filter_by(
            org_id=org_id, lifecycle_status="CURRENT", status="READY", deleted_at=None,
        ).all()
        horizon = as_of + timedelta(days=horizon_days)

        for evidence in pool:
            stale_now = _stale_clauses(evidence, content, frameworks, as_of)
            # Same rule, run once more against a future date: whatever becomes
            # stale by the horizon but is not stale yet is the early warning.
            stale_later = _stale_clauses(evidence, content, frameworks, horizon)
            soon = {k: v for k, v in stale_later.items() if k not in stale_now}

            if stale_now:
                expired.append(ExpiringEvidence(
                    evidence_id=evidence.id, original_filename=evidence.original_filename,
                    artefact_type=evidence.artefact_type, clauses=tuple(sorted(stale_now)),
                    detail=next(iter(stale_now.values())),
                ))
            if soon:
                expiring_soon.append(ExpiringEvidence(
                    evidence_id=evidence.id, original_filename=evidence.original_filename,
                    artefact_type=evidence.artefact_type, clauses=tuple(sorted(soon)),
                    detail=next(iter(soon.values())),
                ))

    stuck: list[StalledEvidence] = []
    failed: list[StalledEvidence] = []
    for evidence in db.query(Evidence).filter_by(org_id=org_id, deleted_at=None).all():
        if evidence.status in TERMINAL_EVIDENCE_STATUSES and evidence.status != "FAILED":
            continue
        created = evidence.created_at
        if created.tzinfo is None:  # SQLite hands these back naive
            created = created.replace(tzinfo=timezone.utc)
        age_minutes = int((now - created).total_seconds() // 60)
        row = StalledEvidence(
            evidence_id=evidence.id, original_filename=evidence.original_filename,
            status=evidence.status, age_minutes=age_minutes, detail=evidence.status_detail,
        )
        if evidence.status == "FAILED":
            failed.append(row)
        elif age_minutes >= stuck_after_minutes:
            stuck.append(row)

    deadlines = breach_and_dsr_attention(db, org_id, now=now)

    return AttentionReport(
        org_id=org_id, checked_at=now.isoformat(), horizon_days=horizon_days,
        expired=tuple(expired), expiring_soon=tuple(expiring_soon),
        stuck=tuple(stuck), failed=tuple(failed),
        breach=tuple(deadlines["breach"]), dsr=tuple(deadlines["dsr"]),
    )


def retryable_extractions(db: Session, *, now: datetime | None = None,
                          older_than_minutes: int = RETRY_EXTRACTION_AFTER_MINUTES,
                          ) -> list[Evidence]:
    """Current evidence sitting at NEEDS_REVIEW because the analysis model was
    unavailable or errored, old enough to be worth another try, with no locked
    verdict in the way. Same eligibility `POST /evidence/{id}/reprocess` applies.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=older_than_minutes)
    out: list[Evidence] = []
    rows = db.query(Evidence).filter_by(
        lifecycle_status="CURRENT", status="NEEDS_REVIEW", deleted_at=None,
    ).all()
    for evidence in rows:
        created = evidence.created_at
        if created.tzinfo is None:  # SQLite hands these back naive
            created = created.replace(tzinfo=timezone.utc)
        if created > cutoff:
            continue
        latest = (
            db.query(AiRun)
            .filter_by(evidence_id=evidence.id, operation="attribute_extraction")
            .order_by(AiRun.created_at.desc())
            .first()
        )
        if latest is None or latest.status not in {"UNAVAILABLE", "ERROR"}:
            continue  # INVALID_OUTPUT is a model that answered, just badly — a human looks
        # `locked` is a property, not a column — check it in Python.
        links = db.query(EvidenceControlLink).filter_by(evidence_id=evidence.id).all()
        if any(link.locked for link in links):
            continue
        out.append(evidence)
    return out


# --------------------------------------------------------------------------- CLI


def _retry_extractions() -> int:
    """Re-run the pipeline for every org's outage-damaged evidence. Writes.

    Deliberately a separate entrypoint from the read-only report: run it from
    cron a few minutes behind the report, and it heals the exact rows the report
    lists under STUCK/NEEDS_REVIEW-with-an-UNAVAILABLE-run.
    """
    from app.content.load import load as load_content
    from app.db import session_scope, set_tenant
    from app.service import process_evidence

    content = load_content()
    retried = 0
    with session_scope() as db:
        for org in db.query(Organization).order_by(Organization.name).all():
            set_tenant(db, org.id)  # RLS scopes each pass (no-op on SQLite)
            for evidence in retryable_extractions(db):
                print(f"  re-running {evidence.original_filename or evidence.id} ({org.name})")
                process_evidence(db, content, evidence, "monitor:retry-extractions")
                retried += 1
    print(f"\n{retried} extraction(s) re-run")
    return 0


def _main() -> int:
    """Report for every organisation; non-zero exit when something needs a human.

    A plain script rather than an in-process scheduler, deliberately (ADR-006):
    cron or Task Scheduler already solves recurrence, and a non-zero exit is
    something every job runner already knows how to alert on.
    """
    from app.content.load import load as load_content
    from app.db import session_scope, set_tenant

    content = load_content()
    problems = 0
    with session_scope() as db:
        orgs = db.query(Organization).order_by(Organization.name).all()
        for org in orgs:
            set_tenant(db, org.id)  # RLS scopes each pass (no-op on SQLite)
            report = attention_report(db, org.id, content)
            print(f"\n{org.name} ({org.id})")
            if report.total == 0:
                print("  nothing needs attention")
                continue
            for label, rows in (("EXPIRED", report.expired),
                                ("EXPIRING SOON", report.expiring_soon)):
                for row in rows:
                    print(f"  {label}: {row.original_filename or row.evidence_id} "
                          f"[{', '.join(row.clauses)}] — {row.detail}")
            for label, rows in (("FAILED", report.failed), ("STUCK", report.stuck)):
                for row in rows:
                    print(f"  {label}: {row.original_filename or row.evidence_id} "
                          f"({row.status}, {row.age_minutes}m) {row.detail}")
            for label, rows in (("BREACH DEADLINE", report.breach), ("DSR DEADLINE", report.dsr)):
                for row in rows:
                    print(f"  {label}: {row.title} due {row.due_at}"
                          f"{' (OVERDUE)' if row.overdue else ''}")
            # Expiring-soon/due-soon is a warning, not yet a failure; only an
            # overdue deadline pages.
            problems += (len(report.expired) + len(report.stuck) + len(report.failed)
                        + sum(1 for b in report.breach if b.overdue)
                        + sum(1 for d in report.dsr if d.overdue))

    print(f"\n{problems} item(s) need attention")
    return 1 if problems else 0


def sync_all_connectors(db: Session, org_id: str) -> list[str]:
    """Sync every configured, in-scope DPDP connector source for one org —
    the batch counterpart to POST /connectors/{source}/sync, sharing its
    implementation via app.routers.connectors::sync_connector_for_org so
    there is one place that actually pulls and stores a connector snapshot."""
    from fastapi import HTTPException

    from app.routers import connectors

    org = db.get(Organization, org_id)
    na_sources = set(org.dpdp_na_sources) if org else set()
    results = []
    for source in connectors.SOURCES:
        if not os.environ.get(connectors._env_key(source, "URL")):
            continue
        if source in na_sources:
            continue
        try:
            connectors.sync_connector_for_org(db, org_id, "system:monitor", "", source)
            results.append(f"{source}: synced")
        except HTTPException as exc:
            results.append(f"{source}: failed ({exc.detail})")
    return results


def _sync_connectors() -> int:
    """Periodic connector sync for every org — the batch/cron counterpart to
    clicking "Collect evidence" (app/routers/connectors.py). No in-process
    scheduler (ADR-006): cron/Task Scheduler already solves recurrence."""
    from app.db import session_scope, set_tenant

    problems = 0
    with session_scope() as db:
        for org in db.query(Organization).order_by(Organization.name).all():
            set_tenant(db, org.id)  # RLS scopes each pass (no-op on SQLite)
            results = sync_all_connectors(db, org.id)
            if not results:
                continue
            print(f"\n{org.name} ({org.id})")
            for line in results:
                print(f"  {line}")
                if "failed" in line:
                    problems += 1

    print(f"\n{problems} connector(s) failed to sync")
    return 1 if problems else 0


if __name__ == "__main__":
    import sys

    if "--retry-extractions" in sys.argv:
        raise SystemExit(_retry_extractions())
    if "--sync-connectors" in sys.argv:
        raise SystemExit(_sync_connectors())
    raise SystemExit(_main())
