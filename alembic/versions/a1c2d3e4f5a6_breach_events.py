"""add breach_events

Revision ID: a1c2d3e4f5a6
Revises: e5f6a7b8c9d0
"""

from alembic import op
import sqlalchemy as sa

revision = "a1c2d3e4f5a6"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "breach_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("personal_data_categories", sa.Text(), nullable=False, server_default=""),
        sa.Column("affected_count_estimate", sa.Integer(), nullable=True),
        sa.Column("board_notify_due_at", sa.DateTime(), nullable=False),
        sa.Column("board_notified_at", sa.DateTime(), nullable=True),
        sa.Column("affected_notify_due_at", sa.DateTime(), nullable=True),
        sa.Column("affected_notified_at", sa.DateTime(), nullable=True),
        sa.Column("board_task_id", sa.String(), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("affected_task_id", sa.String(), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="OPEN"),
        sa.Column("created_by", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("breach_events")
