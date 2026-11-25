"""DPDP duty-level not applicable, under row level security from the start

Additive: one new table. Nothing existing changes.

Revision ID: c3e8a1f5d7b2
Revises: b8d2f4a6c1e7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c3e8a1f5d7b2"
down_revision = "b8d2f4a6c1e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dpdp_duty_na",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("framework", sa.String(), nullable=False),
        sa.Column("clause", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("marked_by", sa.String(), nullable=False),
        sa.Column("marked_at", sa.DateTime(), nullable=False),
        sa.Column("reversed_by", sa.String(), nullable=True),
        sa.Column("reversed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_dpdp_duty_na_org", "dpdp_duty_na", ["org_id", "framework", "clause"])
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE dpdp_duty_na ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE dpdp_duty_na FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY dpdp_duty_na_tenant_isolation ON dpdp_duty_na
        USING (org_id = current_setting('app.tenant_id', true))
        WITH CHECK (org_id = current_setting('app.tenant_id', true))
    """)


def downgrade() -> None:
    op.drop_index("ix_dpdp_duty_na_org", table_name="dpdp_duty_na")
    op.drop_table("dpdp_duty_na")
