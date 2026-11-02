"""auditor findings (ADR-032), under row level security from the start

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "findings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("org_control_id", sa.String(), sa.ForeignKey("org_controls.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False, server_default="MEDIUM"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(), nullable=False, server_default="OPEN"),
        sa.Column("raised_by", sa.String(), nullable=False),
        sa.Column("raised_at", sa.DateTime(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False, server_default=""),
        sa.Column("responded_by", sa.String(), nullable=True),
        sa.Column("responded_at", sa.DateTime(), nullable=True),
        sa.Column("closed_by", sa.String(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("close_note", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index("ix_findings_control", "findings", ["org_id", "org_control_id"])
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE findings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE findings FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY findings_tenant_isolation ON findings
        USING (org_id = current_setting('app.tenant_id', true))
        WITH CHECK (org_id = current_setting('app.tenant_id', true))
    """)


def downgrade() -> None:
    op.drop_index("ix_findings_control", table_name="findings")
    op.drop_table("findings")
