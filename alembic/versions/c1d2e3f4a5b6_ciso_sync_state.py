"""add ciso_sync_state

Revision ID: c1d2e3f4a5b6
Revises: b7c8d9e0f1a2
"""

from alembic import op
import sqlalchemy as sa

revision = "c1d2e3f4a5b6"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ciso_sync_state",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("local_entity_type", sa.String(), nullable=False),
        sa.Column("local_entity_id", sa.String(), nullable=False),
        sa.Column("ciso_assistant_object_id", sa.String(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_sync_status", sa.String(), nullable=False, server_default="PENDING"),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint("org_id", "local_entity_type", "local_entity_id"),
    )


def downgrade() -> None:
    op.drop_table("ciso_sync_state")
