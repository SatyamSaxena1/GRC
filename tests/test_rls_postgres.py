"""Row-level security, proven on real Postgres (ADR-001, ADR-019 rule 1).

The rest of the suite runs on SQLite, where app/db.py's set_tenant and set_firm are no-ops, so
nothing there can tell whether tenant isolation holds in the database. These tests migrate a
real Postgres schema with Alembic, which is what creates the policies, and connect as the
application role.

Skipped unless RLS_TEST_DATABASE_URL points at an empty database owned by a role that is
neither a superuser nor BYPASSRLS. Superusers ignore RLS entirely, so the first test refuses
to pass for such a role: a check that cannot go red is decoration. CI provides the URL
(.github/workflows/ci.yml, job `rls`).
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import db as db_module
from app.main import app
from app.routers import firm as firm_router

URL = os.environ.get("RLS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="RLS_TEST_DATABASE_URL not set (needs real Postgres)")


@pytest.fixture(scope="module")
def engine():
    """A freshly migrated schema, owned by the application role."""
    eng = create_engine(URL)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True,
                   env={**os.environ, "DATABASE_URL": URL})
    yield eng
    eng.dispose()


@pytest.fixture()
def client(engine, tmp_path, monkeypatch):
    monkeypatch.setenv("EVIDENCE_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setattr(db_module, "engine", engine)
    with TestClient(app) as c:
        yield c


def _org(client, name):
    return client.post("/admin/organizations", json={"name": name, "frameworks": ["ISO-27001"]}).json()["id"]


def _evidence(client, org_id):
    response = client.post("/evidence", headers={"authorization": f"org:{org_id}"},
                           params={"artefact_type": "POLICY"},
                           files={"file": ("policy.txt", b"an access control policy", "text/plain")})
    assert response.status_code == 202, response.text
    return response.json()["id"]


def test_the_application_role_is_bound_by_rls(engine):
    """If this fails, every other test here is meaningless: superusers and BYPASSRLS roles
    skip every policy."""
    with engine.connect() as conn:
        role = conn.execute(text(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
        forced = conn.execute(text(
            "SELECT relforcerowsecurity FROM pg_class WHERE relname = 'evidence'")).scalar_one()
    assert role == (False, False), "connect as a non-superuser without BYPASSRLS"
    assert forced, "evidence must have FORCE ROW LEVEL SECURITY, or its owner skips the policy"


def test_one_tenant_cannot_read_another_tenants_rows_at_the_database(client, engine):
    """The canary: the database itself, not application WHERE clauses, refuses the read."""
    org_a, org_b = _org(client, "Acme"), _org(client, "Beta")
    evidence_id = _evidence(client, org_a)

    def visible(tenant):
        with engine.begin() as conn:
            if tenant:
                conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant})
            return conn.execute(text("SELECT count(*) FROM evidence WHERE id = :id"),
                                {"id": evidence_id}).scalar_one()

    assert visible(org_a) == 1
    assert visible(org_b) == 0
    assert visible(None) == 0   # no tenant bound: nothing, not everything


def test_a_tenant_cannot_modify_another_tenants_rows(client, engine):
    org_a, org_b = _org(client, "Acme"), _org(client, "Beta")
    evidence_id = _evidence(client, org_a)
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": org_b})
        changed = conn.execute(text("UPDATE evidence SET description = 'tampered' WHERE id = :id"),
                               {"id": evidence_id}).rowcount
    assert changed == 0


def _approve_onboarding(client):
    firm = client.post("/admin/audit-firms", json={"name": "Gemba"}).json()["id"]
    admin = client.post("/admin/users", json={"email": "admin@gemba.test", "role": "FIRM_ADMIN",
                                              "audit_firm_id": firm}).json()["id"]
    request_id = client.post("/firm/onboarding-requests", json={
        "audit_firm_id": firm, "org_name": "Acme", "contact_email": "ciso@acme.test",
        "frameworks": ["ISO-27001"]}).json()["id"]
    return client.post(f"/firm/onboarding-requests/{request_id}/approve",
                       headers={"authorization": f"user:{admin}"}, json={"note": "signed"})


def test_approving_an_onboarding_request_works_under_rls(client):
    """Regression for ed57e9e: the firm's session carries only app.firm_id, so the new org's
    first audit row failed FORCE RLS until the approval bound the org as tenant."""
    response = _approve_onboarding(client)
    assert response.status_code == 200, response.text
    assert response.json()["org_id"]


def test_dropping_the_tenant_binding_turns_this_suite_red(client, monkeypatch):
    """The drill, kept as a test: remove the fix and the database refuses the write. Proof
    that the regression test above can fail, which on SQLite it never could."""
    monkeypatch.setattr(firm_router, "set_tenant", lambda db, org_id: None)
    with pytest.raises(Exception, match="row-level security"):
        _approve_onboarding(client)
