"""Attested controls (ADR-060): a rule-less clause is met only by a named person's dated statement, read as ATTESTED,
never PASS; a clause with a rule cannot be attested; a withdrawn or lapsed statement stops counting."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.content.load import load
from app.models import AuditEvent, ControlAttestation

TODAY = datetime.now(timezone.utc).date()
UNTIL = (TODAY + timedelta(days=300)).isoformat()
SAYS = "Screening is done by our HR provider before every start date; reports are kept in the HR system."


def _org(client):
    return client.post("/admin/organizations", json={"name": "Acme", "frameworks": ["ISO-27001"]}).json()["id"]


def _user(client, org, email, role):
    return client.post("/admin/users", json={"email": email, "org_id": org, "role": role}).json()["id"]


def _as(user_id):
    return {"authorization": f"user:{user_id}"}


def _attest(client, who, clause="A.6.1", **kw):
    return client.post("/attestations", headers=_as(who),
                       json={"framework": "ISO-27001", "clause": clause, "statement": SAYS, "valid_until": UNTIL, **kw})


def _readiness(client, who):
    return client.get("/analytics/readiness/ISO-27001", headers=_as(who)).json()


def test_iso_and_soc2_list_every_control_and_rule_less_ones_are_never_evaluated():
    content = load()
    iso = content.framework("ISO-27001").requirements
    assert len(iso) == 93 and len({r.clause for r in iso}) == 93
    soc2 = {r.clause for r in content.framework("SOC-2").requirements}
    assert {"CC1.1", "CC3.3", "CC5.3", "CC9.2"} <= soc2
    from app.evaluate import evaluate
    links = evaluate({"approval_date": "2026-01-01"}, "POLICY", ["ISO-27001"], content)
    assert all(not content.requirement("ISO-27001", l.clause).attestation_only for l in links)


def test_an_admin_attests_a_rule_less_control_and_it_reads_attested(client, db):
    org = _org(client)
    admin = _user(client, org, "admin@acme.test", "ORG_ADMIN")
    before = _readiness(client, admin)
    row = _attest(client, admin)
    assert row.status_code == 201, row.text
    after = _readiness(client, admin)
    clause = next(c for c in after["clauses"] if c["clause"] == "A.6.1")
    assert clause["verdict"] == "ATTESTED" and clause["attestation_only"] is True
    assert after["attested"] == 1 and after["satisfied"] == before["satisfied"]   # never counted as passed by rules
    assert after["readiness"] > before["readiness"]
    assert db.query(AuditEvent).filter_by(action="CONTROL_ATTESTED").count() == 1

    listed = client.get("/attestations", params={"framework": "ISO-27001"}, headers=_as(admin)).json()
    assert [a["current"] for a in listed] == [True]
    assert listed[0]["attested_by_display"] == "admin@acme.test"   # a name, not an internal id
    assert client.post(f"/attestations/{listed[0]['id']}/revoke", headers=_as(admin)).status_code == 200
    assert next(c for c in _readiness(client, admin)["clauses"] if c["clause"] == "A.6.1")["verdict"] == "NO_EVIDENCE"
    assert client.post(f"/attestations/{listed[0]['id']}/revoke", headers=_as(admin)).status_code == 409


def test_a_clause_with_a_rule_cannot_be_attested_and_bad_input_is_refused(client):
    org = _org(client)
    admin = _user(client, org, "admin@acme.test", "ORG_ADMIN")
    assert _attest(client, admin, clause="A.8.24").status_code == 409          # judged by rules
    assert _attest(client, admin, clause="A.99.9").status_code == 404
    assert _attest(client, admin, statement="yes").status_code == 422
    for bad in (TODAY.isoformat(), (TODAY + timedelta(days=400)).isoformat()):
        assert _attest(client, admin, valid_until=bad).status_code == 422
    assert _attest(client, admin, evidence_id="nope").status_code == 422
    assert client.post("/attestations", headers=_as(admin), json={
        "framework": "SOC-2", "clause": "CC1.1", "statement": SAYS, "valid_until": UNTIL}).status_code == 409  # not subscribed


def test_only_an_admin_or_the_owner_may_attest(client):
    org = _org(client)
    owner = _user(client, org, "owner@acme.test", "CONTROL_OWNER")
    viewer = _user(client, org, "viewer@acme.test", "COMPLIANCE_VIEWER")
    assert _attest(client, owner).status_code == 403          # owns no control yet
    assert _attest(client, viewer).status_code == 403


def test_a_lapsed_statement_stops_counting(client, db):
    org = _org(client)
    admin = _user(client, org, "admin@acme.test", "ORG_ADMIN")
    db.add(ControlAttestation(org_id=org, framework="ISO-27001", clause="A.6.1", statement=SAYS, attested_by="x",
                              valid_until=TODAY - timedelta(days=1)))
    db.commit()
    assert _readiness(client, admin)["attested"] == 0
