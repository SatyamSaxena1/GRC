"""The expiry watch: evidence that was fine when uploaded and has quietly rotted
since, plus uploads that never reached a terminal state.

The gap this closes: freshness is judged once, at upload. tests/test_freshness.py
covers the rule itself by passing `as_of` straight to `evaluate()`; nothing
covered "stored as PASS, still stored as PASS a year later, nobody told".
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import db as db_module
from app import monitor
from app.content.load import load as load_content
from app.models import Evidence, EvidenceControlLink

CONTENT = load_content()

# A complete access control policy, shaped the way process_evidence stores it
# (name -> the whole provenance-bearing field dict). Reviewed until 2026-06-30,
# which ISO-27001 A.5.15's evidence_validity reads via `next_review_date`.
POLICY_ATTRS = {
    "approval_date": {"value": "2026-01-01"},
    "approver_role": {"value": "Chief Information Security Officer"},
    "effective_date": {"value": "2026-01-01"},
    "systems_covered": {"value": ["Corporate IT", "cardholder data environment"]},
    "next_review_date": {"value": "2026-06-30"},
    "password_min_length": {"value": 14},
    "mfa_required_for": {"value": ["remote access", "administrative access"]},
    "access_review_frequency_days": {"value": 90},
}

BEFORE_REVIEW = date(2026, 1, 15)   # not stale, and not within 30 days of it
JUST_BEFORE = date(2026, 6, 10)     # stale within the 30-day horizon
AFTER_REVIEW = date(2026, 8, 1)     # stale now


def make_ready(evidence_id: str, attrs: dict = POLICY_ATTRS, verdict: str = "PASS") -> None:
    """Put an uploaded row into the state a successful pipeline run leaves behind.

    Set directly rather than via extraction: these tests are about what happens
    to stored evidence as time passes, not about the model.
    """
    with Session(db_module.engine) as s:
        evidence = s.get(Evidence, evidence_id)
        evidence.extracted_attributes = attrs
        evidence.status = "READY"
        for link in s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id):
            link.verdict = verdict
        s.commit()


def verdicts(evidence_id: str) -> dict:
    with Session(db_module.engine) as s:
        return {
            (l.framework, l.clause): l.verdict
            for l in s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id)
        }


def report_for(org_id: str, **kwargs) -> monitor.AttentionReport:
    with Session(db_module.engine) as s:
        return monitor.attention_report(s, org_id, CONTENT, **kwargs)


def test_evidence_that_was_fresh_at_upload_is_reported_expired_later(client, bootstrap, upload):
    """The whole point. Nothing re-uploads, nothing re-evaluates, the stored
    verdict still says PASS — and the watch still surfaces it."""
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    make_ready(evidence_id)

    fresh = report_for(org_id, as_of=BEFORE_REVIEW)
    assert fresh.expired == ()

    rotted = report_for(org_id, as_of=AFTER_REVIEW)
    assert [e.evidence_id for e in rotted.expired] == [evidence_id]
    assert "ISO-27001 A.5.15" in rotted.expired[0].clauses
    assert "expired" in rotted.expired[0].detail


def test_the_report_never_rewrites_a_stored_verdict(client, bootstrap, upload):
    """Report-only is the design: an auditor may have locked these verdicts, and
    a background job flipping a locked PASS to FAIL would break locking itself."""
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    make_ready(evidence_id)
    before = verdicts(evidence_id)

    report = report_for(org_id, as_of=AFTER_REVIEW)
    assert report.expired  # it definitely saw the problem

    assert verdicts(evidence_id) == before
    assert set(before.values()) == {"PASS"}  # still PASS, untouched


def test_expiring_within_the_horizon_warns_before_it_lapses(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    make_ready(evidence_id)

    report = report_for(org_id, as_of=JUST_BEFORE)
    assert report.expired == ()
    assert [e.evidence_id for e in report.expiring_soon] == [evidence_id]

    # Far enough out and it is neither — no crying wolf all year.
    quiet = report_for(org_id, as_of=BEFORE_REVIEW)
    assert quiet.expired == () and quiet.expiring_soon == ()


def test_superseded_evidence_is_not_reported(client, bootstrap, upload):
    """Only what the organisation is currently relying on. An old version being
    out of date is not a finding — it was replaced on purpose."""
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    make_ready(evidence_id)
    assert report_for(org_id, as_of=AFTER_REVIEW).expired

    with Session(db_module.engine) as s:
        s.get(Evidence, evidence_id).lifecycle_status = "SUPERSEDED"
        s.commit()

    assert report_for(org_id, as_of=AFTER_REVIEW).expired == ()


def test_report_is_scoped_to_one_organisation(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    make_ready(evidence_id)

    other_org, _ = bootstrap(client)
    assert report_for(other_org, as_of=AFTER_REVIEW).total == 0
    assert report_for(org_id, as_of=AFTER_REVIEW).expired


def test_evidence_stuck_mid_pipeline_is_reported(client, bootstrap, upload):
    """A process restart mid-run leaves a row in a non-terminal status with
    nothing to re-enqueue it (ADR-006). The frontend would poll it forever."""
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    with Session(db_module.engine) as s:
        evidence = s.get(Evidence, evidence_id)
        evidence.status = "EVALUATING"
        s.commit()

    now = datetime.now(timezone.utc)
    assert report_for(org_id, now=now).stuck == ()  # still young, still plausible

    later = report_for(org_id, now=now + timedelta(minutes=monitor.STUCK_AFTER_MINUTES + 1))
    assert [s.evidence_id for s in later.stuck] == [evidence_id]
    assert later.stuck[0].status == "EVALUATING"


def test_failed_evidence_is_reported_separately_from_stuck(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    with Session(db_module.engine) as s:
        evidence = s.get(Evidence, evidence_id)
        evidence.status = "FAILED"
        evidence.status_detail = "storage unavailable"
        s.commit()

    report = report_for(org_id)
    assert [f.evidence_id for f in report.failed] == [evidence_id]
    assert report.failed[0].detail == "storage unavailable"
    assert report.stuck == ()  # a known failure is not a stuck job


def _retryable_ids(org_id: str, **kwargs) -> list[str]:
    from app.db import set_tenant
    with Session(db_module.engine) as s:
        set_tenant(s, org_id)
        return [e.id for e in monitor.retryable_extractions(s, **kwargs)]


def test_extraction_that_ran_while_the_model_was_down_becomes_retryable(client, bootstrap, upload):
    """No model in the test env -> the upload's extraction is UNAVAILABLE and the
    row lands at NEEDS_REVIEW. Once it has sat there a while, the sweep picks it
    up (the same thing a human clicking Re-run would do)."""
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]

    with Session(db_module.engine) as s:
        created = s.get(Evidence, evidence_id).created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)

    just_after = created + timedelta(minutes=1)
    assert _retryable_ids(org_id, now=just_after) == []  # too fresh, leave it be

    later = created + timedelta(minutes=monitor.RETRY_EXTRACTION_AFTER_MINUTES + 1)
    assert _retryable_ids(org_id, now=later) == [evidence_id]


def test_a_locked_verdict_keeps_a_row_out_of_the_retry_sweep(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    with Session(db_module.engine) as s:
        link_id = s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id).first().id
    client.post(f"/audit/links/{link_id}/lock",
                headers={"authorization": f"auditor:{engagement_id}"},
                json={"verdict": "PASS"})

    with Session(db_module.engine) as s:
        created = s.get(Evidence, evidence_id).created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    later = created + timedelta(minutes=monitor.RETRY_EXTRACTION_AFTER_MINUTES + 1)
    assert _retryable_ids(org_id, now=later) == []


def test_a_settled_ready_row_is_never_retried(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    with Session(db_module.engine) as s:
        s.get(Evidence, evidence_id).status = "READY"
        s.commit()
        created = s.get(Evidence, evidence_id).created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    later = created + timedelta(minutes=monitor.RETRY_EXTRACTION_AFTER_MINUTES + 1)
    assert _retryable_ids(org_id, now=later) == []


def test_attention_endpoint_serves_the_report(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    with Session(db_module.engine) as s:
        s.get(Evidence, evidence_id).status = "FAILED"
        s.commit()

    body = client.get("/analytics/attention", headers={"authorization": f"org:{org_id}"}).json()
    assert body["total"] == 1
    assert body["failed"][0]["evidence_id"] == evidence_id
    assert body["horizon_days"] == monitor.EXPIRY_HORIZON_DAYS
