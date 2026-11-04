"""Auditor findings (ADR-032): raised and closed by an auditor, answered by the auditee, all audited."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app import db as db_module, notify
from app.audit_log import verify_chain
from app.models import AuditEvent

DESC = "the access review for privileged accounts was not performed in the last two quarters"
ANSWER = "we performed the review on 12 October and attached the signed log to the control"
NOTE = "the signed log was checked against the account list and covers all privileged accounts"


@pytest.fixture()
def world(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    upload(client, org_id)
    admin, auditor = {"authorization": f"org:{org_id}"}, {"authorization": f"auditor:{engagement_id}"}
    controls = client.get("/controls", headers=admin).json()
    owner = client.post("/admin/users", json={"email": "owner@acme.test", "org_id": org_id, "role": "CONTROL_OWNER"}).json()["id"]
    viewer = client.post("/admin/users", json={"email": "viewer@acme.test", "org_id": org_id, "role": "COMPLIANCE_VIEWER"}).json()["id"]
    return client, org_id, admin, auditor, controls[0]["id"], controls[1]["id"], owner, viewer


def _raise(client, auditor, control_id, **over):
    return client.post(f"/controls/{control_id}/findings", headers=auditor,
                       json={"title": "Privileged access review missing", "severity": "HIGH", "description": DESC, **over})


def _events():
    with Session(db_module.engine) as s:
        return [e for e in s.query(AuditEvent).order_by(AuditEvent.at) if e.action.startswith("FINDING_")]


def test_an_auditor_raises_a_finding_and_the_auditee_sees_it(world):
    client, org_id, admin, auditor, cid, _, _, _ = world
    created = _raise(client, auditor, cid)
    assert created.status_code == 201
    f = created.json()
    assert f["status"] == "OPEN" and f["severity"] == "HIGH" and f["raised_by_display"] == "Auditor · BigFour"
    listed = client.get(f"/controls/{cid}/findings", headers=admin).json()
    assert [x["id"] for x in listed] == [f["id"]] and listed[0]["description"] == DESC
    (event,) = _events()
    assert event.action == "FINDING_RAISED" and event.before is None and event.after["status"] == "OPEN"


def test_only_an_auditor_raises_and_findings_must_say_what(world):
    client, org_id, admin, auditor, cid, _, owner, _ = world
    assert _raise(client, admin, cid).status_code == 403
    assert _raise(client, {"authorization": f"user:{owner}"}, cid).status_code == 403
    assert _raise(client, auditor, cid, description="bad").status_code == 422
    assert _raise(client, auditor, cid, severity="URGENT").status_code == 422
    assert _raise(client, auditor, cid, title="x").status_code == 422
    assert _events() == []


def test_the_full_lifecycle_is_audited_with_before_and_after(world):
    client, org_id, admin, auditor, cid, _, _, _ = world
    fid = _raise(client, auditor, cid).json()["id"]
    assert client.post(f"/findings/{fid}/respond", headers=admin, json={"response": ANSWER}).json()["status"] == "RESPONDED"
    closed = client.post(f"/findings/{fid}/close", headers=auditor, json={"note": NOTE}).json()
    assert closed["status"] == "CLOSED" and closed["close_note"] == NOTE and closed["closed_by_display"] == "Auditor · BigFour"
    assert client.post(f"/findings/{fid}/reopen", headers=auditor, json={"note": "the log turned out to cover only one quarter"}).json()["status"] == "OPEN"
    events = _events()
    assert [e.action for e in events] == ["FINDING_RAISED", "FINDING_RESPONDED", "FINDING_CLOSED", "FINDING_REOPENED"]
    assert (events[1].before["status"], events[1].after["status"]) == ("OPEN", "RESPONDED") and events[1].reason == ANSWER
    assert (events[2].before["status"], events[2].after["status"]) == ("RESPONDED", "CLOSED")
    assert (events[3].before["status"], events[3].after["status"]) == ("CLOSED", "OPEN")
    with Session(db_module.engine) as s:
        assert verify_chain(s)


def test_who_may_do_what_to_a_finding(world):
    client, org_id, admin, auditor, cid, other_cid, owner, viewer = world
    fid = _raise(client, auditor, cid).json()["id"]
    assert client.post(f"/findings/{fid}/respond", headers=auditor, json={"response": ANSWER}).status_code == 403  # the auditor does not answer itself
    assert client.post(f"/findings/{fid}/respond", headers={"authorization": f"user:{viewer}"}, json={"response": ANSWER}).status_code == 403
    assert client.post(f"/findings/{fid}/respond", headers=admin, json={"response": "ok"}).status_code == 422
    assert client.post(f"/findings/{fid}/close", headers=admin, json={"note": NOTE}).status_code == 403
    assert client.post(f"/findings/{fid}/close", headers=auditor, json={"note": "done"}).status_code == 422
    # a control owner answers only for a control they have been given
    as_owner = {"authorization": f"user:{owner}"}
    assert client.post(f"/findings/{fid}/respond", headers=as_owner, json={"response": ANSWER}).status_code in (403, 404)
    client.post(f"/controls/{cid}/owners", headers=admin, json={"user_id": owner})
    assert client.post(f"/findings/{fid}/respond", headers=as_owner, json={"response": ANSWER}).status_code == 200


def test_closed_findings_are_closed_until_an_auditor_reopens_them(world):
    client, org_id, admin, auditor, cid, _, _, _ = world
    fid = _raise(client, auditor, cid).json()["id"]
    assert client.post(f"/findings/{fid}/reopen", headers=auditor, json={"note": "it was never closed at all"}).status_code == 409
    client.post(f"/findings/{fid}/close", headers=auditor, json={"note": NOTE})
    assert client.post(f"/findings/{fid}/close", headers=auditor, json={"note": NOTE}).status_code == 409
    assert client.post(f"/findings/{fid}/respond", headers=admin, json={"response": ANSWER}).status_code == 409
    assert client.post(f"/findings/{fid}/reopen", headers=admin, json={"note": "the auditee cannot reopen"}).status_code == 403


def test_findings_stay_inside_their_organisation_and_visible_controls(world, bootstrap):
    client, org_id, admin, auditor, cid, other_cid, owner, _ = world
    fid = _raise(client, auditor, cid).json()["id"]
    other_org, _ = bootstrap(client)
    stranger = {"authorization": f"org:{other_org}"}
    assert client.post(f"/findings/{fid}/respond", headers=stranger, json={"response": ANSWER}).status_code == 404
    assert client.get(f"/controls/{cid}/findings", headers=stranger).status_code == 404
    assert client.get("/findings", headers=stranger).json() == []
    # a control owner lists only findings on the controls assigned to them
    as_owner = {"authorization": f"user:{owner}"}
    assert client.get("/findings", headers=as_owner).json() == []
    client.post(f"/controls/{cid}/owners", headers=admin, json={"user_id": owner})
    assert [f["id"] for f in client.get("/findings", headers=as_owner).json()] == [fid]
    assert [f["id"] for f in client.get("/findings?status=OPEN", headers=admin).json()] == [fid]
    assert client.get("/findings?status=CLOSED", headers=admin).json() == []


def test_raising_a_finding_notifies_without_leaking_its_text(world, monkeypatch):
    client, org_id, admin, auditor, cid, _, _, _ = world
    sent = []
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://hooks.test/x")
    monkeypatch.setattr(notify, "_spawn", lambda work: work())
    monkeypatch.setattr(notify, "_post", lambda payload, *args, **kwargs: sent.append(payload) or True)
    _raise(client, auditor, cid)
    (payload,) = sent
    assert payload["kind"] == "FINDING_RAISED" and payload["severity"] == "high"
    assert payload["message"].startswith("A high finding was raised on ")
    assert "Privileged" not in payload["message"] and DESC not in str(payload)


def test_a_controls_history_includes_its_findings_events(world):
    client, org_id, admin, auditor, cid, other_cid, _, _ = world
    fid = _raise(client, auditor, cid).json()["id"]
    client.post(f"/findings/{fid}/respond", headers=admin, json={"response": ANSWER})
    actions = [e["action"] for e in client.get(f"/controls/{cid}/history", headers=admin).json()]
    assert actions.count("FINDING_RAISED") == 1 and actions.count("FINDING_RESPONDED") == 1
    assert not any(a.startswith("FINDING_") for e in [client.get(f"/controls/{other_cid}/history", headers=admin).json()] for a in [x["action"] for x in e])
