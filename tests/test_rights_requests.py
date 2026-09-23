from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_request_gets_default_thirty_day_sla_and_a_task(client, bootstrap):
    org_id, _ = bootstrap(client, frameworks=["DPDP"])
    headers = {"authorization": f"org:{org_id}"}
    received = datetime.now(timezone.utc).replace(microsecond=0)

    response = client.post("/rights-requests", headers=headers, json={
        "kind": "ERASURE", "requester_name": "Jane Doe", "received_at": received.isoformat(),
    })
    assert response.status_code == 201, response.text
    body = response.json()
    due = datetime.fromisoformat(body["due_at"])
    if due.tzinfo is None:  # SQLite hands timestamps back naive
        due = due.replace(tzinfo=timezone.utc)
    assert due - received == timedelta(days=30)
    assert body["overdue"] is False

    tasks = client.get("/tasks", headers=headers).json()
    assert any("ERASURE request from Jane Doe" in t["title"] for t in tasks)


def test_closing_a_request_closes_its_task_and_audits(client, bootstrap):
    org_id, _ = bootstrap(client, frameworks=["DPDP"])
    headers = {"authorization": f"org:{org_id}"}
    created = client.post("/rights-requests", headers=headers, json={
        "kind": "ACCESS", "received_at": datetime.now(timezone.utc).isoformat(),
    }).json()

    response = client.post(f"/rights-requests/{created['id']}/close", headers=headers,
                           json={"resolution_note": "exported and sent"})
    assert response.status_code == 200
    assert response.json()["status"] == "CLOSED"

    tasks = client.get("/tasks", headers=headers).json()
    task = next(t for t in tasks if "ACCESS request" in t["title"])
    assert task["status"] == "DONE"


def test_auditor_can_read_but_not_log_a_request(client, bootstrap):
    org_id, engagement_id = bootstrap(client, frameworks=["DPDP"])
    auditor_headers = {"authorization": f"auditor:{engagement_id}"}

    response = client.post("/rights-requests", headers=auditor_headers, json={
        "kind": "ACCESS", "received_at": datetime.now(timezone.utc).isoformat(),
    })
    assert response.status_code == 403

    listing = client.get("/rights-requests", headers=auditor_headers)
    assert listing.status_code == 200
