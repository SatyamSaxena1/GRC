"""organization-defined commitments (policy-stated thresholds an org is held to)

Adds org_commitments (one row per org+attribute, upserted from POLICY evidence
— see app/service.py) and evaluated_at on evidence_control_links (the staleness
signal: a link is flagged when its requirement's org-defined attribute has a
newer commitment than the link's last evaluation). See
docs/adr/013-organization-defined-commitments.md.

Revision ID: c9d0e1f2a3b4
Revises: d0e1f2a3b4c5
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "c9d0e1f2a3b4"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "org_commitments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("attribute", sa.String(), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("source_evidence_id", sa.String(), sa.ForeignKey("evidence.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("org_id", "attribute", name="uq_org_commitment"),
    )

    with op.batch_alter_table("evidence_control_links") as batch_op:
        # server_default backfills existing rows to "now" rather than null — an
        # existing link is treated as freshly evaluated, not immediately stale.
        batch_op.add_column(sa.Column("evaluated_at", sa.DateTime(), nullable=False,
                                      server_default=sa.func.now()))

    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute("ALTER TABLE org_commitments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE org_commitments FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY org_commitments_tenant_isolation ON org_commitments
        USING (org_id = current_setting('app.tenant_id', true))
        WITH CHECK (org_id = current_setting('app.tenant_id', true))
    """)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS org_commitments_tenant_isolation ON org_commitments")

    with op.batch_alter_table("evidence_control_links") as batch_op:
        batch_op.drop_column("evaluated_at")

    op.drop_table("org_commitments")
