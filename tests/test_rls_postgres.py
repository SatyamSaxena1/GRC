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


def test_every_tenant_owned_table_has_forced_rls(engine):
    """The catalog check (borrowed from the earlier Trishul attempt): a single table proves
    little, so assert that every table carrying a tenant column is behind enabled AND forced
    RLS. A new tenant table shipped without its policy migration fails here, not in
    production."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT c.relname, bool_and(c.relrowsecurity AND c.relforcerowsecurity)
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid AND NOT a.attisdropped
                               AND a.attname IN ('org_id', 'audit_firm_id')
            WHERE n.nspname = 'public' AND c.relkind = 'r'
            GROUP BY c.relname ORDER BY c.relname
        """)).all()
    assert rows, "no tenant-owned tables found: is this the migrated schema?"
    unforced = [name for name, forced in rows if not forced]
    assert not unforced, f"tenant tables without enabled and forced RLS: {unforced}"


def _user(client, org_id, email):
    return client.post("/admin/users", json={"email": email, "org_id": org_id,
                                             "role": "ORG_ADMIN"}).json()["id"]


def test_one_tenant_cannot_read_another_tenants_users(client, engine):
    org_a, org_b = _org(client, "Acme"), _org(client, "Beta")
    alice = _user(client, org_a, "alice@acme.test")

    def visible(tenant):
        with engine.begin() as conn:
            conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant})
            return conn.execute(text("SELECT count(*) FROM users WHERE id = :id"), {"id": alice}).scalar_one()

    assert visible(org_a) == 1
    assert visible(org_b) == 0


def test_the_identity_lookup_is_read_only_and_switches_off(client, engine):
    from sqlalchemy.orm import Session

    from app.db import identity_lookup
    org_a = _org(client, "Acme")
    alice = _user(client, org_a, "alice@acme.test")
    with Session(engine) as db, db.begin():
        with identity_lookup(db):
            assert db.execute(text("SELECT count(*) FROM users WHERE id = :id"), {"id": alice}).scalar_one() == 1
            changed = db.execute(text("UPDATE users SET role = 'X' WHERE id = :id"), {"id": alice}).rowcount
            assert changed == 0   # lookup grants reading, never writing
        assert db.execute(text("SELECT count(*) FROM users WHERE id = :id"), {"id": alice}).scalar_one() == 0


def test_signing_in_as_a_user_still_works_under_rls(client):
    org_a = _org(client, "Acme")
    alice = _user(client, org_a, "alice@acme.test")
    assert client.get("/controls", headers={"authorization": f"user:{alice}"}).status_code == 200
    assert client.get("/controls", headers={"authorization": "user:nobody"}).status_code == 401


class _Collector:
    content = b"{}"

    def raise_for_status(self):
        return None

    def json(self):
        return {"attributes": {"default_branch_protected": True, "required_approving_reviews": 1,
                               "merges_without_independent_approval": 2}}


def test_verdict_provenance_is_recorded_and_replays_under_rls(client, monkeypatch):
    """ADR-022 on the real substrate: rule_definitions is platform content with no tenant
    column, written from inside a tenant-bound pipeline, and replay reads it back."""
    from app.routers import connectors
    org = client.post("/admin/organizations", json={"name": "Acme", "frameworks": ["SOC-2"]}).json()["id"]
    monkeypatch.setenv(connectors._env_key("github", "URL"), "https://collector.test/github")
    monkeypatch.setattr(connectors.requests, "get", lambda url, **_: _Collector())
    headers = {"authorization": f"org:{org}"}
    assert client.post("/connectors/github/sync", headers=headers).status_code == 202
    evidence = next(e for e in client.get("/evidence", headers=headers).json()
                    if e["artefact_type"] == "CHANGE_CONTROL_SNAPSHOT")
    link = next(l for l in client.get(f"/evidence/{evidence['id']}", headers=headers).json()["links"]
                if l["clause"] == "CC8.1")
    assert link["provenance"]["evaluation_hash"]
    replay = client.get(f"/evidence/{evidence['id']}/links/{link['id']}/replay", headers=headers).json()
    assert replay["status"] == "REPRODUCED", replay


def test_the_audit_chain_verifies_from_every_tenants_view(client, engine):
    """The canary for the audit chain under RLS. Each tenant sees only its own events plus
    platform events, so a single global chain cannot be both written and verified from a
    tenant's view: one tenant's write chains off rows another tenant never sees."""
    from sqlalchemy.orm import Session

    from app.audit_log import record, verify_chain
    from app.db import set_tenant

    org_a, org_b = _org(client, "Acme"), _org(client, "Beta")

    def write(org):
        with Session(engine) as s, s.begin():
            set_tenant(s, org)
            record(s, actor="test", action="TOUCHED", entity_type="test", entity="x", org_id=org)

    write(org_a)
    write(org_b)
    write(None)      # a platform event, visible to every tenant
    write(org_a)

    for org in (org_a, org_b):
        with Session(engine) as s, s.begin():
            set_tenant(s, org)
            from app.audit_log import verify, visible_chains
            assert verify_chain(s) is True, [verify(s, c) for c in visible_chains(s)]


def test_the_database_refuses_to_edit_or_delete_audit_events(client, engine):
    """Append-only in the database itself, not only by convention in the application."""
    from sqlalchemy.orm import Session

    from app.audit_log import record
    from app.db import set_tenant

    org = _org(client, "Acme")
    with Session(engine) as s, s.begin():
        set_tenant(s, org)
        event_id = record(s, actor="t", action="TOUCHED", entity_type="t", entity="x", org_id=org).id
    for statement in ("UPDATE audit_events SET reason = 'edited' WHERE id = :id",
                      "DELETE FROM audit_events WHERE id = :id"):
        with pytest.raises(Exception, match="append-only"):
            with Session(engine) as s, s.begin():
                set_tenant(s, org)
                s.execute(text(statement), {"id": event_id})


def test_concurrent_writers_never_fork_a_chain(client, engine):
    """Writers of one chain are serialized by an advisory lock: twenty concurrent events
    land as twenty consecutive links, not as branches sharing a predecessor."""
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy.orm import Session

    from app.audit_log import record, verify
    from app.db import set_tenant

    org = _org(client, "Acme")

    def write(i):
        with Session(engine) as s, s.begin():
            set_tenant(s, org)
            record(s, actor="t", action=f"TOUCHED-{i}", entity_type="t", entity="x", org_id=org)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(20)))
    with Session(engine) as s, s.begin():
        set_tenant(s, org)
        report = verify(s, org)
    assert report.ok, report.problems
    assert report.head_seq == report.events and report.events >= 21
