"""Connections (ADR-044), slice 1: an organisation's own chat webhook. The properties that matter: the secret is
write-only and stored only as ciphertext, only chat hosts are accepted, and an organisation's alerts reach only
its own channel."""

from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app import connections, notify
from app import db as db_module
from app.models import AuditEvent, Connection, Organization

H = lambda org: {"authorization": f"org:{org}"}  # noqa: E731
TOKEN = "AbCdEfGh1234_secretTOKENvalue-xyz"
HOOK = f"https://discord.com/api/webhooks/123456789012345678/{TOKEN}"
HOOK_B = "https://hooks.slack.com/services/T000/B000/XXXXsecretB"


@pytest.fixture()
def key(monkeypatch):
    k = Fernet.generate_key().decode()
    monkeypatch.setenv("CONNECTIONS_KEY", k)
    return k


@pytest.fixture()
def sent(monkeypatch):
    """Capture every outbound post, with a settable status; delivery runs inline."""
    class Calls(list):
        state = {"status": 204, "boom": None}

    calls = Calls()
    state = calls.state

    class Response:
        def __init__(self, code):
            self.status_code = code
            self.text = "response body that must never be stored"

    def fake_post(url, data=None, json=None, headers=None, timeout=None, allow_redirects=True):  # noqa: A002
        if state["boom"]:
            raise state["boom"]
        calls.append({"url": url, "data": data, "json": json, "headers": headers or {}, "timeout": timeout,
                      "allow_redirects": allow_redirects})
        return Response(state["status"])

    monkeypatch.setattr(connections.requests, "post", fake_post)
    monkeypatch.setattr(notify, "_spawn", lambda work: work())
    return calls


def _other_org(client):
    return client.post("/admin/organizations", json={"name": "Other", "frameworks": ["SOC-2"]}).json()["id"]


# --- what the server will agree to call --------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    HOOK, HOOK + "/", "https://ptb.discord.com/api/webhooks/1/abc-DEF_9", "https://discordapp.com/api/webhooks/1/abc",
    HOOK_B,
])
def test_real_chat_webhooks_are_accepted(url):
    assert connections.validate_chat_webhook(url).startswith("https://")


@pytest.mark.parametrize("url", [
    "http://discord.com/api/webhooks/1/abc",                       # not https
    "https://evil.com/api/webhooks/1/abc",                         # not a chat host
    "https://discord.com.evil.com/api/webhooks/1/abc",             # look-alike host
    "https://discord.com@evil.com/api/webhooks/1/abc",             # userinfo trick: the real host is evil.com
    "https://169.254.169.254/latest/meta-data/",                   # cloud metadata
    "https://localhost/api/webhooks/1/abc", "https://127.0.0.1/api/webhooks/1/abc",
    "https://discord.com:8443/api/webhooks/1/abc",                 # unusual port
    "https://discord.com/api/webhooks/1/abc?x=1", "https://discord.com/api/webhooks/1/abc#frag",
    "https://discord.com/not/a/webhook", "https://hooks.slack.com/api/webhooks/1/abc",
    "ftp://discord.com/api/webhooks/1/abc", "discord.com/api/webhooks/1/abc", "",
])
def test_anything_else_is_refused(url):
    with pytest.raises(ValueError):
        connections.validate_chat_webhook(url)


def test_a_refusal_never_echoes_the_address():
    with pytest.raises(ValueError) as exc:
        connections.validate_chat_webhook("https://evil.com/api/webhooks/1/" + TOKEN)
    assert TOKEN not in str(exc.value)


# --- the secret ----------------------------------------------------------------------------------------------------

def test_without_a_key_nothing_is_stored(client, bootstrap, monkeypatch):
    monkeypatch.delenv("CONNECTIONS_KEY", raising=False)
    org, _ = bootstrap(client)
    state = client.get("/connections", headers=H(org)).json()
    assert state["key_configured"] is False and state["connections"][0]["configured"] is False
    r = client.put("/connections/chat-webhook", json={"url": HOOK}, headers=H(org))
    assert r.status_code == 503 and TOKEN not in r.text
    with Session(db_module.engine) as s:
        assert s.query(Connection).count() == 0


