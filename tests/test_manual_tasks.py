"""An org admin handing work straight to an employee, with no evidence gap
behind it. Visibility and status rules differ from a gap-derived task — see
app/models.py:TaskRow and app/routers/controls.py's _task_visible."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import db as db_module
from app.models import OrgControl


def controls_for(org_id):
    with Session(db_module.engine) as s:
        return {(c.framework, c.clause): c.id
                for c in s.query(OrgControl).filter_by(org_id=org_id)}


def make_employee(client, org_id, email="employee@acme.test"):
    return client.post("/admin/users", json={
        "email": email, "org_id": org_id, "role": "CONTROL_OWNER",
    }).json()["id"]


def test_org_admin_can_assign_a_manual_task(client, bootstrap):
    org_id, _ = bootstrap(client)
    employee_id = make_employee(client, org_id)
    headers = {"authorization": f"org:{org_id}"}

    resp = client.post("/tasks", headers=headers, json={
        "title": "Sign the updated access control policy",
        "description": "Legal needs a wet signature before Friday.",
        "owner_user_id": employee_id,
        "priority": "HIGH",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_manual"] is True
    assert body["gap_id"] is None
    assert body["owner_email"] == "employee@acme.test"
    assert body["status"] == "OPEN"


def test_only_an_org_admin_can_assign_a_task(client, bootstrap):
    org_id, engagement_id = bootstrap(client)
    employee_id = make_employee(client, org_id)

    as_employee = client.post("/tasks", headers={"authorization": f"user:{employee_id}"},
                              json={"title": "not mine to assign"})
    assert as_employee.status_code == 403

    as_auditor = client.post("/tasks", headers={"authorization": f"auditor:{engagement_id}"},
                             json={"title": "not mine to assign"})
    assert as_auditor.status_code == 403


def test_manual_task_is_visible_only_to_its_owner_and_the_admin(client, bootstrap):
    org_id, _ = bootstrap(client)
    employee_id = make_employee(client, org_id, "owner@acme.test")
    other_id = make_employee(client, org_id, "bystander@acme.test")
    admin_headers = {"authorization": f"org:{org_id}"}

    task = client.post("/tasks", headers=admin_headers,
                       json={"title": "task", "owner_user_id": employee_id}).json()

    assert [t["id"] for t in client.get("/tasks", headers=admin_headers).json()] == [task["id"]]
    assert [t["id"] for t in client.get(
        "/tasks", headers={"authorization": f"user:{employee_id}"}).json()] == [task["id"]]
    assert client.get("/tasks", headers={"authorization": f"user:{other_id}"}).json() == []
    assert client.get(f"/tasks/{task['id']}",
                      headers={"authorization": f"user:{other_id}"}).status_code == 404


def test_auditor_never_sees_a_manual_task(client, bootstrap):
    org_id, engagement_id = bootstrap(client)
    employee_id = make_employee(client, org_id)
    client.post("/tasks", headers={"authorization": f"org:{org_id}"},
               json={"title": "internal only", "owner_user_id": employee_id})

    assert client.get("/tasks", headers={"authorization": f"auditor:{engagement_id}"}).json() == []


def test_manual_task_scoped_to_a_control_follows_control_assignment(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    upload(client, org_id)
    control_id = next(iter(controls_for(org_id).values()))
    assigned = make_employee(client, org_id, "assigned@acme.test")
    unassigned = make_employee(client, org_id, "unassigned@acme.test")
    client.post("/admin/control-assignments", json={"org_control_id": control_id, "user_id": assigned})

    task = client.post("/tasks", headers={"authorization": f"org:{org_id}"}, json={
        "title": "gather evidence for this control", "owner_user_id": unassigned,
        "org_control_id": control_id,
    }).json()

    # Assigned to `unassigned` as the doer, but scoped to a control only
    # `assigned` may see — control scope wins over who the task is for.
    # (assigned also sees this control's other, gap-derived tasks; that's
    # correct control-owner visibility, not part of what this test checks.)
    seen_by_assigned = {t["id"] for t in client.get(
        "/tasks", headers={"authorization": f"user:{assigned}"}).json()}
    assert task["id"] in seen_by_assigned
    assert client.get("/tasks", headers={"authorization": f"user:{unassigned}"}).json() == []


def test_owner_can_close_their_own_manual_task_but_not_reassign_it(client, bootstrap):
    org_id, _ = bootstrap(client)
    employee_id = make_employee(client, org_id)
    task = client.post("/tasks", headers={"authorization": f"org:{org_id}"},
                       json={"title": "task", "owner_user_id": employee_id}).json()
    owner_headers = {"authorization": f"user:{employee_id}"}

    denied = client.patch(f"/tasks/{task['id']}", headers=owner_headers, json={"priority": "CRITICAL"})
    assert denied.status_code == 403

    done = client.patch(f"/tasks/{task['id']}", headers=owner_headers, json={"status": "DONE"})
    assert done.status_code == 200
    assert done.json()["status"] == "DONE"


def test_gap_derived_task_status_stays_evidence_driven(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    upload(client, org_id)
    headers = {"authorization": f"org:{org_id}"}
    task = client.get("/tasks", headers=headers).json()[0]

    resp = client.patch(f"/tasks/{task['id']}", headers=headers, json={"status": "DONE"})
    assert resp.status_code == 409


def test_assigning_to_someone_outside_the_org_is_rejected(client, bootstrap):
    org_id, _ = bootstrap(client)
    other_org = client.post("/admin/organizations", json={"name": "Other", "frameworks": []}).json()["id"]
    outsider_id = make_employee(client, other_org, "outsider@other.test")

    resp = client.post("/tasks", headers={"authorization": f"org:{org_id}"},
                       json={"title": "task", "owner_user_id": outsider_id})
    assert resp.status_code == 422
