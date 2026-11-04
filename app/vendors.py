"""Vendor risk rules (ADR-042): a tier and a review status from fixed rules, never from a model.

The tier is points: what data the vendor can touch, how much the business depends on them, and one more if
they handle personal or sensitive data with no attestation (a current SOC 2 or ISO 27001 report) on file.
The tier sets how often the vendor is reviewed. These numbers are our own baseline, stated here and in the
ADR so an organisation can see exactly why a vendor landed where it did.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

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

def review_states(db, org_id: str, now: datetime | None = None) -> list[tuple]:
    """(vendor, review dict) for each active vendor, by the same rules as the Vendors page. Shared by the weekly
    report counts and the daily attention list so the two can never disagree."""
    from app.models import Vendor, VendorReport

    now = now or datetime.now(timezone.utc)
    reports: dict[str, list] = {}
    for r in db.query(VendorReport).filter_by(org_id=org_id):
        reports.setdefault(r.vendor_id, []).append(r)
    out = []
    for v in db.query(Vendor).filter_by(org_id=org_id, status="ACTIVE").order_by(Vendor.name).all():
        attested = v.has_attestation or any(attests(r.report_type, r.valid_until, now.date()) for r in reports.get(v.id, []))
        out.append((v, review(v.status, tier(v.data_access, v.criticality, attested), v.last_reviewed_at, now)))
    return out


ATTESTING_TYPES = ("SOC2_TYPE2", "SOC2_TYPE1", "ISO27001")
REPORT_TYPES = ATTESTING_TYPES + ("OTHER",)


def attests(report_type: str, valid_until: date, today: date | None = None) -> bool:
    """A SOC 2 or ISO 27001 report counts as an attestation only while its stated valid-until date has not
    passed. Any other document is kept on the record and never counts."""
    return report_type in ATTESTING_TYPES and valid_until >= (today or datetime.now(timezone.utc).date())