def test_the_secret_is_stored_only_as_ciphertext_and_never_returned(client, bootstrap, key, db):
    org, _ = bootstrap(client)
    put = client.put("/connections/chat-webhook", json={"url": HOOK}, headers=H(org))
    assert put.status_code == 200
    row = db.query(Connection).one()
    assert TOKEN not in row.config_encrypted and HOOK not in row.config_encrypted
    assert connections.decrypt(row.config_encrypted) == HOOK

    for response in (put, client.get("/connections", headers=H(org))):
        assert TOKEN not in response.text and "discord.com/api" not in response.text
    view = client.get("/connections", headers=H(org)).json()["connections"][0]
    assert view["configured"] is True and view["status"] == "UNTESTED" and view["hint"].startswith("discord.com ...")
    assert not any(TOKEN in json.dumps(e.detail, default=str) for e in db.query(AuditEvent).all())


def test_a_wrong_address_is_refused_with_a_clear_message(client, bootstrap, key):
    org, _ = bootstrap(client)
    r = client.put("/connections/chat-webhook", json={"url": "https://evil.com/api/webhooks/1/" + TOKEN}, headers=H(org))
    assert r.status_code == 422 and "Discord and Slack" in r.json()["detail"] and TOKEN not in r.text


def test_replacing_resets_the_test_and_never_duplicates(client, bootstrap, key, sent, db):
    org, _ = bootstrap(client)
    client.put("/connections/chat-webhook", json={"url": HOOK}, headers=H(org))
    assert client.post("/connections/chat-webhook/test", headers=H(org)).json()["connections"][0]["status"] == "OK"
    again = client.put("/connections/chat-webhook", json={"url": HOOK_B}, headers=H(org)).json()["connections"][0]
    assert again["status"] == "UNTESTED" and again["last_tested_at"] is None and again["hint"].startswith("hooks.slack.com")
    assert db.query(Connection).count() == 1
    assert db.query(AuditEvent).filter_by(action="CONNECTION_SET").count() == 2


def test_a_key_can_be_rotated_without_losing_saved_connections(monkeypatch):
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setenv("CONNECTIONS_KEY", old)
    token = connections.encrypt(HOOK)
    monkeypatch.setenv("CONNECTIONS_KEY", f"{new},{old}")           # new key first, old still readable
    assert connections.decrypt(token) == HOOK
    monkeypatch.setenv("CONNECTIONS_KEY", new)                      # the old one retired: now unreadable
    with pytest.raises(ValueError) as exc:
        connections.decrypt(token)
    assert HOOK not in str(exc.value) and TOKEN not in str(exc.value)


# --- the test button ----------------------------------------------------------------------------------------------

def test_the_test_button_records_ok_or_the_reason(client, bootstrap, key, sent, db):
    org, _ = bootstrap(client)
    client.put("/connections/chat-webhook", json={"url": HOOK}, headers=H(org))

    ok = client.post("/connections/chat-webhook/test", headers=H(org)).json()["connections"][0]
    assert ok["status"] == "OK" and ok["last_error"] == "" and ok["last_tested_at"]
    call = sent[-1]
    assert call["url"] == HOOK and call["allow_redirects"] is False and call["timeout"] <= 10  # never follows a redirect

    sent.state["status"] = 404
    bad = client.post("/connections/chat-webhook/test", headers=H(org)).json()["connections"][0]
    assert bad["status"] == "FAILED" and "404" in bad["last_error"]
    assert "response body" not in bad["last_error"]

    sent.state["boom"] = ConnectionError(f"could not reach {HOOK}")
    down = client.post("/connections/chat-webhook/test", headers=H(org)).json()["connections"][0]
    assert down["status"] == "FAILED" and "ConnectionError" in down["last_error"] and TOKEN not in down["last_error"]
    events = db.query(AuditEvent).filter_by(action="CONNECTION_TESTED").all()
    assert [e.detail["ok"] for e in events] == [True, False, False]
    assert not any(TOKEN in json.dumps(e.detail, default=str) for e in events)


def test_testing_a_missing_connection_is_a_404(client, bootstrap, key):
    org, _ = bootstrap(client)
    assert client.post("/connections/chat-webhook/test", headers=H(org)).status_code == 404


# --- who may, and whose --------------------------------------------------------------------------------------------

def test_only_an_organisation_admin_may_touch_connections(client, bootstrap, key):
    org, _ = bootstrap(client)
    mk = lambda email, role: {"authorization": "user:" + client.post("/admin/users", json={  # noqa: E731
        "email": email, "org_id": org, "role": role}).json()["id"]}
    for who in (mk("o@a.test", "CONTROL_OWNER"), mk("v@a.test", "COMPLIANCE_VIEWER")):
        assert client.get("/connections", headers=who).status_code == 403
        assert client.put("/connections/chat-webhook", json={"url": HOOK}, headers=who).status_code == 403
        assert client.delete("/connections/chat-webhook", headers=who).status_code == 403
        assert client.post("/connections/chat-webhook/test", headers=who).status_code == 403


