"""Outbound webhook notices (ADR-031): off by default, content-free, signed, never blocking."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta

import pytest
import requests
from sqlalchemy.orm import Session

from app import db as db_module, notify
from app.models import EvidenceControlLink, NotificationLog

URL = "https://hooks.test/services/abc"
REASON = "reviewed the signed policy and the review log; accepting it with a compensating control"


@pytest.fixture()
def posts(monkeypatch):
    """Capture webhook calls. Delivery runs inline instead of on a thread."""
    sent: list[dict] = []

    class Response:
        status_code = 200

    def fake_post(url, data=None, headers=None, timeout=None):
        sent.append({"url": url, "body": json.loads(data), "raw": data, "headers": headers, "timeout": timeout})
        return Response()

    monkeypatch.setattr(notify.requests, "post", fake_post)
    monkeypatch.setattr(notify, "_spawn", lambda work: work())
    return sent


@pytest.fixture()
def configured(monkeypatch):
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", URL)


def _user(client, org_id, email="owner@acme.test"):
    return client.post("/admin/users", json={"email": email, "org_id": org_id, "role": "CONTROL_OWNER"}).json()["id"]


def test_nothing_is_sent_unless_a_webhook_is_configured(client, bootstrap, upload, posts):
    org_id, _ = bootstrap(client)
    upload(client, org_id)
    owner = _user(client, org_id)
    admin = {"authorization": f"org:{org_id}"}
    task_id = client.get("/tasks", headers=admin).json()[0]["id"]
    client.patch(f"/tasks/{task_id}", headers=admin, json={"owner_user_id": owner})
    assert posts == [] and not notify.enabled()


def test_a_task_assignment_posts_one_small_signed_content_free_notice(client, bootstrap, upload, posts, configured, monkeypatch):
    monkeypatch.setenv("NOTIFY_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setenv("NOTIFY_LINK_BASE_URL", "https://grc.example.com/")
    org_id, _ = bootstrap(client)
    upload(client, org_id)
    owner = _user(client, org_id)
    admin = {"authorization": f"org:{org_id}"}
    task = client.get("/tasks", headers=admin).json()[0]
    client.patch(f"/tasks/{task['id']}", headers=admin, json={"owner_user_id": owner})

    (call,) = posts
    body = call["body"]
    assert call["url"] == URL and body["kind"] == "TASK_ASSIGNED" and body["org_id"] == org_id
    assert body["text"] == body["content"] == f"[INFO] {task['title']} assigned to owner@acme.test"
    assert body["link"] == "https://grc.example.com/tasks"
    assert set(body) == {"text", "content", "kind", "severity", "message", "link", "org_id", "at"}  # nothing else leaks
    expected = "sha256=" + hmac.new(b"s3cret", call["raw"], hashlib.sha256).hexdigest()
    assert call["headers"]["X-GRC-Signature"] == expected

    # assigning the same person again moves nothing, so says nothing
    client.patch(f"/tasks/{task['id']}", headers=admin, json={"owner_user_id": owner})
    assert len(posts) == 1


def test_a_bulk_assignment_is_one_notice_not_one_per_task(client, bootstrap, upload, posts, configured):
    org_id, _ = bootstrap(client)
    upload(client, org_id)
    owner = _user(client, org_id)
    admin = {"authorization": f"org:{org_id}"}
    ids = [t["id"] for t in client.get("/tasks", headers=admin).json()][:5]
    client.post("/tasks/bulk", headers=admin, json={"task_ids": ids, "owner_user_id": owner})
    assert [p["body"]["message"] for p in posts] == ["5 tasks assigned to owner@acme.test"]


def test_evidence_requests_unlock_requests_and_locks_notify(client, bootstrap, upload, posts, configured):
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    admin, auditor = {"authorization": f"org:{org_id}"}, {"authorization": f"auditor:{engagement_id}"}
    with Session(db_module.engine) as s:
        link = s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id, framework="PCI-DSS").first()
        link_id, framework, clause = link.id, link.framework, link.clause
    control_id = next(c["id"] for c in client.get("/controls", headers=admin).json()
                      if (c["framework"], c["clause"]) == (framework, clause))

    client.post(f"/controls/{control_id}/messages", headers=auditor, json={"kind": "EVIDENCE_REQUEST", "body": "please send the access review"})
    client.post(f"/audit/links/{link_id}/lock", headers=auditor, json={"verdict": "COMPLIANT", "reason": REASON})
    client.post(f"/controls/{control_id}/messages", headers=admin, json={"kind": "UNLOCK_REQUEST", "body": "new evidence is ready"})
    client.post(f"/controls/{control_id}/messages", headers=admin, json={"kind": "COMMENT", "body": "no notice for a comment"})

    assert [(p["body"]["kind"], p["body"]["message"]) for p in posts] == [
        ("EVIDENCE_REQUEST", f"Evidence requested on {framework} {clause}"),
        ("CONTROL_LOCKED", f"{framework} {clause} locked as COMPLIANT"),
        ("UNLOCK_REQUEST", f"Unlock requested on {framework} {clause}")]
    assert "please send" not in json.dumps([p["body"] for p in posts])  # message bodies never leave


def test_a_failing_webhook_never_breaks_the_action(client, bootstrap, upload, configured, monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(notify.requests, "post", boom)
    monkeypatch.setattr(notify, "_spawn", lambda work: work())
    org_id, _ = bootstrap(client)
    upload(client, org_id)
    owner = _user(client, org_id)
    admin = {"authorization": f"org:{org_id}"}
    task_id = client.get("/tasks", headers=admin).json()[0]["id"]
    resp = client.patch(f"/tasks/{task_id}", headers=admin, json={"owner_user_id": owner})
    assert resp.status_code == 200 and resp.json()["owner_user_id"] == owner
    assert notify._post({"kind": "x"}) is False


def test_a_rejecting_webhook_is_a_failure_not_a_delivery(configured, monkeypatch):
    class Rejected:
        status_code = 410
    monkeypatch.setattr(notify.requests, "post", lambda *a, **k: Rejected())
    assert notify._post({"kind": "x"}) is False


ITEM = {"kind": "EVIDENCE_EXPIRING", "severity": "medium", "at": "2026-11-02T00:00:00Z",
        "message": "policy.pdf: expires in 12 days", "link": "/evidence/e1"}


def test_the_digest_sends_each_item_once_until_the_resend_window_passes(client, bootstrap, posts, configured, monkeypatch):
    org_id, _ = bootstrap(client)
    with Session(db_module.engine) as s:
        assert notify.digest(s, org_id, [ITEM]) == 1
        assert notify.digest(s, org_id, [ITEM]) == 0  # already sent
        other = {**ITEM, "message": "policy.pdf: expires in 11 days"}
        assert notify.digest(s, org_id, [ITEM, other]) == 1  # only the new one
        row = s.query(NotificationLog).first()
        row.sent_at = datetime.utcnow() - timedelta(days=8)
        s.commit()
        assert notify.digest(s, org_id, [ITEM]) == 1  # past NOTIFY_RESEND_DAYS: remind again
    assert [p["body"]["kind"] for p in posts] == ["EVIDENCE_EXPIRING"] * 3


def test_a_failed_digest_send_is_retried_next_run(client, bootstrap, configured, monkeypatch):
    org_id, _ = bootstrap(client)
    monkeypatch.setattr(notify, "_post", lambda payload, *args, **kwargs: False)
    with Session(db_module.engine) as s:
        assert notify.digest(s, org_id, [ITEM]) == 0
        assert s.query(NotificationLog).count() == 0  # not recorded as sent
    assert notify.digest(None, org_id, []) == 0


def test_the_digest_does_nothing_when_unconfigured(client, bootstrap, posts):
    org_id, _ = bootstrap(client)
    with Session(db_module.engine) as s:
        assert notify.digest(s, org_id, [ITEM]) == 0 and s.query(NotificationLog).count() == 0
    assert posts == []


def test_the_monitor_flag_runs_the_digest_and_says_when_nothing_is_configured(client, bootstrap, upload, capsys, monkeypatch):
    from app import monitor
    org_id, _ = bootstrap(client)
    upload(client, org_id)
    monkeypatch.setattr("sys.argv", ["app.monitor", "--notify"])
    monitor._main()
    assert "webhook: not configured" in capsys.readouterr().out
