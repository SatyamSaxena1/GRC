"""per-tenant audit chains, append-only in the database

Expand-only columns: rows written before this (and any written by an instance still running the
previous code during the deploy) keep NULL chain columns and are sealed by each chain's genesis
event (app/audit_log.py). On Postgres a trigger refuses UPDATE and DELETE on audit_events, so
the database itself, not only the application, keeps the trail append-only.

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d1e2f3a4b5c6"
down_revision = "c0d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("audit_events") as batch:
        batch.add_column(sa.Column("chain", sa.String(), nullable=True))
        batch.add_column(sa.Column("chain_seq", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("hash_version", sa.Integer(), nullable=True))
        batch.create_unique_constraint("uq_audit_events_chain_seq", ["chain", "chain_seq"])
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("""
        CREATE FUNCTION audit_events_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()
    """)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
        op.execute("DROP FUNCTION IF EXISTS audit_events_append_only()")
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint("uq_audit_events_chain_seq", type_="unique")
        batch.drop_column("hash_version")
        batch.drop_column("chain_seq")
        batch.drop_column("chain")
