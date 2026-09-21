"""Production-deploy guards: unsigned stub tokens can be switched off, the
/admin bootstrap routes need an operator key, and Render-style database URLs
are accepted. Defaults (stub on, no key) must leave dev and every other test
untouched."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import auth, oidc
from app.dburl import database_url
from app.main import app


def test_stub_token_rejected_when_stub_disabled(client, bootstrap, monkeypatch):
    org_id, _ = bootstrap(client)
    assert client.get("/controls", headers={"authorization": f"org:{org_id}"}).status_code == 200

    monkeypatch.setattr(auth, "STUB_ENABLED", False)
    assert client.get("/controls", headers={"authorization": f"org:{org_id}"}).status_code == 401


def test_startup_refuses_stub_off_without_oidc(monkeypatch):
    monkeypatch.setattr(auth, "STUB_ENABLED", False)
    monkeypatch.setattr(oidc, "JWKS_URL", "")
    with pytest.raises(RuntimeError, match="OIDC"):
        with TestClient(app):
            pass


def test_startup_refuses_stub_off_on_sqlite(monkeypatch):
    """DATABASE_URL unset falls back to SQLite; in production mode that must be
    a boot failure, not a healthy-looking service on an ephemeral disk."""
    monkeypatch.setattr(auth, "STUB_ENABLED", False)
    monkeypatch.setattr(oidc, "JWKS_URL", "https://idp.test/jwks")
    monkeypatch.setattr(oidc, "ISSUER", "https://idp.test/")
    monkeypatch.setattr(oidc, "AUDIENCE", "grc")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        with TestClient(app):
            pass


def test_admin_open_in_dev_without_key(client):
    resp = client.post("/admin/organizations", json={"name": "A", "frameworks": ["ISO-27001"]})
    assert resp.status_code == 200


def test_admin_requires_matching_key_when_set(client, monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "s3cret")
    body = {"name": "A", "frameworks": ["ISO-27001"]}

    assert client.post("/admin/organizations", json=body).status_code == 401
    assert client.post("/admin/organizations", json=body,
                       headers={"x-admin-key": "wrong"}).status_code == 401
    assert client.post("/admin/organizations", json=body,
                       headers={"x-admin-key": "s3cret"}).status_code == 200


def test_admin_fails_closed_in_prod_without_key(client, monkeypatch):
    monkeypatch.setattr(auth, "STUB_ENABLED", False)
    resp = client.post("/admin/organizations", json={"name": "A", "frameworks": ["ISO-27001"]})
    assert resp.status_code == 403


@pytest.mark.parametrize("given, expected", [
    ("postgres://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
    ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ("sqlite:///./x.db", "sqlite:///./x.db"),
])
def test_database_url_normalised(monkeypatch, given, expected):
    monkeypatch.setenv("DATABASE_URL", given)
    assert database_url() == expected
