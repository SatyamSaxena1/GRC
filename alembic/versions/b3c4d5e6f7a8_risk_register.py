"""risk register: risks table with row level security (ADR-056)

A new table, so there are no existing rows to convert. Row level security is enabled and forced in the same
revision, with the same policy as every other tenant table, so no moment exists where the table is readable
across tenants.

Revision ID: b3c4d5e6f7a8
Revises: a8b9c0d1e2f3
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "b3c4d5e6f7a8"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None

TABLE = "risks"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(), nullable=False, server_default="OTHER"),
        sa.Column("owner_email", sa.String(), nullable=False, server_default=""),
        sa.Column("inherent_likelihood", sa.Integer(), nullable=False),
        sa.Column("inherent_impact", sa.Integer(), nullable=False),
        sa.Column("treatment", sa.String(), nullable=True),
        sa.Column("treatment_plan", sa.Text(), nullable=False, server_default=""),
        sa.Column("residual_likelihood", sa.Integer(), nullable=True),
        sa.Column("residual_impact", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="OPEN"),
        sa.Column("next_review_date", sa.Date(), nullable=True),
        sa.Column("last_reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("control_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False, server_default=""),
    )
    op.create_index("ix_risks_org_id", TABLE, ["org_id"])
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
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON {TABLE}")
    op.drop_index("ix_risks_org_id", table_name=TABLE)
    op.drop_table(TABLE)
