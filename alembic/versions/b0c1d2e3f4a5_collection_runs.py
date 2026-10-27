"""connector collection runs (ADR-030), under row level security from the start

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b0c1d2e3f4a5"
down_revision = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collection_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("expectation", sa.String(), nullable=False),
        sa.Column("requested", sa.JSON(), nullable=False),
        sa.Column("returned", sa.JSON(), nullable=False),
        sa.Column("signals", sa.JSON(), nullable=False),
        sa.Column("evidence_id", sa.String(), sa.ForeignKey("evidence.id"), nullable=True),
    )
    op.create_index("ix_collection_runs_lookup", "collection_runs", ["org_id", "source", "started_at"])
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE collection_runs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE collection_runs FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY collection_runs_tenant_isolation ON collection_runs
        USING (org_id = current_setting('app.tenant_id', true))
        WITH CHECK (org_id = current_setting('app.tenant_id', true))
    """)


def downgrade() -> None:
    op.drop_index("ix_collection_runs_lookup", table_name="collection_runs")
    op.drop_table("collection_runs")
