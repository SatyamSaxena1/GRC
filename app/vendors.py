"""Vendor risk rules (ADR-042): a tier and a review status from fixed rules, never from a model.

The tier is points: what data the vendor can touch, how much the business depends on them, and one more if
they handle personal or sensitive data with no attestation (a current SOC 2 or ISO 27001 report) on file.
The tier sets how often the vendor is reviewed. These numbers are our own baseline, stated here and in the
ADR so an organisation can see exactly why a vendor landed where it did.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

DATA_ACCESS = {"NONE": 0, "INTERNAL": 1, "PERSONAL": 2, "SENSITIVE": 3}
CRITICALITY = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
REVIEW_EVERY_DAYS = {"HIGH": 90, "MEDIUM": 180, "LOW": 365}
DUE_SOON_DAYS = 30


def points(data_access: str, criticality: str, has_attestation: bool) -> int:
    missing = 1 if (DATA_ACCESS[data_access] >= 2 and not has_attestation) else 0
    return DATA_ACCESS[data_access] + CRITICALITY[criticality] + missing


def tier(data_access: str, criticality: str, has_attestation: bool) -> str:
    p = points(data_access, criticality, has_attestation)
    return "HIGH" if p >= 5 else "MEDIUM" if p >= 3 else "LOW"


def review(status: str, risk_tier: str, last_reviewed_at: datetime | None, now: datetime | None = None) -> dict:
    """Where this vendor's review stands. An offboarded vendor needs none."""
    if status == "OFFBOARDED":
        return {"state": "OFFBOARDED", "due": None}
    if last_reviewed_at is None:
        return {"state": "NEVER_REVIEWED", "due": None}
    now = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    due = last_reviewed_at + timedelta(days=REVIEW_EVERY_DAYS[risk_tier])
    state = "OVERDUE" if due < now else "DUE_SOON" if due < now + timedelta(days=DUE_SOON_DAYS) else "CURRENT"
    return {"state": state, "due": due.date().isoformat()}
