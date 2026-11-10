"""Risk scoring rules (ADR-056): a score, a band and a review state from fixed rules, never from a model.

Score is likelihood times impact, each on a 1 to 5 scale, so 1 to 25. The band comes from the score alone.
A risk is placed on the heat map at its residual position once someone has stated one, else at its inherent
position. These thresholds are our own baseline, stated here and in the ADR so the working is never hidden.
"""

from __future__ import annotations

from datetime import date, timedelta

SCALE = (1, 2, 3, 4, 5)
CATEGORIES = ("SECURITY", "PRIVACY", "COMPLIANCE", "OPERATIONAL", "VENDOR", "AI", "OTHER")
TREATMENTS = ("MITIGATE", "ACCEPT", "TRANSFER", "AVOID")
STATUSES = ("OPEN", "IN_TREATMENT", "CLOSED")

# Highest band first; a score belongs to the first band whose floor it reaches.
BANDS = (("CRITICAL", 17), ("HIGH", 10), ("MEDIUM", 5), ("LOW", 1))
REVIEW_EVERY_DAYS = {"CRITICAL": 30, "HIGH": 90, "MEDIUM": 180, "LOW": 365}
DUE_SOON_DAYS = 14  # shorter than the vendor register's 30: the critical cadence is itself 30 days


def score(likelihood: int, impact: int) -> int:
    return likelihood * impact


def band(points: int) -> str:
    return next(name for name, floor in BANDS if points >= floor)


def position(risk) -> tuple[int, int]:
    """Where the risk sits now: residual if both halves are stated, otherwise inherent."""
    if risk.residual_likelihood is not None and risk.residual_impact is not None:
        return risk.residual_likelihood, risk.residual_impact
    return risk.inherent_likelihood, risk.inherent_impact


def rating(likelihood: int, impact: int) -> dict:
    points = score(likelihood, impact)
    return {"likelihood": likelihood, "impact": impact, "score": points, "band": band(points)}


def review_state(status: str, next_review_date: date | None, today: date) -> str:
    """CLOSED needs no review. A risk with no date cannot be created or edited into that state, so a missing
    date only appears on rows written outside the API, and is treated as overdue rather than invisible."""
    if status == "CLOSED":
        return "CLOSED"
    if next_review_date is None or next_review_date < today:
        return "OVERDUE"
    return "DUE_SOON" if next_review_date <= today + timedelta(days=DUE_SOON_DAYS) else "CURRENT"


def default_next_review(current_band: str, today: date) -> date:
    return today + timedelta(days=REVIEW_EVERY_DAYS[current_band])


def heatmap(risks, current: bool) -> list[dict]:
    """All 25 cells, each with its score, band and how many open risks sit there. `current` places a risk at
    its residual position where it has one; otherwise every risk is placed at its inherent position."""
    counts: dict[tuple[int, int], int] = {}
    for r in risks:
        if r.status == "CLOSED":
            continue
        cell = position(r) if current else (r.inherent_likelihood, r.inherent_impact)
        counts[cell] = counts.get(cell, 0) + 1
    return [{**rating(lk, im), "count": counts.get((lk, im), 0)} for lk in reversed(SCALE) for im in SCALE]


def overdue_count(risks, today: date) -> int:
    return sum(review_state(r.status, r.next_review_date, today) == "OVERDUE" for r in risks)
