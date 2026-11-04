"""connections an organisation sets up itself (ADR-044), under row level security from the start

Additive: a new table. The secret is stored only as ciphertext (Fernet, key CONNECTIONS_KEY); the other
columns are non-secret facts the page may show.

Revision ID: 944ba96502c7
Revises: c47609bb7698
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "944ba96502c7"
down_revision = "c47609bb7698"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("config_encrypted", sa.Text(), nullable=False),
        sa.Column("hint", sa.String(), nullable=False, server_default=""),
        sa.Column("status", sa.String(), nullable=False, server_default="UNTESTED"),
        sa.Column("last_tested_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("org_id", "kind", name="uq_connections_org_kind"),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE connections ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE connections FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY connections_tenant_isolation ON connections
        USING (org_id = current_setting('app.tenant_id', true))
        WITH CHECK (org_id = current_setting('app.tenant_id', true))
    """)


def downgrade() -> None:
    op.drop_table("connections")
