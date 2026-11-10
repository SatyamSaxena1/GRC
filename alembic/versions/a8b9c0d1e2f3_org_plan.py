"""organizations plan, trial_ends_at, frameworks_limit, seats_limit (ADR-054)

Additive and nullable on purpose: every existing organisation keeps all four null, which the code reads as "no plan,
no limits" -- nothing is enforced against a row until an operator gives it a plan. No backfill, no data change.

Revision ID: a8b9c0d1e2f3
Revises: 944ba96502c7
"""

from alembic import op
import sqlalchemy as sa

revision = "a8b9c0d1e2f3"
down_revision = "944ba96502c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("plan", sa.String(), nullable=True))
    op.add_column("organizations", sa.Column("trial_ends_at", sa.DateTime(), nullable=True))
    op.add_column("organizations", sa.Column("frameworks_limit", sa.Integer(), nullable=True))
    op.add_column("organizations", sa.Column("seats_limit", sa.Integer(), nullable=True))


def downgrade() -> None:
    for c in ("seats_limit", "frameworks_limit", "trial_ends_at", "plan"):
        op.drop_column("organizations", c)
