"""Owners on controls and bulk task updates: org-admin only, org-scoped, audited, all-or-nothing."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import db as db_module
from app.models import AuditEvent, TaskRow


def _user(client, org_id, email, role="CONTROL_OWNER"):
    return client.post("/admin/users", json={"email": email, "org_id": org_id, "role": role}).json()["id"]


def _setup(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    upload(client, org_id)  # the default stub finds no facts: real gaps, tasks and controls
    admin = {"authorization": f"org:{org_id}"}
    owner_id = _user(client, org_id, "owner@acme.test")
    return org_id, admin, owner_id, client.get("/controls", headers=admin).json()


def _events(action):
    with Session(db_module.engine) as s:
        return s.query(AuditEvent).filter_by(action=action).all()


def test_the_controls_list_carries_owners_without_a_call_per_control(client, bootstrap, upload):
    org_id, admin, owner_id, controls = _setup(client, bootstrap, upload)
    assert all(c["owner_ids"] == [] and c["owner_emails"] == [] for c in controls)
    client.post(f"/controls/{controls[0]['id']}/owners", headers=admin, json={"user_id": owner_id})
    listed = {c["id"]: c for c in client.get("/controls", headers=admin).json()}
    assert listed[controls[0]["id"]]["owner_emails"] == ["owner@acme.test"]
    assert client.get(f"/controls/{controls[0]['id']}", headers=admin).json()["owner_ids"] == [owner_id]


def test_assigning_an_owner_is_idempotent_audited_under_the_real_actor_and_org_scoped(client, bootstrap, upload):
    org_id, admin, owner_id, controls = _setup(client, bootstrap, upload)
    cid = controls[0]["id"]
    first = client.post(f"/controls/{cid}/owners", headers=admin, json={"user_id": owner_id}).json()
    again = client.post(f"/controls/{cid}/owners", headers=admin, json={"user_id": owner_id}).json()
    assert first["created"] is True and again["created"] is False and again["owner_ids"] == [owner_id]
    events = _events("CONTROL_ASSIGNED")
    assert [e.actor for e in events][-1] == f"org:{org_id}" and len(events) == 1  # once, and not "admin"

    other_org, _ = bootstrap(client)
    stranger = _user(client, other_org, "x@other.test")
    assert client.post(f"/controls/{cid}/owners", headers=admin, json={"user_id": stranger}).status_code == 422
    assert client.post(f"/controls/{cid}/owners", headers={"authorization": f"org:{other_org}"},
                       json={"user_id": stranger}).status_code == 404


def test_only_an_org_admin_may_change_owners(client, bootstrap, upload):
    org_id, admin, owner_id, controls = _setup(client, bootstrap, upload)
    cid = controls[0]["id"]
    client.post(f"/controls/{cid}/owners", headers=admin, json={"user_id": owner_id})
    as_owner = {"authorization": f"user:{owner_id}"}
    assert client.post(f"/controls/{cid}/owners", headers=as_owner, json={"user_id": owner_id}).status_code == 403
    assert client.delete(f"/controls/{cid}/owners/{owner_id}", headers=as_owner).status_code == 403


def test_removing_an_owner_ends_their_access_and_is_audited(client, bootstrap, upload):
    org_id, admin, owner_id, controls = _setup(client, bootstrap, upload)
    cid = controls[0]["id"]
    client.post(f"/controls/{cid}/owners", headers=admin, json={"user_id": owner_id})
    as_owner = {"authorization": f"user:{owner_id}"}
    assert client.get(f"/controls/{cid}", headers=as_owner).status_code == 200
    assert client.delete(f"/controls/{cid}/owners/{owner_id}", headers=admin).json()["owner_ids"] == []
    assert client.get(f"/controls/{cid}", headers=as_owner).status_code in (403, 404)
    assert len(_events("CONTROL_UNASSIGNED")) == 1
    assert client.delete(f"/controls/{cid}/owners/{owner_id}", headers=admin).status_code == 404


def test_apply_to_tasks_hands_over_only_open_unassigned_tasks(client, bootstrap, upload):
    org_id, admin, owner_id, controls = _setup(client, bootstrap, upload)
    other = _user(client, org_id, "other@acme.test")
    tasks = client.get("/tasks", headers=admin).json()
    cid = tasks[0]["org_control_id"]
    same_control = [t for t in tasks if t["org_control_id"] == cid]
    assert len(same_control) >= 2
    client.patch(f"/tasks/{same_control[0]['id']}", headers=admin, json={"owner_user_id": other})  # already taken
    res = client.post(f"/controls/{cid}/owners", headers=admin, json={"user_id": owner_id, "apply_to_tasks": True}).json()
    assert res["tasks_assigned"] == len(same_control) - 1
    after = {t["id"]: t["owner_user_id"] for t in client.get("/tasks", headers=admin).json()}
    assert after[same_control[0]["id"]] == other
    assert all(after[t["id"]] == owner_id for t in same_control[1:])


def test_tasks_carry_what_they_are_about_so_they_can_be_grouped(client, bootstrap, upload):
    _, admin, _, _ = _setup(client, bootstrap, upload)
    task = client.get("/tasks", headers=admin).json()[0]
    assert task["attribute"] and task["kind"] == "MISSING_ATTRIBUTE" and task["org_control_id"]


def test_bulk_update_assigns_schedules_and_audits_each_task(client, bootstrap, upload):
    org_id, admin, owner_id, _ = _setup(client, bootstrap, upload)
    ids = [t["id"] for t in client.get("/tasks", headers=admin).json()][:4]
    res = client.post("/tasks/bulk", headers=admin, json={
        "task_ids": ids + ids[:1], "owner_user_id": owner_id, "due_at": "2027-01-15T00:00:00Z", "priority": "HIGH"})
    assert res.status_code == 200 and res.json()["requested"] == 4 and res.json()["changed"] == 4
    assert all(t["owner_user_id"] == owner_id and t["priority"] == "HIGH" and t["due_at"].startswith("2027-01-15")
               for t in res.json()["tasks"])
    assert len(_events("TASK_UPDATED")) == 4
    again = client.post("/tasks/bulk", headers=admin, json={"task_ids": ids, "priority": "HIGH"}).json()
    assert again["changed"] == 0 and len(_events("TASK_UPDATED")) == 4  # nothing moved, nothing audited
    cleared = client.post("/tasks/bulk", headers=admin, json={"task_ids": ids, "owner_user_id": None}).json()
    assert cleared["changed"] == 4 and all(t["owner_user_id"] is None for t in cleared["tasks"])


def test_bulk_update_is_all_or_nothing_and_org_admin_only(client, bootstrap, upload):
    org_id, admin, owner_id, _ = _setup(client, bootstrap, upload)
    ids = [t["id"] for t in client.get("/tasks", headers=admin).json()][:3]
    bad = client.post("/tasks/bulk", headers=admin, json={"task_ids": [*ids, "no-such-task"], "owner_user_id": owner_id})
    assert bad.status_code == 404
    with Session(db_module.engine) as s:
        assert s.query(TaskRow).filter(TaskRow.owner_user_id == owner_id).count() == 0
    assert client.post("/tasks/bulk", headers=admin, json={"task_ids": ids}).status_code == 422
    assert client.post("/tasks/bulk", headers=admin, json={"task_ids": ids, "priority": None}).status_code == 422
    other_org, _ = bootstrap(client)
    stranger = _user(client, other_org, "x@other.test")
    assert client.post("/tasks/bulk", headers=admin, json={"task_ids": ids, "owner_user_id": stranger}).status_code == 422
    assert client.post("/tasks/bulk", headers={"authorization": f"user:{owner_id}"},
                       json={"task_ids": ids, "priority": "LOW"}).status_code == 403
    assert client.post("/tasks/bulk", headers=admin, json={"task_ids": [], "priority": "LOW"}).status_code == 422
