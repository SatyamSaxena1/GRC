"""Evidence that was true once is not evidence that it is true now.

The bug this file exists to prevent: the real Aurionpro ASV attestation
(scan completed 2023-03-16, expired 2023-06-14) returned PCI-DSS 11.3.2 -> PASS
for a 2026 audit, because no freshness rule existed. An expired quarterly scan
demonstrates nothing about the period under audit.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app import db as db_module
from app.content.load import load
from app.evaluate import evaluate
from app.models import Engagement, EvidenceControlLink, GapRow

CONTENT = load()

# Transcribed from evaluation/dataset/pci_asv_attestation_2023.pdf, pages 1-2.
REAL_ASV_SCAN = {
    "scan_completed_date": "2023-03-16",
    "scan_expiry_date": "2023-06-14",
    "compliance_status": True,
    "asv_company": "Clone Systems, Inc.",
}


def link_for(attributes, as_of, clause="11.3.2"):
    return {l.clause: l for l in evaluate(
        attributes, "SCAN_REPORT", ["PCI-DSS"], CONTENT, as_of=as_of
    )}[clause]


def test_expired_asv_scan_is_rejected_not_passed():
    """The exact regression: a passing-but-expired scan must not read as compliant."""
    link = link_for(REAL_ASV_SCAN, as_of=date(2026, 8, 19))

    assert link.verdict == "FAIL", "an expired ASV scan must never evaluate to PASS"
    stale = [g for g in link.gaps if g.kind == "STALE"]
    assert len(stale) == 1
    assert stale[0].actual == "2023-06-14"
    assert "expired" in stale[0].detail


def test_same_scan_passes_inside_its_validity_window():
    """The scan is genuinely valid evidence for an audit of Q2 2023."""
    link = link_for(REAL_ASV_SCAN, as_of=date(2023, 5, 1))
    assert link.verdict == "PASS"
    assert not link.gaps


def test_expiry_is_derived_when_the_document_omits_it():
    """PCI ASV scans are valid 90 days; a report that does not state its expiry is
    still judged, from the completion date."""
    without_expiry = {k: v for k, v in REAL_ASV_SCAN.items() if k != "scan_expiry_date"}

    # 2023-03-16 + 90d = 2023-06-14
    assert link_for(without_expiry, as_of=date(2023, 6, 1)).verdict != "FAIL"

    expired = link_for(without_expiry, as_of=date(2023, 9, 1))
    assert any(g.kind == "STALE" for g in expired.gaps)


def test_missing_expiry_when_required_is_its_own_gap():
    """If neither an expiry nor an issue date is present, the evidence cannot be
    shown to be current — that is a gap, not a silent pass."""
    undated = {"compliance_status": True, "asv_company": "Clone Systems, Inc."}
    link = link_for(undated, as_of=date(2026, 1, 1))
    # PARTIAL, not FAIL: the document does say something, it just cannot be shown
    # to be current. What matters is that it never reads as PASS.
    assert link.verdict == "PARTIAL"
    assert {g.attribute for g in link.gaps} >= {"scan_completed_date", "scan_expiry_date"}


def test_stale_gap_carries_actionable_remediation():
    from app.service import _remediation

    stale = next(g for g in link_for(REAL_ASV_SCAN, as_of=date(2026, 8, 19)).gaps
                 if g.kind == "STALE")
    action = _remediation(stale)
    assert "no longer current" in action
    assert "upload" in action.lower()
    assert "insufficient" not in action.lower()


# ------------------------------------------------------------------ policy freshness


POLICY = {
    "approval_date": "2020-01-01",
    "approver_role": "Chief Information Security Officer",
    "effective_date": "2020-01-01",
    "systems_covered": ["Corporate IT", "Cardholder Data Environment"],
    "next_review_date": "2021-01-01",
}


def test_policy_past_its_review_date_is_stale():
    link = {l.clause: l for l in evaluate(
        POLICY, "POLICY", ["ISO-27001"], CONTENT, as_of=date(2026, 1, 1)
    )}["A.5.15"]
    assert link.verdict == "FAIL"
    assert any(g.kind == "STALE" for g in link.gaps)


def test_current_policy_is_not_stale():
    current = POLICY | {"approval_date": "2026-01-01", "next_review_date": "2027-01-01"}
    link = {l.clause: l for l in evaluate(
        current, "POLICY", ["ISO-27001"], CONTENT, as_of=date(2026, 6, 1)
    )}["A.5.15"]
    assert not [g for g in link.gaps if g.kind == "STALE"]


def test_policy_freshness_is_inferred_when_review_date_absent():
    """next_review_date is optional (required: false) — fall back to approval age."""
    no_review = {k: v for k, v in POLICY.items() if k != "next_review_date"}
    stale = {l.clause: l for l in evaluate(
        no_review, "POLICY", ["ISO-27001"], CONTENT, as_of=date(2026, 1, 1)
    )}["A.5.15"]
    assert any(g.kind == "STALE" for g in stale.gaps)

    fresh = {l.clause: l for l in evaluate(
        no_review | {"approval_date": "2025-12-01"}, "POLICY", ["ISO-27001"],
        CONTENT, as_of=date(2026, 1, 1),
    )}["A.5.15"]
    assert not [g for g in fresh.gaps if g.kind == "STALE"]


# ------------------------------------------------------------------ audit period


def test_freshness_is_judged_against_the_engagement_period(client, bootstrap, upload):
    """"Current" must mean current for the period under audit, not for today."""
    from app.service import _audit_as_of

    org_id, engagement_id = bootstrap(client)
    with Session(db_module.engine) as s:
        engagement = s.get(Engagement, engagement_id)
        engagement.period_end = datetime(2023, 5, 1, tzinfo=timezone.utc)
        s.commit()
        assert _audit_as_of(s, org_id) == date(2023, 5, 1)


def test_audit_period_falls_back_to_today_without_an_engagement(client, bootstrap):
    from app.service import _audit_as_of

    org_id = client.post("/admin/organizations",
                         json={"name": "Solo", "frameworks": []}).json()["id"]
    with Session(db_module.engine) as s:
        assert _audit_as_of(s, org_id) == date.today()
