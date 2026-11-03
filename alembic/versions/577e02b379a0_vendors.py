"""vendor register (ADR-042), under row level security from the start

Additive: a new table. A vendor's risk tier and review status are derived at read time from these columns by
fixed rules (app/vendors.py), so nothing derived is stored here.

Revision ID: 577e02b379a0
Revises: 2daa67f6f070
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "577e02b379a0"
down_revision = "2daa67f6f070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vendors",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("service", sa.String(), nullable=False, server_default=""),
        sa.Column("data_access", sa.String(), nullable=False, server_default="NONE"),
        sa.Column("criticality", sa.String(), nullable=False, server_default="LOW"),
        sa.Column("has_attestation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("owner_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="ACTIVE"),
        sa.Column("last_reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False, server_default=""),
    )
    op.create_index("ix_vendors_org", "vendors", ["org_id", "status"])
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE vendors ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE vendors FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY vendors_tenant_isolation ON vendors
        USING (org_id = current_setting('app.tenant_id', true))
        WITH CHECK (org_id = current_setting('app.tenant_id', true))
    """)


def downgrade() -> None:
    op.drop_index("ix_vendors_org", table_name="vendors")
    op.drop_table("vendors")
