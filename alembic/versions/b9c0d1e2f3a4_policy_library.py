"""policy library and acceptances (ADR-056), under row level security from the start

Additive: three new tables. Nothing existing changes.

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "policy_docs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(), nullable=False, server_default="DRAFT"),
        sa.Column("approved_by", sa.String(), nullable=False, server_default=""),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("review_due", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False, server_default=""),
    )
    op.create_index("ix_policy_docs_org", "policy_docs", ["org_id"])
    op.create_table(
        "policy_acceptances",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("policy_id", sa.String(), sa.ForeignKey("policy_docs.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("policy_id", "version", "user_id", name="uq_policy_acceptance"),
    )
    op.create_index("ix_policy_acceptances_org", "policy_acceptances", ["org_id", "policy_id"])
    op.create_table(
        "policy_versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("policy_id", sa.String(), sa.ForeignKey("policy_docs.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("approved_by", sa.String(), nullable=False, server_default=""),
        sa.Column("approved_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("policy_id", "version", name="uq_policy_version"),
    )
    op.create_index("ix_policy_versions_org", "policy_versions", ["org_id", "policy_id"])
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in ("policy_docs", "policy_acceptances", "policy_versions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (org_id = current_setting('app.tenant_id', true))
            WITH CHECK (org_id = current_setting('app.tenant_id', true))
        """)


def downgrade() -> None:
    op.drop_index("ix_policy_versions_org", table_name="policy_versions")
    op.drop_table("policy_versions")
    op.drop_index("ix_policy_acceptances_org", table_name="policy_acceptances")
    op.drop_table("policy_acceptances")
    op.drop_index("ix_policy_docs_org", table_name="policy_docs")
    op.drop_table("policy_docs")
