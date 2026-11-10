"""organizations created_at / first_verdict_at, and control_verdict_changes (ADR-058)

Additive. The two organizations columns are nullable and nothing is backfilled: an organisation that already exists has
no recorded start, so it has no time-to-first-verdict rather than an invented one. control_verdict_changes is a new
tenant table, under row level security from the start; it fills as controls are evaluated and by the weekly run.

Revision ID: e7c4a91d5b32
Revises: b9c0d1e2f3a4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e7c4a91d5b32"
down_revision = "b9c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("created_at", sa.DateTime(), nullable=True))
    op.add_column("organizations", sa.Column("first_verdict_at", sa.DateTime(), nullable=True))
    op.create_table(
        "control_verdict_changes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("framework", sa.String(), nullable=False),
        sa.Column("clause", sa.String(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_control_verdict_changes_org_at", "control_verdict_changes", ["org_id", "at"])
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE control_verdict_changes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE control_verdict_changes FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY control_verdict_changes_tenant_isolation ON control_verdict_changes
        USING (org_id = current_setting('app.tenant_id', true))
        WITH CHECK (org_id = current_setting('app.tenant_id', true))
    """)


def downgrade() -> None:
    op.drop_table("control_verdict_changes")
    op.drop_column("organizations", "first_verdict_at")
    op.drop_column("organizations", "created_at")
