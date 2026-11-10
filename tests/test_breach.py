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


def test_an_incident_policys_stated_hours_set_the_board_deadline(client, bootstrap, upload, monkeypatch):
    """The breach log holds the organisation to its own stated hours. Those now arrive in an incident policy, not only in
    the general POLICY, so an uploaded incident policy must still set the commitment (issue 82)."""
    from app import service
    from app.ai.schemas import ExtractedField, ExtractionRun

    def fake_extract(text, names, method="native_text", gateway=None):
        values = {"board_notification_hours": 24, "data_breach_response_process": True, "affected_person_notification": True}
        return ExtractionRun(fields={n: ExtractedField(value=values.get(n), confidence=1.0) for n in names},
                             model="stub", provider="stub", status="OK")

    monkeypatch.setattr(service, "extract_attributes", fake_extract)
    org_id, _ = bootstrap(client, frameworks=["DPDP"])
    upload(client, org_id, content=b"an incident response policy", name="incident.txt", artefact_type="INCIDENT_POLICY")
    headers = {"authorization": f"org:{org_id}"}
    detected = datetime.now(timezone.utc).replace(microsecond=0)
    body = client.post("/breach-events", headers=headers,
                       json={"title": "Leaked export", "detected_at": detected.isoformat()}).json()
    due = datetime.fromisoformat(body["board_notify_due_at"])
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    assert due - detected == timedelta(hours=24)
