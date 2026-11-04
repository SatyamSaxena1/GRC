"""vendor reports (ADR-043): SOC 2 / ISO 27001 reports attached to a vendor, under row level security

Additive: a new table. Whether a report counts as an attestation is decided at read time by a fixed rule
(app/vendors.py::attests) from its type and the valid-until date the uploader states; nothing derived is
stored. Files live in object storage like evidence, and are never deleted.

Revision ID: c47609bb7698
Revises: 577e02b379a0
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c47609bb7698"
down_revision = "577e02b379a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vendor_reports",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("vendor_id", sa.String(), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("report_type", sa.String(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("uploaded_by", sa.String(), nullable=False, server_default=""),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_vendor_reports_vendor", "vendor_reports", ["org_id", "vendor_id"])
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE vendor_reports ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE vendor_reports FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY vendor_reports_tenant_isolation ON vendor_reports
        USING (org_id = current_setting('app.tenant_id', true))
        WITH CHECK (org_id = current_setting('app.tenant_id', true))
    """)


def downgrade() -> None:
    op.drop_index("ix_vendor_reports_vendor", table_name="vendor_reports")
    op.drop_table("vendor_reports")
