"""The policy library (ADR-056): an admin writes and approves, each member accepts for themselves, and a change to the
text is a new version that everyone accepts again."""

from __future__ import annotations

from datetime import date, timedelta

from app.models import AuditEvent
from app.routers import policies

TEXT = "Access to our systems is limited to people who need it, and is removed when they leave."


def _org(client, name="Acme"):
    return client.post("/admin/organizations", json={"name": name, "frameworks": ["ISO-27001"]}).json()["id"]


def _user(client, email, org_id, role="CONTROL_OWNER"):
    return client.post("/admin/users", json={"email": email, "org_id": org_id, "role": role}).json()["id"]


def _as(user_id):
    return {"authorization": f"user:{user_id}"}


def _team(client):
    org = _org(client)
    return org, _user(client, "admin@acme.test", org, "ORG_ADMIN"), _user(client, "owner@acme.test", org)


def test_review_state_comes_from_the_review_date_alone():
    today = date(2026, 11, 10)
    assert policies.review_state("DRAFT", None, today) == "NOT_APPROVED"
    assert policies.review_state("APPROVED", today + timedelta(days=200), today) == "CURRENT"
    assert policies.review_state("APPROVED", today + timedelta(days=30), today) == "DUE_SOON"
    assert policies.review_state("APPROVED", today - timedelta(days=1), today) == "OVERDUE"


def test_a_policy_is_drafted_approved_and_accepted_by_each_person(client, db):
    org, admin, owner = _team(client)
    p = client.post("/policies", json={"title": "Access Control Policy", "body": TEXT}, headers=_as(admin)).json()
    assert p["status"] == "DRAFT" and p["version"] == 1 and p["review"] == "NOT_APPROVED"

    # a draft is the admin's: a member neither sees it nor can accept it
    assert client.get("/policies", headers=_as(owner)).json() == {"can_manage": False, "policies": []}
    assert client.get(f"/policies/{p['id']}", headers=_as(owner)).status_code == 404
    assert client.post(f"/policies/{p['id']}/accept", headers=_as(owner)).status_code == 409
    assert client.post(f"/policies/{p['id']}/approve", headers=_as(owner)).status_code == 403

    approved = client.post(f"/policies/{p['id']}/approve", headers=_as(admin)).json()
    assert approved["status"] == "APPROVED" and approved["review"] == "CURRENT" and approved["approved_by"] == f"user:{admin}"
    assert approved["people"] == 2 and approved["accepted"] == 0
    assert approved["waiting_on"] == ["admin@acme.test", "owner@acme.test"]

    mine = client.post(f"/policies/{p['id']}/accept", headers=_as(owner)).json()
    assert mine["accepted"] == 1 and mine["accepted_by_me"] is True and "waiting_on" not in mine   # names are for the admin
    assert client.post(f"/policies/{p['id']}/accept", headers=_as(owner)).json()["accepted"] == 1   # twice changes nothing
    assert db.query(AuditEvent).filter_by(action="POLICY_ACCEPTED", entity=p["id"]).count() == 1
    assert client.get(f"/policies/{p['id']}", headers=_as(admin)).json()["waiting_on"] == ["admin@acme.test"]
    assert client.get(f"/policies/{p['id']}", headers=_as(owner)).json()["body"] == TEXT


def test_changing_the_text_is_a_new_version_that_everyone_accepts_again(client, db):
    org, admin, owner = _team(client)
    p = client.post("/policies", json={"title": "Access Control Policy", "body": TEXT}, headers=_as(admin)).json()
    client.post(f"/policies/{p['id']}/approve", headers=_as(admin))
    client.post(f"/policies/{p['id']}/accept", headers=_as(owner))

    same = client.put(f"/policies/{p['id']}", json={"body": TEXT}, headers=_as(admin)).json()
    assert same["version"] == 1 and same["status"] == "APPROVED"                      # no change, no new version

    v2 = client.put(f"/policies/{p['id']}", json={"body": TEXT + " Reviewed every 90 days."}, headers=_as(admin)).json()
    assert v2["version"] == 2 and v2["status"] == "DRAFT" and v2["accepted"] == 0 and v2["approved_at"] is None
    event = db.query(AuditEvent).filter_by(action="POLICY_EDITED", entity=p["id"]).one()
    assert event.before["version"] == 1 and event.after["version"] == 2
    client.post(f"/policies/{p['id']}/approve", headers=_as(admin))
    assert client.get(f"/policies/{p['id']}", headers=_as(owner)).json()["accepted_by_me"] is False
    assert client.put(f"/policies/{p['id']}", json={"body": TEXT}, headers=_as(owner)).status_code == 403


def test_a_policy_can_start_from_a_template_and_a_deactivated_person_no_longer_counts(client):
    org, admin, owner = _team(client)
    p = client.post("/policies", json={"template_id": "incident-response"}, headers=_as(admin)).json()
    assert p["title"] == "Incident Response Policy" and "## Purpose" in p["body"]
    assert client.post("/policies", json={"template_id": "nope"}, headers=_as(admin)).status_code == 422
    assert client.post("/policies", json={"title": "Only a title"}, headers=_as(admin)).status_code == 422
    client.post(f"/policies/{p['id']}/approve", headers=_as(admin))
    client.patch(f"/admin/users/{owner}", json={"active": False}, headers=_as(admin))
    assert client.get(f"/policies/{p['id']}", headers=_as(admin)).json()["people"] == 1


def test_another_organisation_and_an_unnamed_caller_are_kept_out(client):
    org, admin, _ = _team(client)
    other = _org(client, "Other")
    stranger = _user(client, "x@other.test", other, "ORG_ADMIN")
    p = client.post("/policies", json={"title": "Access Control Policy", "body": TEXT}, headers=_as(admin)).json()
    client.post(f"/policies/{p['id']}/approve", headers=_as(admin))
    assert client.get("/policies", headers=_as(stranger)).json() == {"can_manage": True, "policies": []}
    for call in (client.get(f"/policies/{p['id']}", headers=_as(stranger)),
                 client.post(f"/policies/{p['id']}/accept", headers=_as(stranger)),
                 client.post(f"/policies/{p['id']}/approve", headers=_as(stranger))):
        assert call.status_code == 404
    # the organisation's shared token is not a person, so it cannot accept on anyone's behalf
    assert client.post(f"/policies/{p['id']}/accept", headers={"authorization": f"org:{org}"}).status_code == 422
