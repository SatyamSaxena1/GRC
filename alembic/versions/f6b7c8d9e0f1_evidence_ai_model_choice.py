"""add evidence.ai_model / ai_vision_model (per-upload model choice)

Revision ID: f6b7c8d9e0f1
Revises: e5a6b7c8d9e0
"""

from alembic import op
import sqlalchemy as sa

revision = "f6b7c8d9e0f1"
down_revision = "e5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evidence", sa.Column("ai_model", sa.String(), nullable=True))
    op.add_column("evidence", sa.Column("ai_vision_model", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("evidence", "ai_vision_model")
    op.drop_column("evidence", "ai_model")
