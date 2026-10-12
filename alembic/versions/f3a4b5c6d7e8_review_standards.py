"""review_standards: versioned, hashed Review Standards per organisation (ADR-027),
under row level security from the start

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f3a4b5c6d7e8"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_standards",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body", sa.JSON(), nullable=False),
        sa.Column("source_yaml", sa.Text(), nullable=False, server_default=""),
        sa.Column("body_hash", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("org_id", "version", name="uq_review_standards_org_version"),
    )
    # One active version per organisation, enforced by the database.
    op.create_index("uq_review_standards_one_active", "review_standards", ["org_id"], unique=True,
                    sqlite_where=sa.text("is_active"), postgresql_where=sa.text("is_active"))
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE review_standards ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE review_standards FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY review_standards_tenant_isolation ON review_standards
        USING (org_id = current_setting('app.tenant_id', true))
        WITH CHECK (org_id = current_setting('app.tenant_id', true))
    """)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS review_standards_tenant_isolation ON review_standards")
    op.drop_index("uq_review_standards_one_active", table_name="review_standards")
    op.drop_table("review_standards")
