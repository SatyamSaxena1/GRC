"""ai_runs.decision_hash and ai_runs.detail: typed-decision provenance (ADR-025)

Expand-only: existing rows keep NULL, and an instance still running the previous code writes
NULL too, which reads as "recorded before decision hashes".

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_runs") as batch:
        batch.add_column(sa.Column("decision_hash", sa.String(), nullable=True))
        batch.add_column(sa.Column("detail", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ai_runs") as batch:
        batch.drop_column("detail")
        batch.drop_column("decision_hash")
