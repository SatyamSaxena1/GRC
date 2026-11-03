"""users.active, so an admin can deactivate someone without deleting their history (ADR-036)

Additive: existing rows are active. Users already have row level security (a7b8c9d0e1f2), which
covers the new column.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("users", "active")
