"""Google Workspace by upload (ADR-055): the same token and ingest as Microsoft 365, with Google's two attributes and a
read-only Admin SDK script. A check that cannot run is left out and reported, never a pass or a failure."""

from __future__ import annotations

import io
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app import db as db_module
from app.collectors import gworkspace_readonly as gw
from app.models import Connection, Evidence

H = lambda org: {"authorization": f"org:{org}"}  # noqa: E731
SRC = "google-workspace"


@pytest.fixture()
def key(monkeypatch):
    monkeypatch.setenv("CONNECTIONS_KEY", Fernet.generate_key().decode())


# --- the two Admin SDK checks ------------------------------------------------------------------------------------
def google(users=None, items=None, fail=None):
    """A stand-in for the Admin SDK. `fail` maps a URL fragment to an exception."""
    def get(url):
        for frag, exc in (fail or {}).items():
            if frag in url:
                raise exc
        if "directory/v1/users" in url:
            return {"users": [{"isEnforcedIn2Sv": True}] if users is None else users}
        if "reports/v1/activity" in url:
            if items is None:
                return {"items": [{"id": {}}]}
            return {"items": items} if items else {}              # Google omits "items" when there is nothing
        raise AssertionError(url)
    return get


class Denied(Exception):
    code = "HTTP 403"


def test_a_healthy_workspace_passes_both_and_is_complete():
    out = gw.collect(google())
    assert out["attributes"] == {"privileged_access_mfa": True, "access_logging_enabled": True}
    assert out["collection"] == {"complete": True, "errors": [], "region": "google-workspace"}


def test_a_super_admin_without_enforced_2sv_fails_only_the_mfa_check():
    out = gw.collect(google(users=[{"isEnforcedIn2Sv": True}, {"isEnrolledIn2Sv": True, "isEnforcedIn2Sv": False}]))
    assert out["attributes"] == {"privileged_access_mfa": False, "access_logging_enabled": True}


def test_a_suspended_super_admin_is_ignored_because_it_cannot_sign_in():
    out = gw.collect(google(users=[{"isEnforcedIn2Sv": True}, {"isEnforcedIn2Sv": False, "suspended": True}]))
    assert out["attributes"]["privileged_access_mfa"] is True


def test_no_recent_admin_activity_fails_only_the_logging_check():
    assert gw.collect(google(items=[]))["attributes"]["access_logging_enabled"] is False


def test_pages_are_followed():
    calls = []

    def get(url):
        calls.append(url)
        if "directory/v1/users" in url:
            if "pageToken=p2" in url:
                return {"users": [{"isEnforcedIn2Sv": False}]}
            return {"users": [{"isEnforcedIn2Sv": True}], "nextPageToken": "p2"}
        return {"items": [{}]}

    assert gw.collect(get)["attributes"]["privileged_access_mfa"] is False and any("pageToken=p2" in c for c in calls)


def test_a_missing_scope_or_no_admins_returned_is_left_out_never_read_as_a_pass_or_failure():
    out = gw.collect(google(fail={"reports/v1": Denied()}))
    assert "access_logging_enabled" not in out["attributes"] and out["collection"]["complete"] is False
    assert any("access_logging_enabled" in e and "HTTP 403" in e for e in out["collection"]["errors"])
    none = gw.collect(google(users=[{"suspended": True}]))
    assert "privileged_access_mfa" not in none["attributes"] and none["collection"]["complete"] is False


def test_only_read_calls_to_the_admin_sdk_are_made():
    seen = []
    gw.collect(lambda url: seen.append(url) or {"users": [{"isEnforcedIn2Sv": True}], "items": [{}]})
    assert len(seen) == 2 and all(u.startswith("https://admin.googleapis.com/admin/") for u in seen)


# --- the same token and ingest, for Google Workspace -----------------------------------------------------------
GOOD = {"attributes": {"privileged_access_mfa": True, "access_logging_enabled": False},
        "collection": {"complete": True, "errors": [], "region": "google-workspace"}}


def _token(client, org, source=SRC):
    r = client.post(f"/connections/{source}/token", headers=H(org))
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    return r.json()["new_token"]


def _push(client, token, source=SRC, body=GOOD):
    return client.post(f"/ingest/{source}", json=body, headers={"authorization": f"Bearer {token}"})


def test_an_upload_is_stored_as_google_workspace_evidence(client, bootstrap, key):
    org = bootstrap(client)[0]
    assert _push(client, _token(client, org)).status_code == 202
    with Session(db_module.engine) as s:
        ev = s.query(Evidence).filter_by(org_id=org, artefact_type="GOOGLE_WORKSPACE_SNAPSHOT").one()
        assert ev.uploaded_by == "upload:google-workspace"
        assert s.query(Connection).filter_by(org_id=org, kind="GOOGLE_WORKSPACE_PUSH").one().status == "OK"


