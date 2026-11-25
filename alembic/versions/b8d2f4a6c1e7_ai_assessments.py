"""ai assessments (ADR-069), under row level security from the start

Additive: one new table. Nothing existing changes.

Revision ID: b8d2f4a6c1e7
Revises: e4a7c2d9b6f3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b8d2f4a6c1e7"
down_revision = "e4a7c2d9b6f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_assessments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("framework", sa.String(), nullable=False),
        sa.Column("clause", sa.String(), nullable=False),
        sa.Column("evidence_id", sa.String(), sa.ForeignKey("evidence.id"), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("points", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("document_sha256", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_outcome", sa.String(), nullable=True),
        sa.Column("confirmed_by", sa.String(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("confirm_note", sa.Text(), nullable=False),
    )
    op.create_index("ix_ai_assessments_org", "ai_assessments", ["org_id", "framework", "clause"])
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE ai_assessments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ai_assessments FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY ai_assessments_tenant_isolation ON ai_assessments
        USING (org_id = current_setting('app.tenant_id', true))
        WITH CHECK (org_id = current_setting('app.tenant_id', true))
    """)


def downgrade() -> None:
    op.drop_index("ix_ai_assessments_org", table_name="ai_assessments")
    op.drop_table("ai_assessments")
