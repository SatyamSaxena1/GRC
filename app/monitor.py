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

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.content.load import Content
from app.evaluate import evaluate
from app.models import (
    TERMINAL_EVIDENCE_STATUSES, AiRun, Evidence, EvidenceControlLink, Organization,
)

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
class AttentionReport:
    org_id: str
    checked_at: str
    horizon_days: int
    expired: tuple[ExpiringEvidence, ...] = field(default=())
    expiring_soon: tuple[ExpiringEvidence, ...] = field(default=())
    stuck: tuple[StalledEvidence, ...] = field(default=())
    failed: tuple[StalledEvidence, ...] = field(default=())

    @property
    def total(self) -> int:
        return len(self.expired) + len(self.expiring_soon) + len(self.stuck) + len(self.failed)

    def to_dict(self) -> dict:
        return {
            "org_id": self.org_id, "checked_at": self.checked_at,
            "horizon_days": self.horizon_days, "total": self.total,
            "expired": [e.to_dict() for e in self.expired],
            "expiring_soon": [e.to_dict() for e in self.expiring_soon],
            "stuck": [s.to_dict() for s in self.stuck],
            "failed": [s.to_dict() for s in self.failed],
        }


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
            org_id=org_id, lifecycle_status="CURRENT", status="READY"
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
    for evidence in db.query(Evidence).filter_by(org_id=org_id).all():
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

    return AttentionReport(
        org_id=org_id, checked_at=now.isoformat(), horizon_days=horizon_days,
        expired=tuple(expired), expiring_soon=tuple(expiring_soon),
        stuck=tuple(stuck), failed=tuple(failed),
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
        lifecycle_status="CURRENT", status="NEEDS_REVIEW"
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
            # Expiring-soon is a warning, not yet a failure; don't page for it.
            problems += len(report.expired) + len(report.stuck) + len(report.failed)

    print(f"\n{problems} item(s) need attention")
    return 1 if problems else 0


if __name__ == "__main__":
    import sys

    if "--retry-extractions" in sys.argv:
        raise SystemExit(_retry_extractions())
    raise SystemExit(_main())
