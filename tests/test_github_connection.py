"""Connections slice 2 (ADR-045): an organisation connects its own GitHub token and repositories. The token is
write-only, sees only api.github.com, and a sync uses the organisation's own token, never another's."""

from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import connections
from app import db as db_module
from app.models import AuditEvent, Connection, Organization
from app.routers import connectors

H = lambda org: {"authorization": f"org:{org}"}  # noqa: E731
TOKEN = "ghp_AbCdEfGh1234secretTOKENvalue"
BODY = {"token": TOKEN, "repos": ["acme/api", "acme/web"]}


@pytest.fixture()
def key(monkeypatch):
    monkeypatch.setenv("CONNECTIONS_KEY", Fernet.generate_key().decode())


def _org(client, bootstrap):
    return bootstrap(client)[0]


def _put(client, org, body=BODY):
    return client.put("/connections/github", json=body, headers=H(org))


# --- validation ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("token,repos", [
    ("short", ["a/b"]), ("ghp_has space in it 12345678901", ["a/b"]), (TOKEN, []), (TOKEN, ["justaname"]),
    (TOKEN, ["https://evil.test/a/b"]), (TOKEN, ["a/b/c"]), (TOKEN, [f"o{i}/r" for i in range(11)]),
])
def test_bad_input_is_refused_without_echoing_the_token(token, repos):
    with pytest.raises(ValueError) as e:
        connections.validate_github(token, repos)
    assert token not in str(e.value)


def test_duplicates_are_collapsed():
    assert connections.validate_github(f" {TOKEN} ", ["a/b", "a/b", " c/d "]) == (TOKEN, ["a/b", "c/d"])


# --- the page's API -----------------------------------------------------------------------------------------------
def test_saving_is_write_only_and_stored_only_as_ciphertext(client, bootstrap, key):
    org = _org(client, bootstrap)
    r = _put(client, org)
    assert r.status_code == 200
    mine = [c for c in r.json()["connections"] if c["kind"] == "GITHUB_CHANGE_CONTROL"][0]
    assert mine["configured"] and mine["status"] == "UNTESTED"
    assert TOKEN not in r.text and TOKEN not in client.get("/connections", headers=H(org)).text
    with Session(db_module.engine) as s:
        row = s.query(Connection).filter_by(org_id=org, kind="GITHUB_CHANGE_CONTROL").one()
        assert TOKEN not in row.config_encrypted and TOKEN not in row.hint
        events = json.dumps([e.detail for e in s.query(AuditEvent).filter_by(action="CONNECTION_SET")], default=str)
        assert TOKEN not in events and "acme/api" in events      # repository names are not secret; the token is


def test_the_feature_is_off_without_a_key(client, bootstrap, monkeypatch):
    monkeypatch.delenv("CONNECTIONS_KEY", raising=False)
    assert _put(client, _org(client, bootstrap)).status_code == 503


def test_test_button_reports_each_failure_without_leaking(client, bootstrap, key, monkeypatch):
    org = _org(client, bootstrap)
    _put(client, org)
    seen = []

    class R:
        def __init__(self, code):
            self.status_code = code

    codes = iter([200, 404, 401])

    def fake_get(self, url, timeout=None, allow_redirects=True, **kw):
        seen.append((url, self.headers.get("Authorization"), allow_redirects))
        return R(next(codes))

    monkeypatch.setattr(connections.requests.Session, "get", fake_get)
    one = client.post("/connections/github/test", headers=H(org)).json()["connections"][1]
    assert one["status"] == "FAILED" and "acme/web" in one["last_error"] and TOKEN not in json.dumps(one)
    assert all(u.startswith("https://api.github.com/repos/") and not redir for u, _, redir in seen)
    codes2 = iter([401])
    monkeypatch.setattr(connections.requests.Session, "get", lambda s, u, **k: R(next(codes2)))
    assert "rejected" in client.post("/connections/github/test", headers=H(org)).json()["connections"][1]["last_error"]


def test_only_org_admins_and_each_org_sees_only_its_own(client, bootstrap, key):
    org = _org(client, bootstrap)
    other = client.post("/admin/organizations", json={"name": "Other", "frameworks": ["SOC-2"]}).json()["id"]
    _put(client, org)
    assert client.get("/connections", headers=H(other)).json()["connections"][1]["configured"] is False
    assert client.put("/connections/github", json=BODY, headers={"authorization": "user:nobody"}).status_code in (401, 403)


