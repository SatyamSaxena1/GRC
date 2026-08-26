"""Reuse rate and Day-1 framework readiness.

These are the numbers the concept note calls the strongest demonstration of the
product, so they have to be right rather than flattering: a reuse rate that
counts an artefact's first link as "reuse" would inflate every figure.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app import analytics, db as db_module, service
from app.ai.schemas import ExtractedField, ExtractionRun
from app.content.load import load

CONTENT = load()

COMPLIANT_POLICY = {
    "approval_date": "2026-03-12", "approver_role": "Chief Information Security Officer",
    "effective_date": "2026-03-12", "next_review_date": "2027-03-12",
    "systems_covered": ["Corporate IT", "Cardholder Data Environment"],
    "password_min_length": 14,
    "mfa_required_for": ["remote access", "administrative access"],
    "access_review_frequency_days": 90,
}


@pytest.fixture()
def stub_extraction(monkeypatch):
    """Scripted extraction so the analytics maths is tested, not the model."""
    def _install(values: dict):
        def fake_read_document(filename, content, gateway=None):
            return "stubbed", "native_text"

        def fake_extract(text, names, method="native_text", gateway=None):
            return ExtractionRun(
                fields={n: ExtractedField(value=values.get(n), confidence=0.9,
                                          extraction_method=method) for n in names},
                model="stub", provider="stub", prompt_template_version="stub:v1",
            )
        monkeypatch.setattr(service, "read_document", fake_read_document)
        monkeypatch.setattr(service, "extract_attributes", fake_extract)
    return _install


def session():
    return Session(db_module.engine)


# ------------------------------------------------------------------ reuse rate


def test_reuse_rate_is_zero_with_no_evidence(client, bootstrap):
    org_id, _ = bootstrap(client)
    stats = client.get("/analytics/reuse", headers={"authorization": f"org:{org_id}"}).json()
    assert stats["total_links"] == 0
    assert stats["reuse_rate"] == 0.0
    assert stats["effort_hours_saved"] == 0.0


def test_one_upload_satisfying_many_requirements_is_counted_as_reuse(
    client, bootstrap, upload, stub_extraction
):
    """The product claim, as a number: one artefact, seven links, six avoided uploads."""
    stub_extraction(COMPLIANT_POLICY)
    org_id, _ = bootstrap(client)
    upload(client, org_id, content=b"policy")

    stats = client.get("/analytics/reuse", headers={"authorization": f"org:{org_id}"}).json()
    assert stats["distinct_evidence"] == 1
    assert stats["total_links"] == 7           # 3 ISO + 4 PCI
    assert stats["reused_links"] == 6          # first link is the upload itself
    assert stats["reuse_rate"] == pytest.approx(6 / 7, abs=1e-3)
    assert stats["avoided_uploads"] == 6


def test_effort_saved_scales_with_the_configured_rate(client, bootstrap, upload, stub_extraction):
    stub_extraction(COMPLIANT_POLICY)
    org_id, _ = bootstrap(client)
    upload(client, org_id, content=b"policy")
    headers = {"authorization": f"org:{org_id}"}

    default = client.get("/analytics/reuse", headers=headers).json()
    doubled = client.get("/analytics/reuse?effort_hours=3.0", headers=headers).json()
    assert default["effort_hours_saved"] == pytest.approx(6 * 1.5)
    assert doubled["effort_hours_saved"] == pytest.approx(6 * 3.0)


def test_superseded_versions_do_not_inflate_reuse(client, bootstrap, upload, stub_extraction):
    """A redone document is work repeated, not work saved."""
    stub_extraction(COMPLIANT_POLICY)
    org_id, _ = bootstrap(client)
    v1 = upload(client, org_id, content=b"policy").json()["evidence_id"]
    headers = {"authorization": f"org:{org_id}"}

    before = client.get("/analytics/reuse", headers=headers).json()
    client.post(f"/evidence/{v1}/versions", headers=headers,
                files={"file": ("v2.txt", b"revised policy", "text/plain")})
    after = client.get("/analytics/reuse", headers=headers).json()

    assert after["distinct_evidence"] == before["distinct_evidence"] == 1
    assert after["total_links"] == before["total_links"]


def test_two_unrelated_artefacts_each_carry_their_own_upload_cost(
    client, bootstrap, upload, stub_extraction
):
    stub_extraction(COMPLIANT_POLICY)
    org_id, _ = bootstrap(client)
    upload(client, org_id, content=b"policy one")
    upload(client, org_id, content=b"policy two")

    stats = client.get("/analytics/reuse", headers={"authorization": f"org:{org_id}"}).json()
    assert stats["distinct_evidence"] == 2
    assert stats["reused_links"] == stats["total_links"] - 2


# ------------------------------------------------------- day-1 framework readiness


def test_day_one_readiness_for_an_unsubscribed_framework(client, bootstrap, upload, stub_extraction):
    """The thesis in one call: an ISO-only organisation is told how much PCI it
    already meets, before subscribing to PCI."""
    stub_extraction(COMPLIANT_POLICY)
    org_id, _ = bootstrap(client, frameworks=["ISO-27001"])
    upload(client, org_id, content=b"policy")

    result = client.get("/analytics/readiness/PCI-DSS",
                        headers={"authorization": f"org:{org_id}"}).json()

    assert result["already_subscribed"] is False
    assert result["total_requirements"] == 5
    assert result["satisfied"] >= 3          # policy clauses already met
    assert 0.0 < result["readiness"] <= 1.0
    assert {c["clause"] for c in result["clauses"]} == {"12.1.1", "8.3.6", "8.4.2", "7.2.4", "11.3.2"}


def test_readiness_names_what_is_not_covered(client, bootstrap, upload, stub_extraction):
    """A readiness figure without the clause list is a number nobody can act on."""
    stub_extraction(COMPLIANT_POLICY)
    org_id, _ = bootstrap(client, frameworks=["ISO-27001"])
    upload(client, org_id, content=b"policy")

    result = client.get("/analytics/readiness/PCI-DSS",
                        headers={"authorization": f"org:{org_id}"}).json()
    by_clause = {c["clause"]: c["verdict"] for c in result["clauses"]}

    # A policy says nothing about whether an ASV scan was run.
    assert by_clause["11.3.2"] == "NO_EVIDENCE"
    # ...but it does answer the password requirement.
    assert by_clause["8.3.6"] == "PASS"


def test_readiness_is_zero_without_evidence(client, bootstrap):
    org_id, _ = bootstrap(client, frameworks=["ISO-27001"])
    result = client.get("/analytics/readiness/PCI-DSS",
                        headers={"authorization": f"org:{org_id}"}).json()
    assert result["readiness"] == 0.0
    assert result["evaluated"] == 0


def test_best_verdict_per_clause_wins_across_artefacts(client, bootstrap, upload, stub_extraction):
    """Different artefacts cover different clauses; a weak one must not pull down
    a clause another artefact already satisfies."""
    org_id, _ = bootstrap(client, frameworks=["ISO-27001"])

    stub_extraction(COMPLIANT_POLICY | {"password_min_length": 4})
    upload(client, org_id, content=b"weak policy")
    stub_extraction(COMPLIANT_POLICY)
    upload(client, org_id, content=b"strong policy")

    result = client.get("/analytics/readiness/PCI-DSS",
                        headers={"authorization": f"org:{org_id}"}).json()
    by_clause = {c["clause"]: c["verdict"] for c in result["clauses"]}
    assert by_clause["8.3.6"] == "PASS"  # the strong policy carries it


def test_readiness_across_all_known_frameworks(client, bootstrap, upload, stub_extraction):
    stub_extraction(COMPLIANT_POLICY)
    org_id, _ = bootstrap(client, frameworks=["ISO-27001"])
    upload(client, org_id, content=b"policy")

    results = client.get("/analytics/readiness",
                         headers={"authorization": f"org:{org_id}"}).json()
    frameworks = {r["framework"]: r for r in results}
    assert frameworks["ISO-27001"]["already_subscribed"] is True
    assert frameworks["PCI-DSS"]["already_subscribed"] is False


def test_unknown_framework_is_404(client, bootstrap):
    org_id, _ = bootstrap(client)
    assert client.get("/analytics/readiness/NOT-A-FRAMEWORK",
                      headers={"authorization": f"org:{org_id}"}).status_code == 404


def test_analytics_are_tenant_scoped(client, bootstrap, upload, stub_extraction):
    stub_extraction(COMPLIANT_POLICY)
    org_id, _ = bootstrap(client)
    upload(client, org_id, content=b"policy")
    other = client.post("/admin/organizations",
                        json={"name": "Other", "frameworks": ["PCI-DSS"]}).json()["id"]

    mine = client.get("/analytics/reuse", headers={"authorization": f"org:{org_id}"}).json()
    theirs = client.get("/analytics/reuse", headers={"authorization": f"org:{other}"}).json()
    assert mine["total_links"] > 0
    assert theirs["total_links"] == 0
