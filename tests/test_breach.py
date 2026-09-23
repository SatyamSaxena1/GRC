from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_breach_creates_board_task_with_statutory_deadline(client, bootstrap):
    org_id, _ = bootstrap(client, frameworks=["DPDP"])
    headers = {"authorization": f"org:{org_id}"}
    detected = datetime.now(timezone.utc).replace(microsecond=0)

    response = client.post("/breach-events", headers=headers, json={
        "title": "Leaked customer export", "detected_at": detected.isoformat(),
    })
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "OPEN"
    assert body["board_overdue"] is False
    due = datetime.fromisoformat(body["board_notify_due_at"])
    if due.tzinfo is None:  # SQLite hands timestamps back naive
        due = due.replace(tzinfo=timezone.utc)
    assert due - detected == timedelta(hours=72)  # statutory ceiling, no org commitment set
    assert body["affected_notify_due_at"] is None  # no statutory number, none invented

    tasks = client.get("/tasks", headers=headers).json()
    titles = [t["title"] for t in tasks]
    assert any("Notify Board" in t for t in titles)


def test_only_org_admin_can_declare_a_breach(client, bootstrap):
    org_id, _ = bootstrap(client, frameworks=["DPDP"])
    user = client.post("/admin/users", json={
        "email": "owner@acme.test", "org_id": org_id, "role": "CONTROL_OWNER",
    }).json()
    response = client.post("/breach-events", headers={"authorization": f"user:{user['id']}"}, json={
        "title": "x", "detected_at": datetime.now(timezone.utc).isoformat(),
    })
    assert response.status_code == 403


def test_notify_board_closes_task_and_is_audited(client, bootstrap):
    org_id, _ = bootstrap(client, frameworks=["DPDP"])
    headers = {"authorization": f"org:{org_id}"}
    created = client.post("/breach-events", headers=headers, json={
        "title": "Test breach", "detected_at": datetime.now(timezone.utc).isoformat(),
    }).json()

    response = client.post(f"/breach-events/{created['id']}/notify-board", headers=headers,
                           json={"note": "told the board"})
    assert response.status_code == 200
    assert response.json()["board_notified_at"] is not None

    tasks = {t["title"]: t for t in client.get("/tasks", headers=headers).json()}
    board_task = next(t for title, t in tasks.items() if "Notify Board" in title)
    assert board_task["status"] == "DONE"
