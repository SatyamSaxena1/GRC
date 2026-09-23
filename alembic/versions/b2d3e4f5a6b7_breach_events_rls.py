"""row level security on breach_events

Same direct org_id policy as control_messages (f4a5b6c7d8e9) — one RLS policy
migration per new tenant table, per this repo's convention.

Revision ID: b2d3e4f5a6b7
Revises: a1c2d3e4f5a6
"""

from __future__ import annotations

from alembic import op

revision = "b2d3e4f5a6b7"
down_revision = "a1c2d3e4f5a6"
branch_labels = None
depends_on = None

TABLE = "breach_events"


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
