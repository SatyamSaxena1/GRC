"""Vendor reports (ADR-043): a current SOC 2 / ISO 27001 report is the attestation; an expired or other
document is kept but never counts. Files are validated, immutable, tenant-scoped and download-only."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from app import vendors
from app.models import AuditEvent

H = lambda org: {"authorization": f"org:{org}"}  # noqa: E731
FUTURE = (date.today() + timedelta(days=200)).isoformat()
PAST = (date.today() - timedelta(days=1)).isoformat()


def _vendor(client, org):
    # personal data + high dependence: 2 + 2 + 1 (no attestation) = 5 points, HIGH
    return client.post("/vendors", json={"name": "Acme Hosting", "data_access": "PERSONAL", "criticality": "HIGH"},
                       headers=H(org)).json()


def _attach(client, org, vendor_id, content=b"SOC 2 Type II report for the period ending 2026", name="soc2.txt",
            report_type="SOC2_TYPE2", valid_until=FUTURE):
    return client.post(f"/vendors/{vendor_id}/reports", headers=H(org),
                       data={"report_type": report_type, "valid_until": valid_until},
                       files={"file": (name, content, "text/plain")})


@pytest.mark.parametrize("kind,until,counts", [
    ("SOC2_TYPE2", date(2026, 12, 31), True), ("SOC2_TYPE1", date(2026, 12, 31), True),
    ("ISO27001", date(2026, 12, 31), True), ("OTHER", date(2026, 12, 31), False),
    ("SOC2_TYPE2", date(2026, 11, 2), False),
])
def test_only_a_current_soc2_or_iso_report_attests(kind, until, counts):
    assert vendors.attests(kind, until, today=date(2026, 11, 3)) is counts


def test_a_current_report_lowers_the_tier_and_is_the_source(client, bootstrap):
    org, _ = bootstrap(client)
    v = _vendor(client, org)
    assert v["tier"] == "HIGH" and v["points"] == 5 and v["attestation"]["source"] == "none"
    out = _attach(client, org, v["id"]).json()
    assert out["attestation"] == {"on_file": True, "source": "report", "valid_until": FUTURE}
    assert out["points"] == 4 and out["tier"] == "MEDIUM"
    assert out["reports"][0]["counts"] is True and out["reports"][0]["filename"] == "soc2.txt"


def test_an_expired_report_and_another_document_do_not_count(client, bootstrap):
    org, _ = bootstrap(client)
    v = _vendor(client, org)
    expired = _attach(client, org, v["id"], content=b"an old report from last year", valid_until=PAST).json()
    assert expired["tier"] == "HIGH" and expired["attestation"]["source"] == "none"
    assert expired["reports"][0]["counts"] is False
    other = _attach(client, org, v["id"], content=b"their marketing security whitepaper", report_type="OTHER").json()
    assert other["tier"] == "HIGH" and len(other["reports"]) == 2


def test_the_manual_tick_still_works_but_a_report_takes_precedence(client, bootstrap):
    org, _ = bootstrap(client)
    v = _vendor(client, org)
    ticked = client.patch(f"/vendors/{v['id']}", json={"has_attestation": True}, headers=H(org)).json()
    assert ticked["attestation"]["source"] == "manual"
    assert _attach(client, org, v["id"]).json()["attestation"]["source"] == "report"


def test_the_upload_is_validated_and_duplicates_refused(client, bootstrap):
    org, _ = bootstrap(client)
    v = _vendor(client, org)
    assert _attach(client, org, v["id"], name="malware.exe").status_code == 400
    assert _attach(client, org, v["id"], content=b"").status_code == 400
    assert _attach(client, org, v["id"], report_type="SOC3").status_code == 422
    assert _attach(client, org, v["id"], valid_until="next spring").status_code == 422
    assert _attach(client, org, v["id"]).status_code == 200
    assert _attach(client, org, v["id"]).status_code == 409  # the same bytes again


def test_the_file_downloads_as_an_attachment_only(client, bootstrap):
    org, _ = bootstrap(client)
    v = _vendor(client, org)
    report = _attach(client, org, v["id"], content=b"<script>alert(1)</script> SOC 2 text", name="report.txt").json()["reports"][0]
    got = client.get(f"/vendors/{v['id']}/reports/{report['id']}/file", headers=H(org))
    assert got.status_code == 200 and got.content == b"<script>alert(1)</script> SOC 2 text"
    assert got.headers["content-disposition"].startswith("attachment") and got.headers["x-content-type-options"] == "nosniff"
    assert got.headers["content-type"] == "application/octet-stream"


def test_roles_and_tenancy(client, bootstrap):
    org, _ = bootstrap(client)
    other = client.post("/admin/organizations", json={"name": "Other", "frameworks": ["SOC-2"]}).json()["id"]
    v = _vendor(client, org)
    report = _attach(client, org, v["id"]).json()["reports"][0]
    viewer = {"authorization": "user:" + client.post("/admin/users", json={
        "email": "v@a.test", "org_id": org, "role": "COMPLIANCE_VIEWER"}).json()["id"]}

    assert client.get(f"/vendors/{v['id']}/reports/{report['id']}/file", headers=viewer).status_code == 200
    assert client.post(f"/vendors/{v['id']}/reports", headers=viewer, data={"report_type": "OTHER", "valid_until": FUTURE},
                       files={"file": ("x.txt", b"hello there", "text/plain")}).status_code == 403
    assert client.get(f"/vendors/{v['id']}/reports/{report['id']}/file", headers=H(other)).status_code in (403, 404)
    assert _attach(client, other, v["id"], content=b"someone elses vendor").status_code == 404
    assert client.get(f"/vendors/{v['id']}/reports/{report['id']}/file", headers=H(org)).status_code == 200
    assert client.get(f"/vendors/NOPE/reports/{report['id']}/file", headers=H(org)).status_code == 404


def test_attaching_is_audited_with_the_hash_and_never_the_content(client, bootstrap, db):
    org, _ = bootstrap(client)
    v = _vendor(client, org)
    _attach(client, org, v["id"], content=b"very confidential audit findings")
    event = db.query(AuditEvent).filter_by(action="VENDOR_REPORT_ATTACHED", entity=v["id"]).one()
    assert event.detail["report_type"] == "SOC2_TYPE2" and event.detail["counts"] is True and len(event.detail["sha256"]) == 64
    assert "confidential" not in json.dumps(event.detail)


def test_the_list_carries_each_vendors_reports(client, bootstrap):
    org, _ = bootstrap(client)
    v = _vendor(client, org)
    _attach(client, org, v["id"])
    listed = client.get("/vendors", headers=H(org)).json()
    assert listed[0]["attestation"]["source"] == "report" and len(listed[0]["reports"]) == 1
