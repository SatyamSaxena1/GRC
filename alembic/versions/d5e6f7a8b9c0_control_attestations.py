"""control attestations (ADR-060), under row level security from the start

Additive: one new table. Nothing existing changes.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "control_attestations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("framework", sa.String(), nullable=False),
        sa.Column("clause", sa.String(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("evidence_id", sa.String(), sa.ForeignKey("evidence.id"), nullable=True),
        sa.Column("attested_by", sa.String(), nullable=False),
        sa.Column("attested_at", sa.DateTime(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=False),
        sa.Column("revoked_by", sa.String(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_control_attestations_org", "control_attestations", ["org_id", "framework", "clause"])
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE control_attestations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE control_attestations FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY control_attestations_tenant_isolation ON control_attestations
        USING (org_id = current_setting('app.tenant_id', true))
        WITH CHECK (org_id = current_setting('app.tenant_id', true))
    """)


def downgrade() -> None:
    op.drop_index("ix_control_attestations_org", table_name="control_attestations")
    op.drop_table("control_attestations")
