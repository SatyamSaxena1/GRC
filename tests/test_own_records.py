"""DPDP Phase 3b (ADR-071): duties our own records can prove are fixed rules over those records."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import db as db_module
from app.collectors import own_records
from app.content.load import load
from app.models import BreachEvent, PolicyAcceptance, PolicyDoc, RightsRequest, TrainingCompletion, TrainingCourse, User, Vendor
from app.routers import connectors
from app.service import process_evidence

NOW = datetime.now(timezone.utc).replace(tzinfo=None)
RULES = {  # clause -> the one fact it is judged on
    "Act s.11-12 - requests on time": "rights_requests_late",
    "Act s.12(3)": "erasure_requests_unfinished",
    "Act s.12(2)": "correction_requests_unfinished",
    "Act s.8(1) & s.8(5)": "personal_data_vendors_not_current",
    "Act s.8(4) - training": "members_without_current_training",
    "Act s.8(4) - policies": "approved_policies_unacknowledged",
    "Act s.8(1) & s.33(2) - audit trail": "audit_log_verifies",
    "Rule 7 - in practice": "breaches_reported_late",
}
STILL_ATTESTED = ("Act s.6(10) & s.33(2)", "Act s.33(2)(e)", "Act s.27(2) & s.28(7) / Rule 19(9)")


def _org(client):
    org = client.post("/admin/organizations", json={"name": "Acme", "frameworks": ["DPDP"]}).json()["id"]
    return org


def _collect(org):
    with Session(db_module.engine) as s:
        return own_records.collect(s, org, NOW)["attributes"]


def _verdicts(client, org):
    rd = client.get("/analytics/readiness/DPDP", headers={"authorization": f"org:{org}"}).json()
    return {c["clause"]: c for c in rd["clauses"]}


def _sync(org):
    with Session(db_module.engine) as s:
        ev = connectors.sync_connector_for_org(s, org, "system:test", "", "platform")
        process_evidence(s, connectors.CONTENT, ev, "system:test", "")


def test_the_pack_wires_each_clause_to_one_own_record_fact():
    pack = {r.clause: r for r in load().framework("DPDP").requirements}
    for clause, attr in RULES.items():
        r = pack[clause]
        assert not r.attestation_only and not r.ai_assessable
        assert {e.artefact_type for e in r.evidence_requirements} == {"PLATFORM_RECORDS_SNAPSHOT"}
        assert [c.attribute for m in r.mappings for c in m.delta_conditions] == [attr]
    for clause in STILL_ATTESTED:                     # nothing we keep can prove these, so they are not rules
        assert pack[clause].attestation_only
    assert set(own_records.ATTRIBUTES) == set(RULES.values())


def test_an_empty_record_is_none_not_zero(client):
    org = _org(client)
    got = _collect(org)
    assert {k: v for k, v in got.items() if k != "audit_log_verifies"} == {
        k: None for k in own_records.ATTRIBUTES if k != "audit_log_verifies"}
    _sync(org)
    v = _verdicts(client, org)
    for clause in RULES:                              # nothing logged is missing evidence, never a pass
        assert v[clause]["verdict"] != "PASS", clause


def test_rights_requests_count_late_and_unfinished(client, db):
    org = _org(client)
    day = timedelta(days=1)
    db.add_all([
        RightsRequest(org_id=org, kind="ACCESS", received_at=NOW - 40 * day, due_at=NOW - 10 * day, resolved_at=NOW - 12 * day, status="CLOSED", resolution_note="sent"),
        RightsRequest(org_id=org, kind="ACCESS", received_at=NOW - 40 * day, due_at=NOW - 10 * day, resolved_at=NOW - 2 * day, status="CLOSED", resolution_note="late"),
        RightsRequest(org_id=org, kind="ACCESS", received_at=NOW - 5 * day, due_at=NOW + 25 * day),
        RightsRequest(org_id=org, kind="ERASURE", received_at=NOW - 5 * day, due_at=NOW + 25 * day, resolved_at=NOW, status="CLOSED", resolution_note=" "),
        RightsRequest(org_id=org, kind="CORRECTION", received_at=NOW - 50 * day, due_at=NOW - 20 * day),
    ])
    db.commit()
    got = _collect(org)
    assert got["rights_requests_late"] == 2          # one answered after its date, one still open past it
    assert got["erasure_requests_unfinished"] == 1   # closed with no written outcome
    assert got["correction_requests_unfinished"] == 1


def test_vendors_training_policies_and_breaches(client, db):
    org = _org(client)
    admin = db.query(User).filter_by(org_id=org).first()
    admin = admin or User(org_id=org, email="a@acme.test", role="ORG_ADMIN")
    db.add(admin)
    db.flush()
    db.add_all([
        Vendor(org_id=org, name="Mail", data_access="PERSONAL", criticality="HIGH"),                       # never reviewed
        Vendor(org_id=org, name="Fonts", data_access="NONE"),                                              # no personal data: ignored
        Vendor(org_id=org, name="Pay", data_access="SENSITIVE", criticality="LOW", last_reviewed_at=NOW - timedelta(days=10)),
    ])
    course = TrainingCourse(org_id=org, title="Basics", body="x", cycle_days=365)
    policy = PolicyDoc(org_id=org, title="Privacy", body="x", status="APPROVED", approved_by="a", approved_at=NOW)
    db.add_all([course, policy])
    db.flush()
    db.add_all([
        BreachEvent(org_id=org, title="a", detected_at=NOW - timedelta(days=9), board_notify_due_at=NOW - timedelta(days=6),
                    board_notified_at=NOW - timedelta(days=7)),                                             # on time
        BreachEvent(org_id=org, title="b", detected_at=NOW - timedelta(days=9), board_notify_due_at=NOW - timedelta(days=6)),  # still waiting
    ])
    db.commit()
    got = _collect(org)
    assert got["personal_data_vendors_not_current"] == 1
    assert got["members_without_current_training"] == 1 and got["approved_policies_unacknowledged"] == 1
    assert got["breaches_reported_late"] == 1
    db.add_all([TrainingCompletion(org_id=org, course_id=course.id, version=course.version, user_id=admin.id, completed_at=NOW),
                PolicyAcceptance(org_id=org, policy_id=policy.id, version=policy.version, user_id=admin.id)])
    db.commit()
    got = _collect(org)
    assert got["members_without_current_training"] == 0 and got["approved_policies_unacknowledged"] == 0


def test_a_clean_record_passes_and_a_late_request_fails_after_the_next_collection(client, db):
    org = _org(client)
    db.add(RightsRequest(org_id=org, kind="ACCESS", received_at=NOW - timedelta(days=3), due_at=NOW + timedelta(days=27),
                         resolved_at=NOW, status="CLOSED", resolution_note="sent"))
    db.commit()
    _sync(org)
    assert _verdicts(client, org)["Act s.11-12 - requests on time"]["verdict"] == "PASS"
    assert _verdicts(client, org)["Act s.12(3)"]["verdict"] != "PASS"     # no erasure request yet: nothing to judge
    db.add(RightsRequest(org_id=org, kind="ACCESS", received_at=NOW - timedelta(days=60), due_at=NOW - timedelta(days=30)))
    db.commit()
    _sync(org)
    assert _verdicts(client, org)["Act s.11-12 - requests on time"]["verdict"] != "PASS"


def test_the_audit_chain_check_reads_the_organisations_own_chain(client, db):
    from app import audit_log
    org = _org(client)
    assert _collect(org)["audit_log_verifies"] is None            # nothing recorded yet: nothing to verify
    audit_log.record(db, actor="t", request_id="", action="TEST", entity_type="t", entity="1", org_id=org, detail={})
    db.commit()
    assert _collect(org)["audit_log_verifies"] is True
