"""Microsoft 365 by upload (ADR-050): the same token and ingest as AWS, with Microsoft's two attributes and a read-only
Graph script. A check that cannot run is left out and reported, never a pass or a failure."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app import connections
from app import db as db_module
from app.collectors import m365_readonly
from app.models import AuditEvent, Connection

H = lambda org: {"authorization": f"org:{org}"}  # noqa: E731


@pytest.fixture()
def key(monkeypatch):
    monkeypatch.setenv("CONNECTIONS_KEY", Fernet.generate_key().decode())


def _org(client, bootstrap):
    return bootstrap(client)[0]


# --- the page's contract with the API: the kinds, in order ---------------------------------------------------------
def test_the_connections_list_starts_with_the_four_kinds_the_page_first_had(client, bootstrap, key):
    kinds = [c["kind"] for c in client.get("/connections", headers=H(_org(client, bootstrap))).json()["connections"]]
    assert kinds[:4] == ["CHAT_WEBHOOK", "GITHUB_CHANGE_CONTROL", "AWS_PUSH", "M365_PUSH"]


# --- the two Graph checks --------------------------------------------------------------------------------------------
def graph(admins=None, audits=None, fail=None):
    """A stand-in for Graph. `fail` maps a URL fragment to an exception."""
    def get(url):
        for frag, exc in (fail or {}).items():
            if frag in url:
                raise exc
        if "userRegistrationDetails" in url:
            rows = [{"isMfaRegistered": True}] if admins is None else admins
            return {"value": rows}
        if "directoryAudits" in url:
            return {"value": [{"id": "1"}] if audits is None else audits}
        raise AssertionError(url)
    return get


class Denied(Exception):
    code = "HTTP 403"


def test_a_healthy_tenant_passes_both_and_is_complete():
    out = m365_readonly.collect(graph())
    assert out["attributes"] == {"privileged_access_mfa": True, "access_logging_enabled": True}
    assert out["collection"]["complete"] is True


def test_an_admin_without_mfa_fails_only_the_mfa_check():
    out = m365_readonly.collect(graph(admins=[{"isMfaRegistered": True}, {"isMfaRegistered": False}]))
    assert out["attributes"] == {"privileged_access_mfa": False, "access_logging_enabled": True}


def test_no_recent_audit_events_fails_only_the_logging_check():
    assert m365_readonly.collect(graph(audits=[]))["attributes"]["access_logging_enabled"] is False


def test_pages_are_followed():
    pages = {"a": {"value": [{"isMfaRegistered": True}], "@odata.nextLink": "b"}, "b": {"value": [{"isMfaRegistered": False}]}}
    calls = []

    def get(url):
        calls.append(url)
        if "userRegistrationDetails" in url:
            return pages["a"]
        if url == "b":
            return pages["b"]
        return {"value": [{"id": "1"}]}

    assert m365_readonly.collect(get)["attributes"]["privileged_access_mfa"] is False and "b" in calls


def test_a_missing_permission_or_no_admins_returned_is_left_out_never_read_as_a_pass_or_failure():
    out = m365_readonly.collect(graph(fail={"directoryAudits": Denied()}))
    assert "access_logging_enabled" not in out["attributes"] and out["collection"]["complete"] is False
    assert any("access_logging_enabled" in e and "HTTP 403" in e for e in out["collection"]["errors"])
    none = m365_readonly.collect(graph(admins=[]))
    assert "privileged_access_mfa" not in none["attributes"] and none["collection"]["complete"] is False


# --- the same token and ingest, for Microsoft 365 -----------------------------------------------------------------
GOOD = {"attributes": {"privileged_access_mfa": True, "access_logging_enabled": False},
        "collection": {"complete": True, "errors": [], "region": "m365"}}


def _token(client, org, source="m365"):
    r = client.post(f"/connections/{source}/token", headers=H(org))
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    return r.json()["new_token"]


def _push(client, token, source="m365", body=GOOD):
    return client.post(f"/ingest/{source}", json=body, headers={"authorization": f"Bearer {token}"})


def test_an_upload_is_stored_as_microsoft_365_evidence(client, bootstrap, key):
    org = _org(client, bootstrap)
    token = _token(client, org)
    assert _push(client, token).status_code == 202
    from app.models import Evidence
    with Session(db_module.engine) as s:
        ev = s.query(Evidence).filter_by(org_id=org, artefact_type="M365_SNAPSHOT").one()
        assert ev.uploaded_by == "upload:m365"
        assert s.query(Connection).filter_by(org_id=org, kind="M365_PUSH").one().status == "OK"


def test_the_token_is_shown_once_and_never_stored(client, bootstrap, key):
    org = _org(client, bootstrap)
    secret = _token(client, org).split(".", 1)[1]
    assert secret not in client.get("/connections", headers=H(org)).text
    with Session(db_module.engine) as s:
        row = s.query(Connection).filter_by(org_id=org, kind="M365_PUSH").one()
        assert secret not in row.config_encrypted and secret not in row.hint
        assert secret not in json.dumps([e.detail for e in s.query(AuditEvent)], default=str)


def test_a_token_for_one_source_never_works_for_another(client, bootstrap, key):
    org = _org(client, bootstrap)
    aws_token, m365_token = _token(client, org, "aws"), _token(client, org, "m365")
    aws_body = {"attributes": {"backup_enabled": True}}
    assert _push(client, m365_token, "aws", aws_body).status_code == 401
    assert _push(client, aws_token, "m365").status_code == 401
    assert _push(client, aws_token, "aws", aws_body).status_code == 202


def test_each_source_accepts_only_its_own_attributes(client, bootstrap, key):
    org = _org(client, bootstrap)
    token = _token(client, org)
    assert _push(client, token, body={"attributes": {"backup_enabled": True}}).status_code == 422   # an AWS attribute
    assert _push(client, token, body={"attributes": {"privileged_access_mfa": "yes"}}).status_code == 422


def test_unknown_sources_and_non_upload_sources_are_refused(client, bootstrap, key):
    org = _org(client, bootstrap)
    assert client.post("/connections/okta/token", headers=H(org)).status_code == 404
    assert client.post("/ingest/okta", json=GOOD, headers={"authorization": "Bearer a.bbbbbbbbbbbbbbbbbbbbbbbb"}).status_code == 404


def test_the_collect_button_explains_that_results_arrive_from_the_script(client, bootstrap, key, monkeypatch):
    org = _org(client, bootstrap)
    monkeypatch.delenv("DPDP_M365_COLLECTOR_URL", raising=False)
    _token(client, org)
    r = client.post("/connectors/m365/sync", headers=H(org))
    assert r.status_code == 409 and "own script" in r.json()["detail"]


def test_removing_ends_the_token(client, bootstrap, key):
    org = _org(client, bootstrap)
    token = _token(client, org)
    assert client.delete("/connections/m365", headers=H(org)).json()["connections"][3]["configured"] is False
    assert _push(client, token).status_code == 401


def test_the_script_dry_run_prints_the_answers_and_uploads_nothing(monkeypatch, capsys):
    monkeypatch.setenv("GRAPH_ACCESS_TOKEN", "x")
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no network")))
    monkeypatch.setattr(m365_readonly, "collect", lambda get: {"attributes": {"privileged_access_mfa": True},
                                                               "collection": {"complete": True, "errors": [], "region": "m365"}})
    assert m365_readonly.main(["--url", "https://example.test", "--dry-run"]) == 0
    assert '"privileged_access_mfa": true' in capsys.readouterr().out
