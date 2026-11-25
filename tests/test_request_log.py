"""Durable request log (ADR-070): what lands in a row, that a broken database never fails a request, and retention."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select

from app import db as db_module
from app import request_log
from app.models import RequestLog
from app.routers import templates

KEY = "operator-key-for-tests"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    request_log._buffer.clear()
    request_log._skipped.update(health=0, csp_report=0)
    request_log._warned = False
    monkeypatch.setenv("ADMIN_API_KEY", KEY)
    yield
    request_log._buffer.clear()


def _rows(db):
    return db.execute(select(RequestLog).order_by(RequestLog.id)).scalars().all()


def test_a_request_writes_one_row_without_query_string_or_body(client, db):
    secret = "hunter2-token"
    r = client.post("/public/demo?email=jane@corp.test&token=" + secret, content=b'{"password":"' + secret.encode() + b'"}',
                    headers={"authorization": "Bearer " + secret, "x-request-id": "jane@corp.test"})
    request_log.flush()
    (row,) = _rows(db)
    assert (row.method, row.path, row.auth) == ("POST", "/public/demo", "present")
    assert row.status == r.status_code and row.duration_ms >= 0 and row.ip
    assert row.request_id == "invalid"             # a caller-supplied id that is not a plain token is not stored
    dump = repr([getattr(row, c.name) for c in RequestLog.__table__.columns])
    for forbidden in (secret, "jane", "corp.test", "email=", "password"):
        assert forbidden not in dump


def test_a_good_request_id_org_and_auth_kinds_are_kept(client, db):
    org = client.post("/admin/organizations", headers={"x-admin-key": KEY},
                      json={"name": "Acme", "frameworks": ["ISO-27001"]}).json()["id"]
    client.get("/templates", headers={"authorization": f"org:{org}", "x-request-id": "req-123"})
    client.get("/templates")
    client.get("/templates", headers={"authorization": "demo"})
    request_log.flush()
    rows = _rows(db)
    assert [r.auth for r in rows] == ["operator", "present", "none", "demo"]
    assert rows[1].request_id == "req-123" and rows[1].org_id == org and rows[2].org_id is None


def test_an_email_in_a_path_is_not_stored(client, db):
    client.get("/anything/jane@corp.test/x")
    request_log.flush()
    assert _rows(db)[0].path == "/anything/{redacted}/x"


def test_health_checks_and_csp_reports_are_counted_not_stored(client, db):
    for _ in range(3):
        client.get("/health/live")
    client.post("/csp-report", json={"csp-report": {}})
    request_log.flush()
    assert _rows(db) == []
    assert request_log._skipped == {"health": 3, "csp_report": 1}


def test_a_failing_database_never_fails_a_request_and_warns_once(client, caplog, monkeypatch):
    monkeypatch.setattr(db_module, "engine", create_engine("sqlite:////no/such/dir/x.db"))
    with caplog.at_level(logging.WARNING, logger="app.request_log"):
        for _ in range(3):
            assert client.get("/public/demo").status_code == 200
            assert request_log.flush() == 0
    assert len([r for r in caplog.records if r.name == "app.request_log"]) == 1
    assert len(request_log._buffer) == 3            # kept for the next try, not lost


def test_the_buffer_is_capped_when_the_database_stays_away(monkeypatch):
    monkeypatch.setattr(request_log, "_buffer", request_log.deque(maxlen=5))
    for i in range(20):
        request_log._buffer.append({"i": i})
    assert [r["i"] for r in request_log._buffer] == [15, 16, 17, 18, 19]


def test_rows_older_than_365_days_are_pruned_and_newer_ones_are_not(client, db):
    now = datetime.now(timezone.utc)
    for days in (400, 366, 364, 1):
        db.add(RequestLog(ts=now - timedelta(days=days), method="GET", path=f"/d{days}", status=200, auth="none"))
    db.commit()
    assert request_log.prune() == 2
    assert [r.path for r in _rows(db)] == ["/d364", "/d1"]


def test_retention_never_drops_below_365_unless_explicitly_allowed(monkeypatch, caplog):
    monkeypatch.setenv("LOG_RETENTION_DAYS", "30")
    assert request_log.retention_days() == 365
    monkeypatch.setenv("LOG_RETENTION_ALLOW_SHORT", "1")
    with caplog.at_level(logging.WARNING, logger="app.request_log"):
        assert request_log.retention_days() == 30
    assert "below the 365" in caplog.text
    monkeypatch.setenv("LOG_RETENTION_DAYS", "800")
    monkeypatch.delenv("LOG_RETENTION_ALLOW_SHORT")
    assert request_log.retention_days() == 800


def test_the_operator_endpoint_refuses_a_wrong_key_and_a_tenant_caller(client, db):
    org = client.post("/admin/organizations", headers={"x-admin-key": KEY},
                      json={"name": "Acme", "frameworks": ["ISO-27001"]}).json()["id"]
    client.get("/templates", headers={"authorization": f"org:{org}"})
    request_log.flush()
    assert client.get("/admin/request-logs").status_code == 401
    assert client.get("/admin/request-logs", headers={"x-admin-key": "wrong"}).status_code == 401
    assert client.get("/admin/request-logs", headers={"authorization": f"org:{org}"}).status_code == 401
    ok = client.get("/admin/request-logs", headers={"x-admin-key": KEY})
    assert ok.status_code == 200
    body = ok.json()
    assert body["retention_days"] == 365 and {"path", "status", "auth", "ip"} <= set(body["rows"][0])
    assert client.get("/admin/request-logs?status=404", headers={"x-admin-key": KEY}).json()["rows"] == []


def test_the_operator_endpoint_is_locked_out_after_repeated_wrong_keys(client):
    from app import auth
    auth._admin_fails.clear()
    codes = [client.get("/admin/request-logs", headers={"x-admin-key": "bad"}).status_code for _ in range(12)]
    auth._admin_fails.clear()
    assert codes[0] == 401 and codes[-1] == 429


def test_the_logging_policy_states_the_strictest_retention_from_the_packs():
    body, stated = templates.render("logging-and-monitoring")
    assert stated == {"log_retention_days": templates.strictest("log_retention_days")} and stated["log_retention_days"] >= 365
    assert f"at least {stated['log_retention_days']} days" in body
