"""organizations.trust_token: an organisation can publish a content-free trust page (ADR-039)

Additive and nullable: null means not published. organizations is not a tenant-owned table (it has no
row level security), so the public route can find an organisation by token and then bind the tenant.

Revision ID: b8c9d0e1f2a3
Revises: f7a8b9c0d1e2
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b8c9d0e1f2a3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("trust_token", sa.String(), nullable=True))
    op.create_index("ix_organizations_trust_token", "organizations", ["trust_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_organizations_trust_token", table_name="organizations")
    op.drop_column("organizations", "trust_token")
