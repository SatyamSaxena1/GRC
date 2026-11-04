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
