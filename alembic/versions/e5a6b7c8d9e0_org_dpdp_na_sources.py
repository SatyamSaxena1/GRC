"""add organizations.dpdp_na_sources

Revision ID: e5a6b7c8d9e0
Revises: d4f5a6b7c8d9
"""

from alembic import op
import sqlalchemy as sa

revision = "e5a6b7c8d9e0"
down_revision = "d4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("dpdp_na_sources", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("organizations", "dpdp_na_sources")
