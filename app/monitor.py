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

from app import audit_log
from app.content.load import Content
from app.evaluate import evaluate
from app.ai import decision
from app.service import UNSUPPORTED_MIN, mismatch, process_evidence
from app.models import (
    TERMINAL_EVIDENCE_STATUSES, AiRun, BreachEvent, Evidence, EvidenceControlLink, GapException, Organization,
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
            # A broken audit chain is never a warning: silence is never green (ADR-019).
            problems += _report_chain(db, audit_log.chain_of(org.id))
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

        problems += _report_chain(db, audit_log.PLATFORM)
        _report_exception_pressure(db, orgs, content)
        _report_decision_calibration(db, orgs)

    print(f"\n{problems} item(s) need attention")
    return 1 if problems else 0


def exception_pressure(db: Session, org_ids: list[str], content: Content) -> list[dict]:
    """Rules with many exceptions across all organisations, for whoever owns the content packs.
    Counts only, never which organisations (Trishul's metric rule): the point is the rule."""
    from app.db import set_tenant
    from app.exceptions import MISCALIBRATION_THRESHOLD, open_gap_fingerprints, rule_pressure

    totals: dict[tuple[str, str, str], dict] = {}
    for org_id in org_ids:
        set_tenant(db, org_id)
        rows = db.query(GapException).filter_by(org_id=org_id).all()
        for key, counts in rule_pressure(rows, content, open_gap_fingerprints(db, org_id)).items():
            total = totals.setdefault(key, {"open": 0, "ended": 0, "orgs": 0})
            total["open"] += counts["open"]
            total["ended"] += counts["ended"]
            total["orgs"] += 1  # every organisation that contributed, open or ended
    return [{"framework": fw, "clause": clause, "attribute": attr, **counts}
            for (fw, clause, attr), counts in sorted(totals.items())
            if counts["open"] + counts["ended"] >= MISCALIBRATION_THRESHOLD]


def _report_exception_pressure(db: Session, orgs: list, content: Content) -> None:
    rows = exception_pressure(db, [o.id for o in orgs], content)
    if rows:
        print("\nRules with repeated exceptions (review the rule before renewing them):")
    for r in rows:
        print(f"  {r['framework']} {r['clause']} {r['attribute']}: {r['open']} open, "
              f"{r['ended']} ended, in {r['orgs']} organisation(s)")


CALIBRATION_DAYS = 30
SETTLE_DAYS = 7  # a type nobody corrected within a week is taken as the right one


def decision_calibration(db: Session, org_ids: list[str], now: datetime | None = None) -> list[dict]:
    """How the typed decisions of the last CALIBRATION_DAYS held up, per check and model (ADR-025).

    The artefact-type check is scored against what people did afterwards: the type of the
    version that superseded the document, or, once SETTLE_DAYS passed with no new version, the
    type it was filed as. The quote check has no such outcome yet (nobody corrects an extracted
    value in place), so only how often it flagged is reported. Counts only, never which
    organisations: the point is the model, as with exception pressure."""
    from app.db import set_tenant

    now = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    since, settled_before = now - timedelta(days=CALIBRATION_DAYS), now - timedelta(days=SETTLE_DAYS)
    totals: dict[tuple[str, str], dict] = {}
    for org_id in org_ids:
        set_tenant(db, org_id)
        runs = (db.query(AiRun).filter(AiRun.org_id == org_id, AiRun.decision_hash.isnot(None),
                                       AiRun.created_at >= since).all())
        for run in runs:
            row = totals.setdefault((run.operation, run.model), {"asked": 0, "settled": 0, "right": 0,
                                                                 "brier": 0.0, "flagged": 0})
            output = run.validated_output or {}
            if run.operation == "quote_support_check":
                row["asked"] += len(output)
                row["flagged"] += sum(1 for p in output.values() if p.get("NO", 0.0) >= UNSUPPORTED_MIN)
                continue
            row["asked"] += 1
            declared = (run.detail or {}).get("declared", "")
            row["flagged"] += mismatch(output, declared) is not None
            truth = _settled_type(db, run, declared, settled_before)
            if truth is not None:
                row["settled"] += 1
                row["right"] += decision.top(output) == truth
                row["brier"] += decision.brier(output, truth)
    return [{"operation": op, "model": model, **row,
             "accuracy": row["right"] / row["settled"] if row["settled"] else None,
             "brier": row["brier"] / row["settled"] if row["settled"] else None}
            for (op, model), row in sorted(totals.items())]


def _settled_type(db: Session, run: AiRun, declared: str, settled_before: datetime) -> str | None:
    """The type people settled on for the run's document, or None while it may still change."""
    newer = (db.query(Evidence).filter_by(org_id=run.org_id, supersedes_id=run.evidence_id)
             .order_by(Evidence.created_at).first())
    if newer is not None:
        return newer.artefact_type
    return declared if declared and run.created_at <= settled_before else None


def _report_decision_calibration(db: Session, orgs: list) -> None:
    rows = decision_calibration(db, [o.id for o in orgs])
    if rows:
        print(f"\nAI decision calibration, last {CALIBRATION_DAYS} days (ADR-025):")
    for r in rows:
        line = f"  {r['operation']} {r['model'] or '?'}: {r['asked']} asked, {r['flagged']} flagged"
        if r["operation"] != "quote_support_check":
            line += (f", {r['settled']} settled" + (f", accuracy {r['accuracy']:.0%}, brier {r['brier']:.3f}"
                                                  if r["settled"] else ""))
        print(line)


def _report_chain(db: Session, chain: str) -> int:
    report = audit_log.verify(db, chain)
    if not report.ok:
        print(f"  AUDIT CHAIN BROKEN ({chain}): {'; '.join(report.problems)}")
        return 1
    if report.unchained_after_genesis:
        print(f"  audit chain {chain}: {report.unchained_after_genesis} event(s) written outside "
              f"the chain during a deploy switchover")
    return 0


def sync_all_connectors(db: Session, org_id: str, sources: set[str] | None = None) -> list[str]:
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
        if sources is not None and source not in sources:
            continue
        if not os.environ.get(connectors._env_key(source, "URL")):
            continue
        if source in na_sources:
            continue
        try:
            evidence = connectors.sync_connector_for_org(db, org_id, "system:monitor", "", source)
        except HTTPException as exc:
            results.append(f"{source}: failed ({exc.detail})")
            continue
        # Judge it now, as the "Collect evidence" button does: a snapshot stored but never
        # evaluated would leave the controls on the previous verdict while the run reports green.
        try:
            process_evidence(db, connectors.CONTENT, evidence, "system:monitor", "")
        except Exception as exc:  # noqa: BLE001 — reported as a failure, never swallowed
            results.append(f"{source}: synced, evaluation failed ({type(exc).__name__}: {exc})")
            continue
        if evidence.status == "FAILED":
            results.append(f"{source}: synced, evaluation failed ({evidence.status_detail or 'see the evidence page'})")
        else:
            links = db.query(EvidenceControlLink).filter_by(evidence_id=evidence.id).count()
            results.append(f"{source}: synced and evaluated ({links} controls)")
    return results


def _sync_connectors(org_ids: set[str] | None = None, sources: set[str] | None = None) -> int:
    """Periodic connector sync for every org — the batch/cron counterpart to
    clicking "Collect evidence" (app/routers/connectors.py). No in-process
    scheduler (ADR-006): cron/Task Scheduler already solves recurrence."""
    from app.db import session_scope, set_tenant

    problems = 0
    with session_scope() as db:
        orgs = db.query(Organization).order_by(Organization.name).all()
        if org_ids is not None:
            # A collector URL is platform-wide: a client's own repositories must reach only that client.
            unknown = org_ids - {o.id for o in orgs}
            if unknown:
                print(f"unknown organisation id(s): {', '.join(sorted(unknown))}")
                return 1
            orgs = [o for o in orgs if o.id in org_ids]
        for org in orgs:
            set_tenant(db, org.id)  # RLS scopes each pass (no-op on SQLite)
            results = sync_all_connectors(db, org.id, sources)
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
        import argparse
        parser = argparse.ArgumentParser(prog="python -m app.monitor --sync-connectors")
        parser.add_argument("--sync-connectors", action="store_true")
        parser.add_argument("--org", action="append", help="only these organisation ids; repeatable")
        parser.add_argument("--source", action="append", help="only these connector sources; repeatable")
        args = parser.parse_args()
        raise SystemExit(_sync_connectors(set(args.org) if args.org else None,
                                          set(args.source) if args.source else None))
    raise SystemExit(_main())
