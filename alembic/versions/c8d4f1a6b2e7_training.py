"""training courses and completions (ADR-063), under row level security from the start

Additive: two new tables. Nothing existing changes.

Revision ID: c8d4f1a6b2e7
Revises: a7c3e9d15f20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c8d4f1a6b2e7"
down_revision = "a7c3e9d15f20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "training_courses",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("cycle_days", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("created_by", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_training_courses_org", "training_courses", ["org_id"])
    op.create_table(
        "training_completions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("course_id", sa.String(), sa.ForeignKey("training_courses.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_training_completions_course", "training_completions", ["org_id", "course_id", "user_id"])
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in ("training_courses", "training_completions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (org_id = current_setting('app.tenant_id', true))
            WITH CHECK (org_id = current_setting('app.tenant_id', true))
        """)


def downgrade() -> None:
    op.drop_index("ix_training_completions_course", table_name="training_completions")
    op.drop_table("training_completions")
    op.drop_index("ix_training_courses_org", table_name="training_courses")
    op.drop_table("training_courses")
