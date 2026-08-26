"""row level security on ciso_sync_state

Same direct org_id policy as the tables in a1b2c3d4e5f6 — kept as its own
migration rather than reopening that one, per this repo's convention of one
RLS policy migration per new tenant table.

Revision ID: d7e8f9a0b1c2
Revises: c1d2e3f4a5b6
"""

from __future__ import annotations

from alembic import op

revision = "d7e8f9a0b1c2"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None

TABLE = "ciso_sync_state"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {TABLE}_tenant_isolation ON {TABLE}
        USING (org_id IS NULL OR org_id = current_setting('app.tenant_id', true))
        WITH CHECK (org_id IS NULL OR org_id = current_setting('app.tenant_id', true))
    """)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON {TABLE}")
    op.execute(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY")
