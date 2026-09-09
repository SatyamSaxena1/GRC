"""row level security on control_messages

Same direct org_id policy as the tables in a1b2c3d4e5f6 — kept as its own
migration per this repo's convention of one RLS policy migration per new
tenant table.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
"""

from __future__ import annotations

from alembic import op

revision = "f4a5b6c7d8e9"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None

TABLE = "control_messages"


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
