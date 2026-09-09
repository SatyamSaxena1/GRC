"""Auditor<->auditee conversation on a control: evidence requests, unlock
requests, comments. Same authorization shape as the rest of the app — an
out-of-scope control is 404, not 403 (see app/authorization.py)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import db as db_module
from app.models import AuditEvent, EvidenceControlLink, OrgControl


def controls_for(org_id):
    with Session(db_module.engine) as s:
        return {(c.framework, c.clause): c.id
                for c in s.query(OrgControl).filter_by(org_id=org_id)}


def first_link(evidence_id):
    with Session(db_module.engine) as s:
        link = s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id).first()
        return link.id


def test_auditor_can_request_evidence_but_auditee_cannot(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    upload(client, org_id)
    control_id = next(iter(controls_for(org_id).values()))

    resp = client.post(f"/controls/{control_id}/messages",
                       headers={"authorization": f"auditor:{engagement_id}"},
                       json={"kind": "EVIDENCE_REQUEST", "body": "please provide the network diagram"})
    assert resp.status_code == 201
    assert resp.json()["status"] == "OPEN"

    denied = client.post(f"/controls/{control_id}/messages",
                         headers={"authorization": f"org:{org_id}"},
                         json={"kind": "EVIDENCE_REQUEST", "body": "not mine to ask"})
    assert denied.status_code == 403


def test_auditee_can_request_unlock_only_when_locked(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    control_id = next(iter(controls_for(org_id).values()))

    not_locked = client.post(f"/controls/{control_id}/messages",
                             headers={"authorization": f"org:{org_id}"},
                             json={"kind": "UNLOCK_REQUEST", "body": "please reopen"})
    assert not_locked.status_code == 409

    link_id = first_link(evidence_id)
    client.post(f"/audit/links/{link_id}/lock", headers={"authorization": f"auditor:{engagement_id}"},
               json={"verdict": "PASS"})

    ok = client.post(f"/controls/{control_id}/messages",
                     headers={"authorization": f"org:{org_id}"},
                     json={"kind": "UNLOCK_REQUEST", "body": "please reopen, evidence was wrong version"})
    assert ok.status_code == 201

    as_auditor = client.post(f"/controls/{control_id}/messages",
                             headers={"authorization": f"auditor:{engagement_id}"},
                             json={"kind": "UNLOCK_REQUEST", "body": "not mine to ask"})
    assert as_auditor.status_code == 403


def test_comment_visible_to_both_sides_but_not_outside_scope(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    upload(client, org_id)
    control_id = next(iter(controls_for(org_id).values()))

    client.post(f"/controls/{control_id}/messages", headers={"authorization": f"org:{org_id}"},
               json={"kind": "COMMENT", "body": "uploaded the latest policy"})
    thread = client.get(f"/controls/{control_id}/messages",
                        headers={"authorization": f"auditor:{engagement_id}"}).json()
    assert len(thread) == 1 and thread[0]["kind"] == "COMMENT"

    other_org, _ = bootstrap(client, frameworks=("ISO-27001",))
    assert client.get(f"/controls/{control_id}/messages",
                      headers={"authorization": f"org:{other_org}"}).status_code == 404


def test_only_auditor_resolves_and_not_twice(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    upload(client, org_id)
    control_id = next(iter(controls_for(org_id).values()))
    message = client.post(f"/controls/{control_id}/messages",
                          headers={"authorization": f"auditor:{engagement_id}"},
                          json={"kind": "EVIDENCE_REQUEST", "body": "need more"}).json()

    denied = client.patch(f"/controls/{control_id}/messages/{message['id']}/resolve",
                          headers={"authorization": f"org:{org_id}"}, json={"resolution_note": "done"})
    assert denied.status_code == 403

    ok = client.patch(f"/controls/{control_id}/messages/{message['id']}/resolve",
                      headers={"authorization": f"auditor:{engagement_id}"},
                      json={"resolution_note": "satisfied by v2"})
    assert ok.status_code == 200
    assert ok.json()["status"] == "RESOLVED"

    again = client.patch(f"/controls/{control_id}/messages/{message['id']}/resolve",
                         headers={"authorization": f"auditor:{engagement_id}"}, json={})
    assert again.status_code == 409


def test_create_and_resolve_are_audited(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    upload(client, org_id)
    control_id = next(iter(controls_for(org_id).values()))
    message = client.post(f"/controls/{control_id}/messages",
                          headers={"authorization": f"auditor:{engagement_id}"},
                          json={"kind": "EVIDENCE_REQUEST", "body": "need more"}).json()
    client.patch(f"/controls/{control_id}/messages/{message['id']}/resolve",
                headers={"authorization": f"auditor:{engagement_id}"}, json={"resolution_note": "ok"})

    with Session(db_module.engine) as s:
        actions = [e.action for e in s.query(AuditEvent).filter_by(entity=message["id"]).order_by(AuditEvent.seq)]
    assert actions == ["CONTROL_MESSAGE_CREATED", "CONTROL_MESSAGE_RESOLVED"]


def test_requests_endpoint_is_scoped_to_visible_controls(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    upload(client, org_id)
    control_id = next(iter(controls_for(org_id).values()))
    client.post(f"/controls/{control_id}/messages",
               headers={"authorization": f"auditor:{engagement_id}"},
               json={"kind": "EVIDENCE_REQUEST", "body": "need more"})

    seen_by_org = client.get("/requests", headers={"authorization": f"org:{org_id}"}).json()
    assert len(seen_by_org) == 1

    other_org, _ = bootstrap(client, frameworks=("ISO-27001",))
    seen_by_other = client.get("/requests", headers={"authorization": f"org:{other_org}"}).json()
    assert seen_by_other == []

    user = client.post("/admin/users", json={
        "email": "owner@acme.test", "org_id": org_id, "role": "CONTROL_OWNER",
    }).json()
    unassigned_view = client.get("/requests", headers={"authorization": f"user:{user['id']}"}).json()
    assert unassigned_view == []  # not assigned to this control, so its requests are invisible
