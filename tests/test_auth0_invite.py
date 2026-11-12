"""Invite and deactivate with a sign-in service (ADR-047): off by default; the server never sees a password; a
failure leaves no half-invited person; the one-time link is shown once and never stored."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from app import auth0_admin
from app import db as db_module
from app.models import AuditEvent, User

OP = {"x-admin-key": "test-admin-key"}
LINK = "https://tenant.example.auth0.com/lo/reset?ticket=SECRETLINK123"


class FakeAuth0:
    def __init__(self):
        self.calls: list[tuple] = []
        self.users: dict[str, dict] = {}
        self.fail_on: str | None = None

    def __call__(self, method, url, json=None, params=None, timeout=None, allow_redirects=True, headers=None):
        self.calls.append((method, url, json, params, allow_redirects))
        path = url.split("/api/v2", 1)[1] if "/api/v2" in url else url

        class R:
            def __init__(s, code, body=None):
                s.status_code, s._b, s.content = code, body, b"x" if body is not None else b""

            def json(s):
                return s._b

        if self.fail_on and self.fail_on in path:
            return R(500, {})
        if url.endswith("/oauth/token"):
            return R(200, {"access_token": "tok", "expires_in": 3600})
        if path == "/users-by-email":
            u = self.users.get(params["email"].lower())
            return R(200, [u] if u else [])
        if path == "/users" and method == "POST":
            u = {"user_id": "auth0|1", "email": json["email"], "blocked": False, "_pw": json["password"]}
            self.users[json["email"]] = u
            return R(200, u)
        if path == "/tickets/password-change":
            return R(201, {"ticket": LINK})
        if path.startswith("/users/") and method == "PATCH":
            for u in self.users.values():
                if path.endswith(u["user_id"]):
                    u["blocked"] = json["blocked"]
            return R(200, {})
        return R(404, {})


@pytest.fixture()
def auth0(monkeypatch):
    fake = FakeAuth0()
    monkeypatch.setenv("AUTH0_DOMAIN", "tenant.example.auth0.com")
    monkeypatch.setenv("AUTH0_M2M_CLIENT_ID", "cid")
    monkeypatch.setenv("AUTH0_M2M_CLIENT_SECRET", "SECRETVALUE")
    monkeypatch.setattr(auth0_admin.requests, "request", fake)
    auth0_admin._cache.update(token="", until=0.0)
    return fake


def _org(client):
    return client.post("/admin/organizations", json={"name": "Acme", "frameworks": ["SOC-2"]}).json()["id"]


def _invite(client, org, email="new.person@example.com", role="COMPLIANCE_VIEWER"):
    return client.post("/admin/users", json={"email": email, "org_id": org, "role": role})


def test_off_by_default_inviting_only_writes_our_row(client, bootstrap, monkeypatch):
    for k in ("AUTH0_DOMAIN", "AUTH0_M2M_CLIENT_ID", "AUTH0_M2M_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    org, _ = bootstrap(client)
    r = _invite(client, org)
    assert r.status_code == 200 and "password_link" not in r.json() and not auth0_admin.enabled()


def test_an_invite_creates_the_login_with_a_random_password_and_returns_the_link_once(client, bootstrap, auth0):
    org, _ = bootstrap(client)
    r = _invite(client, org)
    assert r.status_code == 200 and r.json()["password_link"] == LINK
    assert r.headers["cache-control"] == "no-store"
    created = auth0.users["new.person@example.com"]
    assert len(created["_pw"]) >= 32                      # a random password nobody knows
    assert all(not redir for *_, redir in auth0.calls)    # never follows a redirect
    with Session(db_module.engine) as s:
        assert s.query(User).filter_by(email="new.person@example.com").count() == 1
        stored = json.dumps([(e.detail, e.reason) for e in s.query(AuditEvent)], default=str)
        assert "SECRETLINK123" not in stored and "SECRETVALUE" not in stored
        assert created["_pw"] not in stored


def test_an_existing_login_is_reused_not_overwritten(client, bootstrap, auth0):
    auth0.users["new.person@example.com"] = {"user_id": "auth0|existing", "email": "new.person@example.com"}
    org, _ = bootstrap(client)
    assert _invite(client, org).status_code == 200
    assert not [c for c in auth0.calls if c[0] == "POST" and c[1].endswith("/api/v2/users")]


def test_someone_who_signs_in_with_google_is_invited_without_a_password_link(client, bootstrap, auth0):
    auth0.users["g@example.com"] = {"user_id": "google-oauth2|123", "email": "g@example.com", "blocked": False}
    org, _ = bootstrap(client)
    r = _invite(client, org, email="g@example.com")
    assert r.status_code == 200
    body = r.json()
    assert body["existing_login"] is True and "password_link" not in body
    assert not any(c[1].endswith("/tickets/password-change") for c in auth0.calls)   # nothing was asked of the service
    assert not any(c[0] == "POST" and c[1].endswith("/users") for c in auth0.calls)  # and no second login was made


def test_if_the_service_fails_no_half_invited_person_is_left_behind(client, bootstrap, auth0):
    org, _ = bootstrap(client)
    auth0.fail_on = "/tickets/password-change"
    r = _invite(client, org)
    assert r.status_code == 502 and "SECRETVALUE" not in r.text
    with Session(db_module.engine) as s:
        assert s.query(User).filter_by(email="new.person@example.com").count() == 0


def test_a_bad_domain_is_refused_with_a_clear_reason(client, bootstrap, auth0, monkeypatch):
    monkeypatch.setenv("AUTH0_DOMAIN", "https://evil.test/path")
    org, _ = bootstrap(client)
    r = _invite(client, org)
    assert r.status_code == 502 and "hostname" in r.text


def test_deactivating_blocks_the_login_and_reactivating_unblocks_it(client, bootstrap, auth0):
    org = _org(client)
    admin = _invite(client, org, email="boss@example.com", role="ORG_ADMIN").json()["id"]
    uid = _invite(client, org).json()["id"]
    hdr = {"authorization": f"user:{admin}"}
    assert client.patch(f"/admin/users/{uid}", json={"active": False}, headers=hdr).status_code == 200
    assert auth0.users["new.person@example.com"]["blocked"] is True
    assert client.patch(f"/admin/users/{uid}", json={"active": True}, headers=hdr).status_code == 200
    assert auth0.users["new.person@example.com"]["blocked"] is False


def test_a_failed_block_never_stops_the_deactivation_and_is_recorded(client, bootstrap, auth0):
    org = _org(client)
    admin = _invite(client, org, email="boss@example.com", role="ORG_ADMIN").json()["id"]
    uid = _invite(client, org).json()["id"]
    auth0.fail_on = "/users"
    r = client.patch(f"/admin/users/{uid}", json={"active": False}, headers={"authorization": f"user:{admin}"})
    assert r.status_code == 200 and r.json()["active"] is False
    with Session(db_module.engine) as s:
        ev = s.query(AuditEvent).filter_by(action="USER_UPDATED").order_by(AuditEvent.at.desc()).first()
        assert "login_block_error" in ev.detail