def test_the_card_lists_the_clause_it_counts_toward_and_the_token_is_never_read_back(client, bootstrap, key):
    org = bootstrap(client)[0]
    secret = _token(client, org).split(".", 1)[1]
    listing = client.get("/connections", headers=H(org))
    assert secret not in listing.text
    view = {c["kind"]: c for c in listing.json()["connections"]}["GOOGLE_WORKSPACE_PUSH"]
    assert any(f["clause"] == "Rule 6 - Google Workspace baseline" for f in view["feeds"])


def test_a_token_for_one_source_never_works_for_another(client, bootstrap, key):
    org = bootstrap(client)[0]
    google_token, m365_token = _token(client, org), _token(client, org, "m365")
    assert _push(client, m365_token).status_code == 401
    assert _push(client, google_token, "m365").status_code == 401


def test_it_accepts_only_its_own_yes_no_attributes(client, bootstrap, key):
    token = _token(client, bootstrap(client)[0])
    assert _push(client, token, body={"attributes": {"backup_enabled": True}}).status_code == 422
    assert _push(client, token, body={"attributes": {"privileged_access_mfa": "yes"}}).status_code == 422


def test_the_collect_button_explains_that_results_arrive_from_the_script(client, bootstrap, key, monkeypatch):
    org = bootstrap(client)[0]
    monkeypatch.delenv("DPDP_GOOGLE_WORKSPACE_COLLECTOR_URL", raising=False)
    _token(client, org)
    r = client.post(f"/connectors/{SRC}/sync", headers=H(org))
    assert r.status_code == 409 and "own script" in r.json()["detail"]


def test_removing_ends_the_token(client, bootstrap, key):
    org = bootstrap(client)[0]
    token = _token(client, org)
    assert client.delete(f"/connections/{SRC}", headers=H(org)).json()["connections"][5]["configured"] is False
    assert _push(client, token).status_code == 401


# --- the script's own safety ----------------------------------------------------------------------------------
def _no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no network")
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", boom)


def test_the_script_dry_run_prints_the_answers_and_uploads_nothing(monkeypatch, capsys):
    monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "x")
    _no_network(monkeypatch)
    monkeypatch.setattr(gw, "collect", lambda get: {"attributes": {"privileged_access_mfa": True},
                                                    "collection": {"complete": True, "errors": [], "region": "google-workspace"}})
    assert gw.main(["--url", "https://example.test", "--dry-run"]) == 0
    assert '"privileged_access_mfa": true' in capsys.readouterr().out


def test_the_script_needs_a_google_sign_in_and_never_sends_a_token_over_plain_http(monkeypatch):
    monkeypatch.setattr(gw, "collect", lambda get: {"attributes": {}, "collection": {"complete": True, "errors": [], "region": ""}})
    for k in ("GOOGLE_ACCESS_TOKEN", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    assert gw.main(["--url", "https://example.test", "--dry-run"]) == 2          # no Google sign-in given
    monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "x")
    _no_network(monkeypatch)
    assert gw.main(["--url", "http://example.test", "--token", "a.b"]) == 2      # http, not https
    with pytest.raises(ValueError):
        gw._open(urllib.request.Request("http://example.test/"))                 # the opener itself refuses it too


def test_the_script_exits_1_when_refused_and_4_when_the_server_is_unreachable(monkeypatch):
    monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "x")
    monkeypatch.setattr(gw, "collect", lambda get: {"attributes": {"privileged_access_mfa": True},
                                                    "collection": {"complete": True, "errors": [], "region": ""}})

    def down(req):
        raise urllib.error.URLError("down")

    def refused(req):
        raise urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO())

    monkeypatch.setattr(gw, "_open", down)
    assert gw.main(["--url", "https://example.test", "--token", "a.b"]) == 4
    monkeypatch.setattr(gw, "_open", refused)
    assert gw.main(["--url", "https://example.test", "--token", "a.b"]) == 1


def test_the_opener_never_follows_a_redirect():
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            if self.path == "/a":
                self.send_response(302)
                self.send_header("Location", "/b")
                self.end_headers()
            else:
                self.send_response(200)
                self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(urllib.error.HTTPError) as caught:
            gw._open(urllib.request.Request(f"http://127.0.0.1:{server.server_port}/a"))
        assert caught.value.code == 302 and hits == ["/a"]
    finally:
        server.shutdown()
