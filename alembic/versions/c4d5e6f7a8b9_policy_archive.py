"""policy_docs.archived_at (ADR-056 amendment)

Additive and nullable: every existing policy keeps null, which reads as "not archived". No backfill, no data change.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
"""

from alembic import op
import sqlalchemy as sa

revision = "c4d5e6f7a8b9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("policy_docs", sa.Column("archived_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("policy_docs", "archived_at")
