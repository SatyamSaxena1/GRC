"""training lessons and graded tries (ADR-064), the new table under row level security from the start

Additive: one nullable-safe column with a default, and one new table. Nothing existing changes meaning.

Revision ID: e4a7c2d9b6f3
Revises: c8d4f1a6b2e7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e4a7c2d9b6f3"
down_revision = "c8d4f1a6b2e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("training_courses", sa.Column("lessons", sa.JSON(), nullable=False, server_default="[]"))
    op.create_table(
        "training_attempts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("course_id", sa.String(), sa.ForeignKey("training_courses.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("lesson", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("correct", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_training_attempts_course", "training_attempts", ["org_id", "course_id", "user_id"])
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE training_attempts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE training_attempts FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY training_attempts_tenant_isolation ON training_attempts
        USING (org_id = current_setting('app.tenant_id', true))
        WITH CHECK (org_id = current_setting('app.tenant_id', true))
    """)


def downgrade() -> None:
    op.drop_index("ix_training_attempts_course", table_name="training_attempts")
    op.drop_table("training_attempts")
    op.drop_column("training_courses", "lessons")
