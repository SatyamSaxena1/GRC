"""Vendor risk (ADR-042): fixed rules decide the tier and review status; the register is audited and tenant-scoped."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import vendors
from app.models import AuditEvent

H = lambda org: {"authorization": f"org:{org}"}  # noqa: E731
NOW = datetime(2026, 11, 3, tzinfo=timezone.utc)


@pytest.mark.parametrize("data,crit,attested,points,tier", [
    ("NONE", "LOW", False, 0, "LOW"),
    ("INTERNAL", "MEDIUM", False, 2, "LOW"),
    ("INTERNAL", "HIGH", True, 3, "MEDIUM"),
    ("PERSONAL", "LOW", True, 2, "LOW"),
    ("PERSONAL", "LOW", False, 3, "MEDIUM"),        # personal data with no attestation costs a point
    ("PERSONAL", "MEDIUM", False, 4, "MEDIUM"),
    ("PERSONAL", "HIGH", False, 5, "HIGH"),
    ("SENSITIVE", "MEDIUM", True, 4, "MEDIUM"),
    ("SENSITIVE", "MEDIUM", False, 5, "HIGH"),
    ("SENSITIVE", "HIGH", True, 5, "HIGH"),
])
def test_the_tier_is_points_and_nothing_else(data, crit, attested, points, tier):
    assert vendors.points(data, crit, attested) == points
    assert vendors.tier(data, crit, attested) == tier


def test_review_status_follows_the_tier_cadence():
    day = lambda n: (NOW - timedelta(days=n)).replace(tzinfo=None)  # noqa: E731
    assert vendors.review("ACTIVE", "HIGH", None, NOW)["state"] == "NEVER_REVIEWED"
    assert vendors.review("OFFBOARDED", "HIGH", None, NOW)["state"] == "OFFBOARDED"
    assert vendors.review("ACTIVE", "HIGH", day(10), NOW)["state"] == "CURRENT"
    assert vendors.review("ACTIVE", "HIGH", day(70), NOW)["state"] == "DUE_SOON"   # due in 20 days
    assert vendors.review("ACTIVE", "HIGH", day(91), NOW)["state"] == "OVERDUE"    # 90-day cadence
    assert vendors.review("ACTIVE", "LOW", day(91), NOW)["state"] == "CURRENT"     # 365-day cadence
    assert vendors.review("ACTIVE", "MEDIUM", day(181), NOW)["state"] == "OVERDUE"


def _add(client, org, **kw):
    body = {"name": "Stripe", "service": "Payments", "data_access": "SENSITIVE", "criticality": "HIGH", **kw}
    return client.post("/vendors", json=body, headers=H(org))


def test_adding_a_vendor_derives_its_tier_and_is_audited(client, bootstrap, db):
    org, _ = bootstrap(client)
    v = _add(client, org).json()
    assert v["tier"] == "HIGH" and v["points"] == 6 and v["review_every_days"] == 90
    assert v["review"]["state"] == "NEVER_REVIEWED"
    event = db.query(AuditEvent).filter_by(action="VENDOR_ADDED", entity=v["id"]).one()
    assert event.after["data_access"] == "SENSITIVE"


def test_an_attestation_lowers_the_tier_and_the_change_is_audited_with_before_and_after(client, bootstrap, db):
    org, _ = bootstrap(client)
    v = _add(client, org, data_access="PERSONAL", criticality="HIGH").json()
    assert v["tier"] == "HIGH"
    patched = client.patch(f"/vendors/{v['id']}", json={"has_attestation": True}, headers=H(org)).json()
    assert patched["tier"] == "MEDIUM"
    event = db.query(AuditEvent).filter_by(action="VENDOR_UPDATED", entity=v["id"]).one()
    assert event.before["has_attestation"] is False and event.after["has_attestation"] is True
    client.patch(f"/vendors/{v['id']}", json={"has_attestation": True}, headers=H(org))  # no change
    assert db.query(AuditEvent).filter_by(action="VENDOR_UPDATED", entity=v["id"]).count() == 1


def test_a_review_needs_a_real_note_and_sets_the_date(client, bootstrap, db):
    org, _ = bootstrap(client)
    v = _add(client, org).json()
    assert client.post(f"/vendors/{v['id']}/review", json={"note": "ok"}, headers=H(org)).status_code == 422
    reviewed = client.post(f"/vendors/{v['id']}/review", json={"note": "Read their SOC 2 report and noted two exceptions"},
                           headers=H(org)).json()
    assert reviewed["review"]["state"] == "CURRENT" and reviewed["last_reviewed_at"]
    event = db.query(AuditEvent).filter_by(action="VENDOR_REVIEWED", entity=v["id"]).one()
    assert "SOC 2" in event.reason


def test_offboarding_is_its_own_audited_event_and_ends_reviews(client, bootstrap, db):
    org, _ = bootstrap(client)
    v = _add(client, org).json()
    off = client.patch(f"/vendors/{v['id']}", json={"status": "OFFBOARDED"}, headers=H(org)).json()
    assert off["review"]["state"] == "OFFBOARDED"
    assert db.query(AuditEvent).filter_by(action="VENDOR_OFFBOARDED", entity=v["id"]).count() == 1
    assert client.post(f"/vendors/{v['id']}/review", json={"note": "checked everything again"}, headers=H(org)).status_code == 409


def test_roles_and_tenancy(client, bootstrap):
    org, _ = bootstrap(client)
    other = client.post("/admin/organizations", json={"name": "Other", "frameworks": ["SOC-2"]}).json()["id"]
    v = _add(client, org).json()
    mk = lambda o, email, role: {"authorization": "user:" + client.post("/admin/users", json={  # noqa: E731
        "email": email, "org_id": o, "role": role}).json()["id"]}
    viewer, owner = mk(org, "v@a.test", "COMPLIANCE_VIEWER"), mk(org, "o@a.test", "CONTROL_OWNER")

    assert [x["name"] for x in client.get("/vendors", headers=viewer).json()] == ["Stripe"]
    assert client.post("/vendors", json={"name": "Nope"}, headers=viewer).status_code == 403
    assert client.get("/vendors", headers=owner).status_code == 403
    assert client.get("/vendors", headers=H(other)).json() == []
    assert client.patch(f"/vendors/{v['id']}", json={"status": "OFFBOARDED"}, headers=H(other)).status_code == 404


def test_an_owner_must_belong_to_the_organisation(client, bootstrap):
    org, _ = bootstrap(client)
    other = client.post("/admin/organizations", json={"name": "Other", "frameworks": ["SOC-2"]}).json()["id"]
    stranger = client.post("/admin/users", json={"email": "s@o.test", "org_id": other, "role": "CONTROL_OWNER"}).json()["id"]
    mine = client.post("/admin/users", json={"email": "m@a.test", "org_id": org, "role": "CONTROL_OWNER"}).json()["id"]
    assert _add(client, org, owner_user_id=stranger).status_code == 422
    ok = _add(client, org, owner_user_id=mine).json()
    assert ok["owner_email"] == "m@a.test"
