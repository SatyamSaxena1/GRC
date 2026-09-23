"""row level security on rights_requests

Revision ID: d4f5a6b7c8d9
Revises: c3e4f5a6b7c8
"""

from __future__ import annotations

from alembic import op

revision = "d4f5a6b7c8d9"
down_revision = "c3e4f5a6b7c8"
branch_labels = None
depends_on = None

TABLE = "rights_requests"


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
