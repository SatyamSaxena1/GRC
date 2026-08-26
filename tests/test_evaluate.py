"""The check the whole product hangs on: one policy, two frameworks, different verdicts."""

from datetime import date

import pytest

from app.content.load import load
from app.evaluate import evaluate

CONTENT = load()

# A real-ish Access Control Policy: fine for ISO, short of PCI on two specific points.
POLICY = {
    "approval_date": "2026-03-01",
    "approver_role": "Chief Information Security Officer",
    "effective_date": "2026-03-15",
    "systems_covered": ["Corporate IT", "HR Systems"],
    "password_min_length": 10,
    "mfa_required_for": ["Remote access", "Administrative access"],
    "access_review_frequency_days": 180,
}


def links_by_clause(frameworks):
    return {l.clause: l for l in evaluate(POLICY, "POLICY", frameworks, CONTENT)}


def test_iso_passes_outright():
    links = links_by_clause(["ISO-27001"])
    assert {c: l.verdict for c, l in links.items()} == {
        "A.5.15": "PASS", "A.5.17": "PASS", "A.5.18": "PASS"
    }
    assert all(not l.gaps for l in links.values())


def test_same_evidence_is_partial_on_pci_with_two_specific_gaps():
    links = links_by_clause(["PCI-DSS"])
    assert links["12.1.1"].verdict == "PARTIAL"  # scope
    assert links["8.3.6"].verdict == "PARTIAL"   # password length
    assert links["8.4.2"].verdict == "PASS"
    assert links["7.2.4"].verdict == "PASS"      # 180 <= 183

    gaps = [(l.clause, g.kind, g.attribute) for l in links.values() for g in l.gaps]
    assert gaps == [
        ("12.1.1", "DELTA", "systems_covered"),
        ("8.3.6", "DELTA", "password_min_length"),
    ]


def test_evidence_is_reused_across_both_frameworks_in_one_pass():
    links = evaluate(POLICY, "POLICY", ["ISO-27001", "PCI-DSS"], CONTENT)
    assert len(links) == 7
    assert {l.framework for l in links} == {"ISO-27001", "PCI-DSS"}


def test_remediating_the_gaps_flips_pci_to_pass():
    fixed = POLICY | {
        "password_min_length": 14,
        "systems_covered": ["Corporate IT", "Cardholder Data Environment"],
    }
    links = {l.clause: l for l in evaluate(fixed, "POLICY", ["PCI-DSS"], CONTENT)}
    assert not any(l.gaps for l in links.values())
    # 12.1.1's UCO coverage is PARTIAL, so one policy alone never fully satisfies it.
    assert links["12.1.1"].verdict == "PARTIAL"
    assert links["8.3.6"].verdict == "PASS"


def test_empty_evidence_fails_rather_than_passes():
    links = evaluate({}, "POLICY", ["ISO-27001", "PCI-DSS"], CONTENT)
    assert links and all(l.verdict == "FAIL" for l in links)


def test_unmatched_artefact_type_produces_no_links():
    assert evaluate(POLICY, "SCREENSHOT", ["ISO-27001"], CONTENT) == []


@pytest.mark.parametrize("value", [None, "twelve", ""])
def test_unparseable_extraction_never_silently_passes(value):
    link = {l.clause: l for l in evaluate(
        POLICY | {"password_min_length": value}, "POLICY", ["PCI-DSS"], CONTENT
    )}["8.3.6"]
    assert link.verdict != "PASS"


def test_cadence_words_convert_to_day_counts_deterministically():
    """Extraction reports the literal word ("quarterly"); code — not the model —
    decides that means 90 days."""
    links = {l.clause: l for l in evaluate(
        POLICY | {"access_review_frequency_days": "quarterly"}, "POLICY", ["ISO-27001", "PCI-DSS"], CONTENT
    )}
    assert links["A.5.18"].verdict == "PASS"  # 90 <= 365
    assert links["7.2.4"].verdict == "PASS"   # 90 <= 183

    stale = {l.clause: l for l in evaluate(
        POLICY | {"access_review_frequency_days": "annually"}, "POLICY", ["PCI-DSS"], CONTENT
    )}
    assert stale["7.2.4"].verdict == "PARTIAL"  # 365 > 183


def test_contains_all_matches_real_extracted_phrases_not_just_exact_tokens():
    """A real model returns natural phrases, not the canonical tokens a content-pack
    author typed. "remote access" must satisfy contains_all against a full sentence
    that mentions it, not require an exact list-item match."""
    natural = POLICY | {
        "mfa_required_for": [
            "remote access through the corporate VPN",
            "administrative access to cloud management consoles",
        ],
        "systems_covered": ["Corporate IT", "including the Cardholder Data Environment scope"],
    }
    links = {l.clause: l for l in evaluate(natural, "POLICY", ["PCI-DSS"], CONTENT)}
    assert links["8.4.2"].verdict == "PASS"
    assert links["12.1.1"].verdict == "PARTIAL"  # UCO coverage still PARTIAL by design
    assert not links["12.1.1"].gaps


# A scan that is still within its 90-day validity window at AUDIT_DATE, so these
# tests isolate compliance_status rather than accidentally testing freshness.
AUDIT_DATE = date(2023, 5, 1)
SCAN_REPORT = {
    "scan_completed_date": "2023-03-16",
    "scan_expiry_date": "2023-06-14",
    "asv_company": "Clone Systems, Inc.",
}


@pytest.mark.parametrize("compliant_value", [True, "pass", "Pass", "compliant"])
def test_scan_report_compliance_status_accepts_bool_or_word(compliant_value):
    """The extraction prompt tells the model to type yes/no facts as booleans, but a
    real model sometimes still returns the word it saw ("Pass"). Both must evaluate
    identically — this is a deterministic normalization, not the model deciding."""
    link = {l.clause: l for l in evaluate(
        SCAN_REPORT | {"compliance_status": compliant_value}, "SCAN_REPORT",
        ["PCI-DSS"], CONTENT, as_of=AUDIT_DATE,
    )}["11.3.2"]
    assert link.verdict == "PASS"
    assert not link.gaps


@pytest.mark.parametrize("failing_value", [False, "fail", "Fail", "non-compliant"])
def test_scan_report_compliance_status_failure_is_a_real_gap(failing_value):
    link = {l.clause: l for l in evaluate(
        SCAN_REPORT | {"compliance_status": failing_value}, "SCAN_REPORT",
        ["PCI-DSS"], CONTENT, as_of=AUDIT_DATE,
    )}["11.3.2"]
    assert link.verdict == "PARTIAL"
    assert [g.attribute for g in link.gaps] == ["compliance_status"]
