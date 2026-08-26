"""Evidence Quality Score: deterministic, weighted, and always explained.

A score with no reasons is a number nobody can act on or challenge, so every
assertion here checks the explanation as well as the figure.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.quality import MAX_SCORE, WEIGHTS, score_evidence

AS_OF = date(2026, 8, 19)
REQUESTED = ["approval_date", "approver_role", "systems_covered", "password_min_length"]

STRONG = {
    "approval_date": "2026-03-12",
    "approver_role": "Chief Information Security Officer",
    "approver_name": "Meera Khanna",
    "signature_present": True,
    "systems_covered": ["Corporate IT", "Cardholder Data Environment"],
    "password_min_length": 14,
    "next_review_date": "2027-03-12",
}
STRONG_SOURCES = {name: [{"page": 1, "quote": "..."}] for name in STRONG}
STRONG_METHODS = {name: "native_text" for name in STRONG}


def strong(**overrides):
    return score_evidence(
        STRONG | overrides.pop("attributes", {}), overrides.pop("requested", REQUESTED),
        sources=overrides.pop("sources", STRONG_SOURCES),
        extraction_methods=overrides.pop("methods", STRONG_METHODS),
        required_scope=overrides.pop("required_scope", ["cardholder data environment"]),
        as_of=overrides.pop("as_of", AS_OF),
    )


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_strong_evidence_scores_near_the_maximum():
    result = strong()
    assert result.score > 4.5
    assert result.score <= MAX_SCORE


def test_scoring_is_deterministic():
    assert strong().score == strong().score


def test_every_dimension_carries_a_reason():
    result = strong()
    assert len(result.dimensions) == len(WEIGHTS)
    assert all(d.reason.strip() for d in result.dimensions)
    assert all(0.0 <= d.score <= 1.0 for d in result.dimensions)


def test_explanation_lists_the_reasons():
    text = strong().explain()
    assert "/ 5.0" in text
    assert "Reason:" in text
    assert text.count("- ") == len(WEIGHTS)


def test_empty_evidence_scores_zero_and_says_why():
    result = score_evidence({}, REQUESTED, as_of=AS_OF)
    assert result.score == 0.0
    joined = " ".join(result.reasons)
    assert "0 of 4" in joined
    assert "no issue or expiry date" in joined


def test_missing_attributes_reduce_completeness_and_name_them():
    partial = {k: v for k, v in STRONG.items() if k != "password_min_length"}
    result = score_evidence(partial, REQUESTED, sources=STRONG_SOURCES,
                            extraction_methods=STRONG_METHODS, as_of=AS_OF)
    completeness = next(d for d in result.dimensions if d.name == "completeness")
    assert completeness.score == 0.75
    assert "password_min_length" in completeness.reason


def test_expired_evidence_scores_zero_freshness():
    result = strong(attributes={"next_review_date": "2025-01-01"})
    freshness = next(d for d in result.dimensions if d.name == "freshness")
    assert freshness.score == 0.0
    assert "expired" in freshness.reason


def test_evidence_near_expiry_is_flagged_before_it_lapses():
    result = strong(attributes={"next_review_date": "2026-09-01"})
    freshness = next(d for d in result.dimensions if d.name == "freshness")
    assert freshness.score == 0.5
    assert "expires in 13 days" in freshness.reason


def test_unsigned_unattributed_document_loses_authenticity():
    anonymous = {k: v for k, v in STRONG.items()
                 if k not in {"approver_role", "approver_name", "signature_present"}}
    result = score_evidence(anonymous, REQUESTED, as_of=AS_OF)
    authenticity = next(d for d in result.dimensions if d.name == "authenticity")
    assert authenticity.score == pytest.approx(0.3)
    assert "no approver identified" in authenticity.reason
    assert "signature not found" in authenticity.reason


def test_scope_gap_is_named_not_just_scored():
    result = strong(attributes={"systems_covered": ["Corporate IT"]})
    scope = next(d for d in result.dimensions if d.name == "scope_coverage")
    assert scope.score == 0.0
    assert "does not include cardholder data environment" in scope.reason


def test_ocr_sourced_values_score_lower_legibility_than_native_text():
    native = strong()
    scanned = strong(methods={name: "vlm" for name in STRONG})

    native_leg = next(d for d in native.dimensions if d.name == "legibility")
    scanned_leg = next(d for d in scanned.dimensions if d.name == "legibility")
    assert native_leg.score == 1.0
    assert scanned_leg.score < native_leg.score
    assert "OCR" in scanned_leg.reason


def test_uncited_values_reduce_corroboration():
    result = strong(sources={})
    corroboration = next(d for d in result.dimensions if d.name == "corroboration")
    assert corroboration.score == 0.0
    assert "0 of" in corroboration.reason


def test_score_is_stored_on_upload(client, bootstrap, upload):
    """The pipeline must persist the score, not merely be able to compute one."""
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]

    detail = client.get(f"/evidence/{evidence_id}",
                        headers={"authorization": f"org:{org_id}"}).json()
    assert detail["quality_score"] is not None
    assert len(detail["quality"]["dimensions"]) == len(WEIGHTS)
    assert all(d["reason"] for d in detail["quality"]["dimensions"])

    status = client.get(f"/evidence/{evidence_id}/status",
                        headers={"authorization": f"org:{org_id}"}).json()
    assert status["quality_score"] == detail["quality_score"]