def test_removing_deletes_the_row_and_is_audited(client, bootstrap, key):
    org = _org(client, bootstrap)
    _put(client, org)
    assert client.delete("/connections/github", headers=H(org)).json()["connections"][1]["configured"] is False
    with Session(db_module.engine) as s:
        assert s.query(Connection).filter_by(kind="GITHUB_CHANGE_CONTROL").count() == 0
        assert s.query(AuditEvent).filter_by(action="CONNECTION_REMOVED").count() == 1


# --- the sync uses the organisation's own token ---------------------------------------------------------------------
def test_a_sync_runs_the_collector_with_the_orgs_own_token_and_repos(client, bootstrap, key, monkeypatch):
    org = _org(client, bootstrap)
    _put(client, org)
    monkeypatch.delenv("DPDP_GITHUB_COLLECTOR_URL", raising=False)
    calls = []
    monkeypatch.setattr(connectors.github_change_control, "fetch",
                        lambda session, repo, since, envs, jobs: calls.append((repo, session.headers["Authorization"])) or {})
    monkeypatch.setattr(connectors.github_change_control, "summarize", lambda repos: {"merges_in_period": 3})
    monkeypatch.setattr(connectors.github_change_control, "exceptions", lambda repos: ([], 0))
    with Session(db_module.engine) as s:
        payload = connectors._pull("github", s, org)
    assert [c[0] for c in calls] == ["acme/api", "acme/web"]
    assert all(c[1] == f"Bearer {TOKEN}" for c in calls)
    assert payload["source"] == "github" and "attributes" in payload


def test_without_a_connection_or_collector_url_github_is_not_configured(client, bootstrap, key, monkeypatch):
    org = _org(client, bootstrap)
    monkeypatch.delenv("DPDP_GITHUB_COLLECTOR_URL", raising=False)
    with Session(db_module.engine) as s, pytest.raises(HTTPException) as e:
        connectors._pull("github", s, org)
    assert e.value.status_code == 409


def test_an_unreadable_connection_fails_closed_and_never_uses_the_shared_collector(client, bootstrap, key, monkeypatch):
    org = _org(client, bootstrap)
    _put(client, org)
    monkeypatch.setenv("CONNECTIONS_KEY", Fernet.generate_key().decode())    # the key was replaced
    monkeypatch.setenv("DPDP_GITHUB_COLLECTOR_URL", "http://127.0.0.1:9/should-not-be-called")
    with Session(db_module.engine) as s, pytest.raises(HTTPException) as e:
        connectors._pull("github", s, org)
    assert e.value.status_code == 502 and "unreadable" in e.value.detail


def test_a_collector_crash_reports_the_class_only(client, bootstrap, key, monkeypatch):
    org = _org(client, bootstrap)
    _put(client, org)

    def boom(*a, **k):
        raise RuntimeError(f"leaky {TOKEN}")

    monkeypatch.setattr(connectors.github_change_control, "fetch", boom)
    with Session(db_module.engine) as s, pytest.raises(HTTPException) as e:
        connectors._pull("github", s, org)
    assert TOKEN not in e.value.detail and "RuntimeError" in e.value.detail


