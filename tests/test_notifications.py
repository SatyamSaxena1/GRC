"""GET /notifications — a pure read-model combining open tasks, open evidence/
unlock requests, and evidence going stale. No new authorization rule: every
item comes from calling the existing list_tasks/list_requests functions
directly, so role-scoping matches those exactly (see test_control_messages.py
for the underlying rules this reuses)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import db as db_module
from app.models import OrgControl


def controls_for(org_id):
    with Session(db_module.engine) as s:
        return {(c.framework, c.clause): c.id
                for c in s.query(OrgControl).filter_by(org_id=org_id)}


def test_open_task_appears_as_a_notification(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    upload(client, org_id)  # extraction unavailable -> gaps -> tasks, in-process

    body = client.get("/notifications", headers={"authorization": f"org:{org_id}"}).json()
    assert body["count"] > 0
    assert any(i["kind"] == "TASK_OPEN" for i in body["items"])


def test_evidence_request_appears_and_disappears_once_resolved(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    upload(client, org_id)
    control_id = next(iter(controls_for(org_id).values()))

    client.post(f"/controls/{control_id}/messages",
               headers={"authorization": f"auditor:{engagement_id}"},
               json={"kind": "EVIDENCE_REQUEST", "body": "please provide the network diagram"})

    before = client.get("/notifications", headers={"authorization": f"org:{org_id}"}).json()
    request_items = [i for i in before["items"] if i["kind"] == "EVIDENCE_REQUEST"]
    assert len(request_items) == 1
    assert request_items[0]["link"] == f"/controls/{control_id}"

    message_id = client.get(f"/controls/{control_id}/messages",
                            headers={"authorization": f"org:{org_id}"}).json()[0]["id"]
    client.patch(f"/controls/{control_id}/messages/{message_id}/resolve",
                 headers={"authorization": f"auditor:{engagement_id}"},
                 json={"resolution_note": "attached"})

    after = client.get("/notifications", headers={"authorization": f"org:{org_id}"}).json()
    assert not [i for i in after["items"] if i["kind"] == "EVIDENCE_REQUEST"]


def test_notifications_are_org_isolated(client, bootstrap, upload):
    org_a, _ = bootstrap(client)
    org_b, _ = bootstrap(client)
    upload(client, org_a)

    a = client.get("/notifications", headers={"authorization": f"org:{org_a}"}).json()
    b = client.get("/notifications", headers={"authorization": f"org:{org_b}"}).json()
    assert a["count"] > 0
    assert b["count"] == 0
