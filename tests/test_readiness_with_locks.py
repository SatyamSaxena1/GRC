"""Readiness and the controls rollup must agree once an auditor has locked a verdict."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import db as db_module
from app.models import EvidenceControlLink

REASON = "reviewed the signed policy and the review log; accepting it with a compensating control"


def _lock_one(client, org_id, engagement_id, evidence_id, framework):
    with Session(db_module.engine) as s:
        link = s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id, framework=framework).first()
        link_id, clause = link.id, link.clause
    resp = client.post(f"/audit/links/{link_id}/lock", headers={"authorization": f"auditor:{engagement_id}"},
                       json={"verdict": "COMPLIANT", "reason": REASON})
    assert resp.status_code == 200
    return clause


def test_a_locked_override_counts_in_readiness_as_it_does_in_the_controls_rollup(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)  # the default stub finds no facts, so every verdict is FAIL
    evidence_id = upload(client, org_id).json()["evidence_id"]
    org = {"authorization": f"org:{org_id}"}
    before = client.get("/analytics/readiness/PCI-DSS", headers=org).json()
    assert before["satisfied"] == 0

    clause = _lock_one(client, org_id, engagement_id, evidence_id, "PCI-DSS")

    after = client.get("/analytics/readiness/PCI-DSS", headers=org).json()
    assert after["satisfied"] == 1
    assert next(c for c in after["clauses"] if c["clause"] == clause)["verdict"] == "PASS"
    assert after["readiness"] > before["readiness"]
    # the other framework is untouched, and the dashboard rollup agrees on the one PASS
    assert client.get("/analytics/readiness/ISO-27001", headers=org).json()["satisfied"] == 0
    assert client.get("/analytics/dashboard", headers=org).json()["controls"]["by_verdict"]["PASS"] == 1


def test_an_auditor_verdict_of_non_compliant_is_not_counted_as_ready(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    with Session(db_module.engine) as s:
        link_id = s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id, framework="PCI-DSS").first().id
    # NON_COMPLIANT is not a closing verdict, so nothing locks and readiness is unchanged
    client.post(f"/audit/links/{link_id}/verdict", headers={"authorization": f"auditor:{engagement_id}"},
                json={"verdict": "NON_COMPLIANT"})
    assert client.get("/analytics/readiness/PCI-DSS", headers={"authorization": f"org:{org_id}"}).json()["satisfied"] == 0
