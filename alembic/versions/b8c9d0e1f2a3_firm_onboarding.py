"""audit-firm side: onboarding requests and auditor staffing

Adds the firm's own two tables and the second RLS axis they need. Firm-owned
rows are scoped by audit_firm_id, not org_id, so they get policies keyed on a
new `app.firm_id` GUC (set by app/db.py's set_firm) rather than app.tenant_id.

`engagements` gains a firm clause on its existing policy for the same reason: a
firm admin listing its book of clients is legitimately reading rows across many
tenants, which the org-only policy would filter to nothing.

Revision ID: b8c9d0e1f2a3
Revises: a5b6c7d8e9f0
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "b8c9d0e1f2a3"
down_revision = "a5b6c7d8e9f0"
branch_labels = None
depends_on = None

FIRM_SCOPED = ["onboarding_requests", "engagement_auditors"]


def upgrade() -> None:
    op.create_table(
        "onboarding_requests",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("audit_firm_id", sa.String(), sa.ForeignKey("audit_firms.id"), nullable=False),
        sa.Column("org_name", sa.String(), nullable=False),
        sa.Column("contact_email", sa.String(), nullable=False, server_default=""),
        sa.Column("registration_detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("frameworks", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
        sa.Column("decision_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("engagement_id", sa.String(), sa.ForeignKey("engagements.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decided_by", sa.String(), nullable=False, server_default=""),
    )

    op.create_table(
        "engagement_auditors",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("engagement_id", sa.String(), sa.ForeignKey("engagements.id"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("audit_firm_id", sa.String(), sa.ForeignKey("audit_firms.id"), nullable=False),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.Column("assigned_by", sa.String(), nullable=False, server_default=""),
        sa.UniqueConstraint("engagement_id", "user_id", name="uq_engagement_auditor"),
    )

    if op.get_bind().dialect.name != "postgresql":
        return

    for table in FIRM_SCOPED:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_firm_isolation ON {table}
            USING (audit_firm_id = current_setting('app.firm_id', true))
            WITH CHECK (audit_firm_id = current_setting('app.firm_id', true))
        """)

    # A firm reads its engagements across tenants; an auditee still only reads
    # its own. Either axis matching is enough, neither being set matches nothing.
    op.execute("DROP POLICY IF EXISTS engagements_tenant_isolation ON engagements")
    op.execute("""
        CREATE POLICY engagements_tenant_isolation ON engagements
        USING (org_id = current_setting('app.tenant_id', true)
               OR audit_firm_id = current_setting('app.firm_id', true))
        WITH CHECK (org_id = current_setting('app.tenant_id', true)
                    OR audit_firm_id = current_setting('app.firm_id', true))
    """)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS engagements_tenant_isolation ON engagements")
        op.execute("""
            CREATE POLICY engagements_tenant_isolation ON engagements
            USING (org_id IS NULL OR org_id = current_setting('app.tenant_id', true))
            WITH CHECK (org_id IS NULL OR org_id = current_setting('app.tenant_id', true))
        """)
        for table in FIRM_SCOPED:
            op.execute(f"DROP POLICY IF EXISTS {table}_firm_isolation ON {table}")

    op.drop_table("engagement_auditors")
    op.drop_table("onboarding_requests")
