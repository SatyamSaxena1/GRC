"""verdict provenance (ADR-022): rule definitions and per-link provenance columns

Expand-only: a new table and nullable columns, so instances still running the previous
code during a deploy keep working.

Revision ID: c0d1e2f3a4b5
Revises: b8c9d0e1f2a4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c0d1e2f3a4b5"
down_revision = "b8c9d0e1f2a4"
branch_labels = None
depends_on = None

COLUMNS = ("rule_hash", "engine_version", "build_id", "evaluation_hash", "engine_verdict")


def upgrade() -> None:
    op.create_table(
        "rule_definitions",
        sa.Column("rule_hash", sa.String(), primary_key=True),
        sa.Column("framework", sa.String(), nullable=False),
        sa.Column("clause", sa.String(), nullable=False),
        sa.Column("body", sa.JSON(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    with op.batch_alter_table("evidence_control_links") as batch:
        for name in COLUMNS:
            batch.add_column(sa.Column(name, sa.String(), nullable=True))
        batch.add_column(sa.Column("evaluation_inputs", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("evidence_control_links") as batch:
        batch.drop_column("evaluation_inputs")
        for name in reversed(COLUMNS):
            batch.drop_column(name)
    op.drop_table("rule_definitions")
