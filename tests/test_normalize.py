"""Normalization is where 'the document said it differently' stops mattering.

Every case here is a representation a real model actually produced or a real
document actually used — not hypotheticals.
"""

from __future__ import annotations

from datetime import date

import pytest

from app import normalize
from app.content.load import DeltaCondition
from app.evaluate import check


@pytest.mark.parametrize("raw,expected", [
    ("2026-03-12", date(2026, 3, 12)),
    ("12 March 2026", date(2026, 3, 12)),
    ("12 Mar 2026", date(2026, 3, 12)),
    ("March 12 2026", date(2026, 3, 12)),
    ("12/03/2026", date(2026, 3, 12)),
    ("12.03.2026", date(2026, 3, 12)),
    ("1st January 2026", date(2026, 1, 1)),
    (date(2026, 3, 12), date(2026, 3, 12)),
    ("not a date", None),
    (None, None),
    (8, None),
])
def test_date_parsing_covers_real_document_formats(raw, expected):
    assert normalize.to_date(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("quarterly", 90.0), ("Quarterly", 90.0), ("annually", 365.0), ("annual", 365.0),
    ("every six months", 182.0), ("monthly", 30.0), ("90", 90.0), ("90 days", 90.0),
    (180, 180.0),
])
def test_cadence_words_become_day_counts(raw, expected):
    assert normalize.to_days(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Pass", True), ("pass", True), ("COMPLIANT", True), ("yes", True), (True, True),
    ("Fail", False), ("non-compliant", False), ("no", False), (False, False),
])
def test_boolean_words_become_booleans(raw, expected):
    assert normalize.to_bool(raw) is expected


def test_unknown_words_are_left_alone_not_coerced():
    """Anything not in the mapping must survive unchanged, so an unrecognized
    value fails a condition rather than silently becoming something else."""
    assert normalize.to_bool("maybe") == "maybe"
    assert normalize.to_days("when someone remembers") == "when someone remembers"


@pytest.mark.parametrize("a,b", [
    ("12 March 2026", "2026-03-12"),
    ("Pass", True),
    ("quarterly", 90),
    ("  CISO  ", "ciso"),
])
def test_equivalent_representations_compare_equal(a, b):
    assert normalize.equivalent(a, b)
    assert normalize.equivalent(b, a)


@pytest.mark.parametrize("a,b", [
    ("12 March 2026", "2026-03-13"),
    ("Pass", False),
    ("quarterly", 365),
    ("CISO", "CTO"),
])
def test_genuinely_different_values_do_not_compare_equal(a, b):
    assert not normalize.equivalent(a, b)


# ------------------------------------------------------------------ date deltas


def test_evidence_dated_before_the_audit_period_fails():
    """effective_date >= audit_period_start, the freshness rule the spec calls for."""
    condition = DeltaCondition(attribute="effective_date", operator=">=", value="2026-01-01")
    assert check(condition, "12 March 2026") is True
    assert check(condition, "2026-06-30") is True
    assert check(condition, "12 March 2025") is False


def test_expired_scan_is_detected_by_date_comparison():
    condition = DeltaCondition(attribute="scan_expiry_date", operator=">=", value="2026-08-01")
    assert check(condition, "Wed Jun 14 2023") is False  # long expired
    assert check(condition, "2026-09-01") is True


def test_uninterpretable_value_fails_the_condition_rather_than_passing():
    condition = DeltaCondition(attribute="password_min_length", operator=">=", value=12)
    for value in (None, "", "twelve-ish", [], {}):
        assert check(condition, value) is False
