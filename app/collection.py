"""Was this connector run complete? (ADR-030)

A run is COMPLETE, PARTIAL or FAILED, and `expectation` says what that judgement rests on:
REPORTED (the collector declared totals, truncation or errors), HISTORY (compared with the last
COMPLETE run) or NONE (nothing to compare with: COMPLETE then means only that nothing indicated
otherwise). Absence of data is never evidence of compliance, so a PARTIAL run's values are
withheld from evaluation rather than read as zero.
"""

from __future__ import annotations

from typing import Any

# Collector-declared fields (all optional): complete, truncated, rate_limited, errors,
# pages_fetched / pages_expected, total_returned / total_expected.
_TOTALS = ("pages_fetched", "pages_expected", "total_returned", "total_expected")


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def summary(attributes: dict) -> dict:
    """What came back, in the shape the next run is compared against."""
    return {"attributes": sorted(attributes),
            "repositories_in_scope": _int(attributes.get("repositories_in_scope")),
            "merges_in_period": _int(attributes.get("merges_in_period"))}


def assess(declared: Any, attributes: dict, baseline: dict | None) -> dict:
    """status, expectation, requested, returned, signals for one run that returned `attributes`."""
    signals: list[str] = []
    declared = declared if isinstance(declared, dict) else None
    requested = {}
    if declared is not None:
        requested = {k: declared[k] for k in _TOTALS if _int(declared.get(k)) is not None}
        if declared.get("complete") is False:
            signals.append("the collector reported the run incomplete")
        if declared.get("truncated"):
            signals.append("the collector reported truncated results")
        if declared.get("rate_limited"):
            signals.append("the collector hit a rate limit")
        signals += [f"collector error: {e}" for e in (declared.get("errors") or []) if isinstance(e, str)]
        fetched, expected = _int(declared.get("pages_fetched")), _int(declared.get("pages_expected"))
        if fetched is not None and expected is not None and fetched < expected:
            signals.append(f"fetched {fetched} of {expected} pages")
        got, want = _int(declared.get("total_returned")), _int(declared.get("total_expected"))
        if got is not None and want is not None and got < want:
            signals.append(f"returned {got} of {want} items the API reported")

    now = summary(attributes)
    if baseline:
        if lost := sorted(set(baseline.get("attributes") or []) - set(now["attributes"])):
            signals.append(f"attributes present in the last complete run are missing: {', '.join(lost)}")
        was, is_ = baseline.get("repositories_in_scope"), now["repositories_in_scope"]
        if was is not None and is_ is not None and is_ < was:
            signals.append(f"repositories in scope fell from {was} to {is_}")
        was, is_ = baseline.get("merges_in_period"), now["merges_in_period"]
        if was and is_ == 0:
            signals.append(f"no merges returned where the last complete run had {was}")

    expectation = "+".join(k for k, on in (("REPORTED", declared is not None), ("HISTORY", bool(baseline))) if on)
    return {"status": "PARTIAL" if signals else "COMPLETE", "expectation": expectation or "NONE",
            "requested": requested, "returned": now, "signals": signals}
