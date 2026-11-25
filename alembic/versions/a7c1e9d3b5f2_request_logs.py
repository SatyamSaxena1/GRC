"""durable request log (ADR-070)

Additive: one new table, not tenant-owned. On PostgreSQL it is behind forced row level security that lets anyone
INSERT (the request middleware writes it) but admits SELECT and DELETE only when the transaction sets
app.log_access = 'on', which only the operator endpoint and the retention job do. Tenant code never sets it, so a
tenant session reads nothing from this table.

Revision ID: a7c1e9d3b5f2
Revises: c3e8a1f5d7b2
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a7c1e9d3b5f2"
down_revision = "c3e8a1f5d7b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "request_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("path", sa.String(200), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("auth", sa.String(10), nullable=False),
        sa.Column("org_id", sa.String(), nullable=True),
        sa.Column("ip", sa.String(45), nullable=False, server_default=""),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_request_logs_ts", "request_logs", ["ts"])
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE request_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE request_logs FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY request_logs_insert ON request_logs FOR INSERT WITH CHECK (true)")
    for verb in ("SELECT", "DELETE"):
        op.execute(f"""
            CREATE POLICY request_logs_{verb.lower()} ON request_logs FOR {verb}
            USING (current_setting('app.log_access', true) = 'on')
        """)


def downgrade() -> None:
    op.drop_index("ix_request_logs_ts", table_name="request_logs")
    op.drop_table("request_logs")
