"""Training (ADR-063): an admin writes courses, each person says they read and understood the current version, it lapses
after the cycle, and a new version of the text makes everyone do it again."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.models import AuditEvent, TrainingCompletion
from app.routers import training

TEXT = "Lock your screen when you leave your desk, and report anything odd to the security contact straight away."


def _org(client, name="Acme"):
    return client.post("/admin/organizations", json={"name": name, "frameworks": ["ISO-27001"]}).json()["id"]


def _user(client, email, org, role="CONTROL_OWNER"):
    return client.post("/admin/users", json={"email": email, "org_id": org, "role": role}).json()["id"]


def _as(user_id):
    return {"authorization": f"user:{user_id}"}


def _team(client):
    org = _org(client)
    return org, _user(client, "admin@acme.test", org, "ORG_ADMIN"), _user(client, "owner@acme.test", org)


def test_state_is_read_from_the_latest_completion_and_the_cycle_alone():
    now = datetime(2026, 11, 12)
    assert training.state(None, 365, now) == ("NOT_DONE", None)
    assert training.state(now - timedelta(days=10), 365, now)[0] == "DONE"
    assert training.state(now - timedelta(days=340), 365, now)[0] == "DUE_SOON"
    assert training.state(now - timedelta(days=366), 365, now)[0] == "OVERDUE"


def test_a_course_is_added_completed_by_each_person_and_counted(client, db):
    org, admin, owner = _team(client)
    c = client.post("/training", json={"template_id": "security-awareness"}, headers=_as(admin)).json()
    assert c["title"] == "Security awareness" and c["version"] == 1 and c["up_to_date"] == 0
    assert sorted(c["waiting_on"]) == ["admin@acme.test", "owner@acme.test"]

    seen = {"version": 1}
    mine = client.post(f"/training/{c['id']}/complete", json=seen, headers=_as(owner)).json()
    assert mine["my_state"] == "DONE" and mine["up_to_date"] == 1 and "waiting_on" not in mine   # the owner never sees names
    again = client.post(f"/training/{c['id']}/complete", json=seen, headers=_as(owner)).json()
    assert again["up_to_date"] == 1
    assert db.query(TrainingCompletion).filter_by(user_id=owner).count() == 1                    # asking twice changes nothing
    assert db.query(AuditEvent).filter_by(action="TRAINING_COMPLETED").count() == 1

    listed = client.get("/training", headers=_as(admin)).json()
    assert listed["can_manage"] and listed["courses"][0]["waiting_on"] == ["admin@acme.test"]


def test_a_new_text_makes_everyone_do_it_again_but_a_new_title_does_not(client, db):
    org, admin, owner = _team(client)
    c = client.post("/training", json={"title": "Office rules", "body": TEXT}, headers=_as(admin)).json()
    client.post(f"/training/{c['id']}/complete", json={"version": 1}, headers=_as(owner))
    renamed = client.put(f"/training/{c['id']}", json={"title": "Office and desk rules"}, headers=_as(admin)).json()
    assert renamed["version"] == 1 and renamed["up_to_date"] == 1
    edited = client.put(f"/training/{c['id']}", json={"body": TEXT + " Also lock your car."}, headers=_as(admin)).json()
    assert edited["version"] == 2 and edited["up_to_date"] == 0
    stale = client.post(f"/training/{c['id']}/complete", json={"version": 1}, headers=_as(owner))
    assert stale.status_code == 409                                                              # read the old text
    assert client.post(f"/training/{c['id']}/complete", json={"version": 2}, headers=_as(owner)).status_code == 200


def test_a_completion_older_than_the_cycle_is_overdue_and_can_be_renewed(client, db):
    org, admin, owner = _team(client)
    c = client.post("/training", json={"template_id": "data-protection-basics", "cycle_days": 90},
                    headers=_as(admin)).json()
    client.post(f"/training/{c['id']}/complete", json={"version": 1}, headers=_as(owner))
    row = db.query(TrainingCompletion).one()
    row.completed_at = datetime.utcnow() - timedelta(days=91)
    db.commit()
    assert client.get(f"/training/{c['id']}", headers=_as(owner)).json()["my_state"] == "OVERDUE"
    renewed = client.post(f"/training/{c['id']}/complete", json={"version": 1}, headers=_as(owner)).json()
    assert renewed["my_state"] == "DONE" and db.query(TrainingCompletion).count() == 2          # history is kept


def test_roles_tenants_and_input_are_enforced(client):
    org, admin, owner = _team(client)
    other = _user(client, "x@other.test", _org(client, "Other"), "ORG_ADMIN")
    c = client.post("/training", json={"template_id": "security-awareness"}, headers=_as(admin)).json()
    assert client.post("/training", json={"template_id": "security-awareness"}, headers=_as(owner)).status_code == 403
    assert client.put(f"/training/{c['id']}", json={"title": "Hacked"}, headers=_as(owner)).status_code == 403
    assert client.get(f"/training/{c['id']}", headers=_as(other)).status_code == 404            # another organisation
    assert client.get("/training", headers=_as(other)).json()["courses"] == []
    assert client.post("/training", json={"template_id": "nope"}, headers=_as(admin)).status_code == 422
    assert client.post("/training", json={"title": "Only a title"}, headers=_as(admin)).status_code == 422
    assert client.post("/training", json={"title": "Short", "body": TEXT, "cycle_days": 5},
                       headers=_as(admin)).status_code == 422
    assert client.get("/training/templates", headers=_as(owner)).status_code == 403
    assert len(client.get("/training/templates", headers=_as(admin)).json()) == 2
