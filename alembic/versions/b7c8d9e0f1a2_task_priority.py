"""add task priority

Revision ID: b7c8d9e0f1a2
Revises: 6a01a4bbfe77
"""

from alembic import op
import sqlalchemy as sa

revision = "b7c8d9e0f1a2"
down_revision = "6a01a4bbfe77"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(sa.Column("priority", sa.String(), nullable=False,
                                      server_default="MEDIUM"))


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_column("priority")
