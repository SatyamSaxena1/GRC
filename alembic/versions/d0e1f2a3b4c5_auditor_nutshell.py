"""auditor-only AI nutshell columns on evidence_control_links

Three columns, same provenance shape as the existing ai_model/ai_prompt_version
pair on the same table. No RLS change: same table, same policy (see
app/routers/evidence.py and app/routers/controls.py for the field-level
redaction that keeps this auditor-only — that is application-layer, not a row
policy, since every role may see the row, just not this one field).

Revision ID: d0e1f2a3b4c5
Revises: b8c9d0e1f2a3
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "d0e1f2a3b4c5"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("evidence_control_links") as batch_op:
        batch_op.add_column(sa.Column("nutshell", sa.Text(), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("nutshell_model", sa.String(), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("nutshell_prompt_version", sa.String(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("evidence_control_links") as batch_op:
        batch_op.drop_column("nutshell_prompt_version")
        batch_op.drop_column("nutshell_model")
        batch_op.drop_column("nutshell")
