"""The audit trail has to be able to answer "who changed what, when, and from what".

Fields that exist but are never populated are worse than absent ones — they look
like coverage. These tests assert the columns actually carry data.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import db as db_module
from app.audit_log import verify_chain
from app.models import AuditEvent, EvidenceControlLink


def session():
    return Session(db_module.engine)


def events(action=None):
    with session() as s:
        query = s.query(AuditEvent)
        if action:
            query = query.filter_by(action=action)
        return query.order_by(AuditEvent.at).all()


def test_every_request_scoped_event_carries_its_request_id(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    upload(client, org_id)

    request_scoped = [e for e in events() if e.actor.startswith(("org:", "user:", "auditor:"))]
    assert request_scoped
    assert all(e.request_id for e in request_scoped), \
        "an audit row that cannot be traced to a request is not much of an audit row"


def test_supplied_request_id_is_preserved_end_to_end(client, bootstrap):
    org_id, _ = bootstrap(client)
    client.post("/evidence", headers={"authorization": f"org:{org_id}",
                                      "x-request-id": "trace-me-123"},
                files={"file": ("policy.txt", b"a policy", "text/plain")})

    uploaded = events("EVIDENCE_UPLOADED")
    assert uploaded and uploaded[-1].request_id == "trace-me-123"


def test_verdict_records_before_and_after_state(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    with session() as s:
        link = s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id).first()
        link_id, original_verdict = link.id, link.verdict

    client.post(f"/audit/links/{link_id}/verdict",
                headers={"authorization": f"auditor:{engagement_id}"},
                json={"verdict": "COMPLIANT", "reason": "reviewed against policy"})

    verdict_event = events("AUDITOR_VERDICT")[-1]
    assert verdict_event.before["auditor_verdict"] is None
    assert verdict_event.after["auditor_verdict"] == "COMPLIANT"
    assert verdict_event.reason == "reviewed against policy"

    lock_event = events("CONTROL_LOCKED")[-1]
    assert lock_event.before["locked"] is False
    assert lock_event.after["locked"] is True
    assert lock_event.before["verdict"] == original_verdict
    assert lock_event.after["verdict"] == "COMPLIANT"


def test_unlock_records_the_transition_and_the_reason(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    headers = {"authorization": f"auditor:{engagement_id}"}
    with session() as s:
        link_id = s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id).first().id

    client.post(f"/audit/links/{link_id}/lock", headers=headers, json={"verdict": "COMPLIANT"})
    client.post(f"/audit/links/{link_id}/unlock", headers=headers,
                json={"reason": "auditee supplied corrected evidence"})

    unlock = events("CONTROL_UNLOCKED")[-1]
    assert unlock.before["locked"] is True
    assert unlock.after["locked"] is False
    assert unlock.reason == "auditee supplied corrected evidence"


def test_supersession_records_the_lifecycle_transition(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    v1 = upload(client, org_id).json()["evidence_id"]
    client.post(f"/evidence/{v1}/versions", headers={"authorization": f"org:{org_id}"},
                files={"file": ("v2.txt", b"a revised policy", "text/plain")})

    superseded = events("EVIDENCE_SUPERSEDED")[-1]
    assert superseded.before["lifecycle_status"] == "CURRENT"
    assert superseded.after["lifecycle_status"] == "SUPERSEDED"


def test_cross_tenant_probe_is_recorded(client, bootstrap, upload):
    """Someone guessing another tenant's ids must leave a trail, even though the
    response tells them nothing."""
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    attacker = client.post("/admin/organizations",
                           json={"name": "Attacker", "frameworks": []}).json()["id"]

    resp = client.get(f"/evidence/{evidence_id}", headers={"authorization": f"org:{attacker}"})
    assert resp.status_code == 404  # tells the attacker nothing

    denials = events("AUTHORIZATION_DENIED")
    assert denials, "a cross-tenant probe must be recorded"
    assert denials[-1].actor == f"org:{attacker}"
    assert evidence_id in denials[-1].entity
    assert denials[-1].detail["reason"] == "cross-tenant evidence access"


def test_unassigned_control_access_is_recorded(client, bootstrap, upload):
    from app.models import OrgControl

    org_id, _ = bootstrap(client)
    upload(client, org_id)
    user = client.post("/admin/users", json={
        "email": "owner@acme.test", "org_id": org_id, "role": "CONTROL_OWNER",
    }).json()

    with session() as s:
        controls = {(c.framework, c.clause): c.id
                    for c in s.query(OrgControl).filter_by(org_id=org_id)}
    assigned, unassigned = controls[("ISO-27001", "A.5.15")], controls[("PCI-DSS", "8.3.6")]
    client.post("/admin/control-assignments",
                json={"org_control_id": assigned, "user_id": user["id"]})

    resp = client.get(f"/controls/{unassigned}", headers={"authorization": f"user:{user['id']}"})
    assert resp.status_code == 404

    denial = events("AUTHORIZATION_DENIED")[-1]
    assert denial.actor == f"user:{user['id']}"
    assert denial.detail["reason"] == "control not assigned to this user"
    assert denial.detail["clause"] == "8.3.6"


def test_closed_engagement_access_is_recorded(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    upload(client, org_id)
    client.post(f"/admin/engagements/{engagement_id}/close")

    client.get("/controls", headers={"authorization": f"auditor:{engagement_id}"})
    # A closed engagement is rejected at authentication, so the audit row comes from
    # the identity layer refusing the token rather than from an authorization check.
    assert events("ENGAGEMENT_CLOSED")


def test_hash_chain_still_verifies_with_before_after_populated(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    with session() as s:
        link_id = s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id).first().id
    client.post(f"/audit/links/{link_id}/verdict",
                headers={"authorization": f"auditor:{engagement_id}"},
                json={"verdict": "COMPLIANT"})

    with session() as s:
        assert verify_chain(s) is True

        # tampering with the recorded before-state must break the chain
        event = s.query(AuditEvent).filter_by(action="CONTROL_LOCKED").first()
        event.before = {"locked": True, "verdict": "COMPLIANT"}
        s.commit()
        assert verify_chain(s) is False
