"""row level security on users

users was the one tenant-owned table left without RLS (found by the catalog check in
tests/test_rls_postgres.py). It needs two policies, not one:

- users_tenant_isolation, for every command: a row is visible and writable only inside
  its own org (app.tenant_id) or firm (app.firm_id).
- users_identity_lookup, SELECT only: sign-in must find a user by id or email before any
  tenant is known. app/db.py::identity_lookup switches app.identity_lookup on around those
  lookups and off straight after, so the window is one query wide, read-only, and never
  reapplied by _rebind_scope.

Revision ID: a7b8c9d0e1f2
Revises: f6b7c8d9e0f1
"""

from __future__ import annotations

from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "f6b7c8d9e0f1"
branch_labels = None
depends_on = None

SCOPED = ("(org_id IS NOT NULL AND org_id = current_setting('app.tenant_id', true)) "
          "OR (audit_firm_id IS NOT NULL AND audit_firm_id = current_setting('app.firm_id', true))")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY users_tenant_isolation ON users USING ({SCOPED}) WITH CHECK ({SCOPED})")
    op.execute("CREATE POLICY users_identity_lookup ON users FOR SELECT "
               "USING (current_setting('app.identity_lookup', true) = 'on')")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP POLICY IF EXISTS users_identity_lookup ON users")
    op.execute("DROP POLICY IF EXISTS users_tenant_isolation ON users")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")
