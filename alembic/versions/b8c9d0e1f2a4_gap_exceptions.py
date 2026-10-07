"""gap exceptions (ADR-021), under row level security from the start

Revision ID: b8c9d0e1f2a4
Revises: a7b8c9d0e1f2
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b8c9d0e1f2a4"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gap_exceptions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("framework", sa.String(), nullable=False),
        sa.Column("clause", sa.String(), nullable=False),
        sa.Column("attribute", sa.String(), nullable=False),
        sa.Column("gap_kind", sa.String(), nullable=False),
        sa.Column("rule_hash", sa.String(), nullable=False),
        sa.Column("value_fingerprint", sa.String(), nullable=False),
        sa.Column("actual_value", sa.String(), nullable=True),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("compensating_control", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(), nullable=False, server_default="REQUESTED"),
        sa.Column("requested_by", sa.String(), nullable=False),
        sa.Column("requested_by_user_id", sa.String(), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("decided_by", sa.String(), nullable=True),
        sa.Column("decided_by_user_id", sa.String(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index("ix_gap_exceptions_lookup", "gap_exceptions",
                    ["org_id", "framework", "clause", "attribute", "gap_kind"])
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE gap_exceptions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE gap_exceptions FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY gap_exceptions_tenant_isolation ON gap_exceptions
        USING (org_id = current_setting('app.tenant_id', true))
        WITH CHECK (org_id = current_setting('app.tenant_id', true))
    """)


def downgrade() -> None:
    op.drop_index("ix_gap_exceptions_lookup", table_name="gap_exceptions")
    op.drop_table("gap_exceptions")
