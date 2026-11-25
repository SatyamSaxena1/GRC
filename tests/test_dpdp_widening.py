"""Phase 1 of docs/product/dpdp-widening-plan.md: the widened DPDP pack and duty-level not applicable."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.content.load import Requirement, load
from app.models import AuditEvent

UNTIL = (datetime.now(timezone.utc).date() + timedelta(days=300)).isoformat()
SAYS = "Our DPO reviews this every quarter and the minutes are kept in the policy library."
WHY = "We never process data of anyone under eighteen."
ORIGINAL = ["Act s.5-6 / Rule 3", "Rule 6 - AWS baseline", "Rule 6 - M365 baseline", "Rule 6 - Google Workspace baseline",
            "Rule 6 - HRMS baseline", "Rule 6(1)(e)", "Rule 7", "Act s.8(7-8) / Rule 8", "Act s.11-13 / Rules 9 & 14"]


def _pack():
    return load().framework("DPDP").requirements


def _org(client):
    org = client.post("/admin/organizations", json={"name": "Acme", "frameworks": ["DPDP"]}).json()["id"]
    return org


def _user(client, org, email, role):
    return client.post("/admin/users", json={"email": email, "org_id": org, "role": role}).json()["id"]


def _as(user_id):
    return {"authorization": f"user:{user_id}"}


def _ready(client, who):
    return client.get("/analytics/readiness/DPDP", headers=_as(who)).json()


def _na(client, who, clause="Act s.9(3)", reason=WHY):
    return client.post("/duty-na", headers=_as(who), json={"clause": clause, "reason": reason})


def test_pack_keeps_the_original_nine_untouched_and_adds_the_duties():
    reqs = _pack()
    assert [r.clause for r in reqs[:9]] == ORIGINAL
    assert not any(r.attestation_only or r.guidance_only for r in reqs[:9])
    assert len(reqs) == 72 and len({r.clause for r in reqs}) == 72
    new = reqs[9:]
    assert all(r.attestation_only and not r.mappings for r in new)      # ADR-060: no rule, no mapping
    assert sum(r.guidance_only for r in new) == 6


def test_guidance_only_needs_a_clause_with_no_rule():
    rule = next(r for r in _pack() if not r.attestation_only)
    with pytest.raises(ValidationError):
        Requirement(**{**rule.model_dump(), "guidance_only": True})


def test_attestation_only_reads_attested_never_pass_and_guidance_never_scores(client):
    org = _org(client)
    admin = _user(client, org, "admin@acme.test", "ORG_ADMIN")
    before = _ready(client, admin)
    guidance = [c for c in before["clauses"] if c.get("guidance_only")]
    assert len(guidance) == 6 and {c["verdict"] for c in guidance} == {"GUIDANCE"}
    assert before["total_requirements"] == 66   # 72 clauses less 6 guidance-only
    assert all(c["verdict"] != "PASS" for c in before["clauses"])

    ok = client.post("/attestations", headers=_as(admin), json={
        "framework": "DPDP", "clause": "Act s.9(3)", "statement": SAYS, "valid_until": UNTIL})
    assert ok.status_code == 201, ok.text
    after = _ready(client, admin)
    assert next(c for c in after["clauses"] if c["clause"] == "Act s.9(3)")["verdict"] == "ATTESTED"
    assert after["attested"] == 1 and after["satisfied"] == before["satisfied"]

    refused = client.post("/attestations", headers=_as(admin), json={
        "framework": "DPDP", "clause": guidance[0]["clause"], "statement": SAYS, "valid_until": UNTIL})
    assert refused.status_code == 409          # guidance is never attested, so never scored
    assert _ready(client, admin)["readiness"] == after["readiness"]


def test_duty_not_applicable_needs_a_reason_leaves_the_score_and_is_audited_and_reversible(client, db):
    org = _org(client)
    admin = _user(client, org, "admin@acme.test", "ORG_ADMIN")
    before = _ready(client, admin)

    for reason in ("", "not relevant", "it does not apply here"):    # none, two words, five words
        assert _na(client, admin, reason=reason).status_code == 422
    assert _ready(client, admin)["total_requirements"] == before["total_requirements"]

    row = _na(client, admin)
    assert row.status_code == 201, row.text
    assert _na(client, admin).status_code == 409                       # already marked
    after = _ready(client, admin)
    assert after["total_requirements"] == before["total_requirements"] - 1
    clause = next(c for c in after["clauses"] if c["clause"] == "Act s.9(3)")
    assert clause["verdict"] == "NOT_APPLICABLE" and clause["na_reason"] == WHY and clause["na_by"] == "admin@acme.test"
    event = db.query(AuditEvent).filter_by(action="DUTY_MARKED_NA").one()
    assert event.org_id == org

    assert client.post(f"/duty-na/{row.json()['id']}/reverse", headers=_as(admin)).status_code == 200
    assert client.post(f"/duty-na/{row.json()['id']}/reverse", headers=_as(admin)).status_code == 409
    back = _ready(client, admin)
    assert back["total_requirements"] == before["total_requirements"]
    assert next(c for c in back["clauses"] if c["clause"] == "Act s.9(3)")["verdict"] == "NO_EVIDENCE"
    assert db.query(AuditEvent).filter_by(action="DUTY_NA_REVERSED").count() == 1
    assert [r["current"] for r in client.get("/duty-na", headers=_as(admin)).json()] == [False]


def test_duty_not_applicable_is_admin_only_dpdp_only_and_never_for_guidance(client):
    org = _org(client)
    admin = _user(client, org, "admin@acme.test", "ORG_ADMIN")
    viewer = _user(client, org, "view@acme.test", "COMPLIANCE_VIEWER")
    assert _na(client, viewer).status_code == 403
    assert _na(client, admin, clause="No such clause").status_code == 404
    guidance = next(r.clause for r in _pack() if r.guidance_only)
    assert _na(client, admin, clause=guidance).status_code == 409
    other = client.post("/duty-na", headers=_as(admin), json={"framework": "ISO-27001", "clause": "A.6.1", "reason": WHY})
    assert other.status_code == 422


def test_existing_nine_requirements_behave_as_before(client):
    org = _org(client)
    admin = _user(client, org, "admin@acme.test", "ORG_ADMIN")
    clauses = {c["clause"]: c for c in _ready(client, admin)["clauses"]}
    for clause in ORIGINAL:
        assert clauses[clause]["verdict"] == "NO_EVIDENCE" and not clauses[clause]["attestation_only"]
    # an existing rule-backed clause can still not be attested
    refused = client.post("/attestations", headers=_as(admin), json={
        "framework": "DPDP", "clause": "Rule 7", "statement": SAYS, "valid_until": UNTIL})
    assert refused.status_code == 409