def test_a_github_sync_with_an_own_connection_returns_at_once_and_runs_in_the_background(client, bootstrap, key, monkeypatch):
    org = _org(client, bootstrap)
    _put(client, org)
    ran = []
    monkeypatch.setattr(connectors, "_sync_in_background", lambda *a: ran.append(a))
    monkeypatch.setattr(connectors, "sync_connector_for_org",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run in the request")))
    r = client.post("/connectors/github/sync", headers=H(org))
    assert r.status_code == 202 and r.json()["status"] == "RUNNING" and r.json()["evidence_id"] is None
    assert len(ran) == 1 and ran[0][0] == org and ran[0][3] == "github"


def test_the_background_run_stores_evidence_and_records_failure_without_raising(client, bootstrap, key, monkeypatch):
    from app.models import CollectionRun, Evidence
    org = _org(client, bootstrap)
    _put(client, org)
    monkeypatch.delenv("DPDP_GITHUB_COLLECTOR_URL", raising=False)
    fetch = lambda session, repo, since, envs, jobs: {}  # noqa: E731
    monkeypatch.setattr(connectors.github_change_control, "fetch", fetch)
    monkeypatch.setattr(connectors.github_change_control, "summarize", lambda repos: {"merges_in_period": 3})
    monkeypatch.setattr(connectors.github_change_control, "exceptions", lambda repos: ([], 0))
    connectors._sync_in_background(org, "user:test", "", "github")
    with Session(db_module.engine) as s:
        assert s.query(Evidence).filter_by(org_id=org, original_filename="connector-github.json").count() == 1

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(connectors.github_change_control, "fetch", boom)
    connectors._sync_in_background(org, "user:test", "", "github")          # must not raise
    with Session(db_module.engine) as s:
        assert s.query(CollectionRun).filter_by(org_id=org, source="github", status="FAILED").count() == 1


# --- accepting a smaller repository scope (ADR-046) -------------------------------------------------------------------
def _runs(org, source="github"):
    from app.models import CollectionRun
    with Session(db_module.engine) as s:
        return s.query(CollectionRun).filter_by(org_id=org, source=source).order_by(CollectionRun.started_at).all()


def _seed_runs(org, signals):
    from datetime import datetime, timedelta
    from app.models import CollectionRun
    t = datetime(2026, 11, 3)
    with Session(db_module.engine) as s:
        s.add(CollectionRun(org_id=org, source="github", started_at=t, status="COMPLETE", expectation="NONE",
                            returned={"repositories_in_scope": 3, "merges_in_period": 42, "attributes": ["a"]}, signals=[]))
        s.add(CollectionRun(org_id=org, source="github", started_at=t + timedelta(days=1), status="PARTIAL",
                            expectation="HISTORY", returned={"repositories_in_scope": 1, "merges_in_period": 78,
                                                             "attributes": ["a"]}, signals=signals))
        s.commit()


WHY = "only the GRC repository is in scope for this audit period"


def test_a_scope_only_partial_can_be_accepted_by_an_org_admin_and_becomes_the_baseline(client, bootstrap):
    org = _org(client, bootstrap)
    _seed_runs(org, ["repositories in scope fell from 3 to 1"])
    r = client.post("/connectors/github/accept-scope", json={"reason": WHY}, headers=H(org))
    assert r.status_code == 200
    runs = _runs(org)
    assert [x.status for x in runs] == ["COMPLETE", "PARTIAL", "COMPLETE"]       # inserted, nothing edited
    assert runs[-1].returned["repositories_in_scope"] == 1 and WHY in runs[-1].signals[0]
    from app.routers import connectors
    with Session(db_module.engine) as s:
        assert connectors._last_run(s, org, "github", "COMPLETE").id == runs[-1].id   # the next baseline
        assert s.query(AuditEvent).filter_by(action="CONNECTOR_SCOPE_ACCEPTED").count() == 1


def test_a_run_the_collector_itself_flagged_cannot_be_accepted(client, bootstrap):
    org = _org(client, bootstrap)
    _seed_runs(org, ["repositories in scope fell from 3 to 1", "the collector hit a rate limit"])
    assert client.post("/connectors/github/accept-scope", json={"reason": WHY}, headers=H(org)).status_code == 409
    assert [x.status for x in _runs(org)] == ["COMPLETE", "PARTIAL"]


def test_acceptance_needs_a_reason_an_admin_and_a_partial_run(client, bootstrap):
    org = _org(client, bootstrap)
    assert client.post("/connectors/github/accept-scope", json={"reason": WHY}, headers=H(org)).status_code == 409
    _seed_runs(org, ["repositories in scope fell from 3 to 1"])
    assert client.post("/connectors/github/accept-scope", json={"reason": "ok fine"}, headers=H(org)).status_code == 422
    assert client.post("/connectors/aws/accept-scope", json={"reason": WHY}, headers=H(org)).status_code == 404
    assert client.post("/connectors/github/accept-scope", json={"reason": WHY},
                       headers={"authorization": "user:nobody"}).status_code in (401, 403)


# --- a flaky GitHub answer must not kill a long collection -------------------------------------------------------
def test_the_github_session_retries_transient_errors_and_then_gives_up_cleanly():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    hits = {"n": 0, "fail": 2}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            hits["n"] += 1
            code = 502 if hits["n"] <= hits["fail"] else 200
            self.send_response(code)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        s = connections.github_session("ghp_AbCdEfGh1234secretTOKENvalue")
        assert s.get_adapter("https://api.github.com/").max_retries.status_forcelist == (500, 502, 503, 504)
        fast = connections.requests.adapters.HTTPAdapter(max_retries=connections.retrying_adapter().max_retries.new(backoff_factor=0))
        s.mount("http://", fast)
        assert s.get(f"http://127.0.0.1:{srv.server_port}/x", timeout=5).status_code == 200   # 2 x 502, then OK
        assert hits["n"] == 3
        hits.update(n=0, fail=99)                                                              # never recovers
        assert s.get(f"http://127.0.0.1:{srv.server_port}/x", timeout=5).status_code == 502   # returned, not raised
        assert hits["n"] == 5                                                                  # 1 try + 4 retries
    finally:
        srv.shutdown()