def test_each_organisation_sees_only_its_own_connection(client, bootstrap, key):
    a, _ = bootstrap(client)
    b = _other_org(client)
    client.put("/connections/chat-webhook", json={"url": HOOK}, headers=H(a))
    assert client.get("/connections", headers=H(a)).json()["connections"][0]["configured"] is True
    assert client.get("/connections", headers=H(b)).json()["connections"][0]["configured"] is False
    assert client.post("/connections/chat-webhook/test", headers=H(b)).status_code == 404


def test_removing_a_connection_is_audited_and_ends_delivery(client, bootstrap, key, sent, db, monkeypatch):
    monkeypatch.delenv("NOTIFY_WEBHOOK_URL", raising=False)
    org, _ = bootstrap(client)
    client.put("/connections/chat-webhook", json={"url": HOOK}, headers=H(org))
    notify.event("TASK_ASSIGNED", "info", "a task was assigned", "/tasks", org)
    assert [c["url"] for c in sent] == [HOOK]

    gone = client.delete("/connections/chat-webhook", headers=H(org)).json()["connections"][0]
    assert gone["configured"] is False and db.query(AuditEvent).filter_by(action="CONNECTION_REMOVED").count() == 1
    notify.event("TASK_ASSIGNED", "info", "another task was assigned", "/tasks", org)
    assert len(sent) == 1  # nowhere to send now


# --- delivery goes to the organisation's own channel -------------------------------------------------------------

def test_an_organisations_alert_goes_to_its_own_channel_unsigned(client, bootstrap, key, sent, monkeypatch):
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://hooks.example.test/operator")
    monkeypatch.setenv("NOTIFY_WEBHOOK_SECRET", "operator-signing-secret")
    a, _ = bootstrap(client)
    b = _other_org(client)
    client.put("/connections/chat-webhook", json={"url": HOOK}, headers=H(a))

    notify.event("TASK_ASSIGNED", "info", "task for A", "/tasks", a)
    notify.event("TASK_ASSIGNED", "info", "task for B", "/tasks", b)

    to_a, to_b = sent[0], sent[1]
    assert to_a["url"] == HOOK and "X-GRC-Signature" not in to_a["headers"]            # own channel, no operator secret
    assert to_b["url"] == "https://hooks.example.test/operator" and "X-GRC-Signature" in to_b["headers"]  # legacy path intact
    assert HOOK not in json.dumps(to_b, default=str)                                    # A's address never reaches B's call


def test_an_unreadable_connection_never_falls_back_to_the_shared_channel(client, bootstrap, key, sent, monkeypatch):
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://hooks.example.test/operator")
    org, _ = bootstrap(client)
    client.put("/connections/chat-webhook", json={"url": HOOK}, headers=H(org))
    monkeypatch.setenv("CONNECTIONS_KEY", Fernet.generate_key().decode())               # the key was replaced

    notify.event("TASK_ASSIGNED", "info", "task", "/tasks", org)
    assert sent == []                                                                    # not the operator's channel either
    bad = client.post("/connections/chat-webhook/test", headers=H(org)).json()["connections"][0]
    assert bad["status"] == "FAILED" and "paste it again" in bad["last_error"] and TOKEN not in bad["last_error"]


def test_the_weekly_digest_uses_the_organisations_own_connection(client, bootstrap, key, sent, monkeypatch):
    monkeypatch.delenv("NOTIFY_WEBHOOK_URL", raising=False)
    org, _ = bootstrap(client)
    client.put("/connections/chat-webhook", json={"url": HOOK}, headers=H(org))
    item = {"kind": "weekly_report", "severity": "info", "message": "Weekly compliance report for Acme", "link": "/overview"}
    with Session(db_module.engine) as s:
        assert notify.digest(s, org, [item]) == 1
    assert [c["url"] for c in sent] == [HOOK]


def test_the_report_card_knows_a_connection_counts_as_delivery(client, bootstrap, key, monkeypatch):
    monkeypatch.delenv("NOTIFY_WEBHOOK_URL", raising=False)
    org, _ = bootstrap(client)
    assert client.get("/reports/weekly", headers=H(org)).json()["delivery"]["webhook_configured"] is False
    client.put("/connections/chat-webhook", json={"url": HOOK}, headers=H(org))
    assert client.get("/reports/weekly", headers=H(org)).json()["delivery"]["webhook_configured"] is True
