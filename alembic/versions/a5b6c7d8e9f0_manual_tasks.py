"""allow tasks without a gap (manual assignment)

Adds org_id (direct tenant column, replacing the through-gap chain for RLS),
org_control_id (optional context), description and created_by to tasks, and
makes gap_id nullable so an org admin can hand a task straight to an employee
without an evaluator-detected gap behind it.

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "a5b6c7d8e9f0"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(sa.Column("org_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("org_control_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("description", sa.Text(), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("created_by", sa.String(), nullable=False, server_default=""))

    # Backfill org_id/org_control_id for existing gap-derived tasks from the
    # chain the old RLS policy used (gap -> link -> evidence). Nothing to
    # backfill for org_control_id if the matching org_control row somehow
    # doesn't exist (pre-dates this app version) — it stays null, same as a
    # manual task with no control context.
    op.execute("""
        UPDATE tasks SET org_id = (
            SELECT e.org_id FROM gaps g
            JOIN evidence_control_links l ON l.id = g.link_id
            JOIN evidence e ON e.id = l.evidence_id
            WHERE g.id = tasks.gap_id
        )
        WHERE org_id IS NULL AND gap_id IS NOT NULL
    """)
    op.execute("""
        UPDATE tasks SET org_control_id = (
            SELECT oc.id FROM gaps g
            JOIN evidence_control_links l ON l.id = g.link_id
            JOIN org_controls oc ON oc.org_id = tasks.org_id
                                 AND oc.framework = l.framework AND oc.clause = l.clause
            WHERE g.id = tasks.gap_id
        )
        WHERE org_control_id IS NULL AND gap_id IS NOT NULL
    """)

    with op.batch_alter_table("tasks") as batch_op:
        batch_op.alter_column("org_id", nullable=False)
        batch_op.alter_column("gap_id", nullable=True)
        batch_op.create_foreign_key("fk_tasks_org_id", "organizations", ["org_id"], ["id"])
        batch_op.create_foreign_key("fk_tasks_org_control_id", "org_controls", ["org_control_id"], ["id"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tasks_tenant_isolation ON tasks")
        op.execute("""
            CREATE POLICY tasks_tenant_isolation ON tasks
            USING (org_id IS NULL OR org_id = current_setting('app.tenant_id', true))
            WITH CHECK (org_id IS NULL OR org_id = current_setting('app.tenant_id', true))
        """)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tasks_tenant_isolation ON tasks")
        op.execute("""
            CREATE POLICY tasks_tenant_isolation ON tasks
            USING (EXISTS (
                SELECT 1 FROM gaps g
                JOIN evidence_control_links l ON l.id = g.link_id
                JOIN evidence e ON e.id = l.evidence_id
                WHERE l.id = tasks.gap_id
                  AND e.org_id = current_setting('app.tenant_id', true)))
        """)
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_constraint("fk_tasks_org_control_id", type_="foreignkey")
        batch_op.drop_constraint("fk_tasks_org_id", type_="foreignkey")
        batch_op.alter_column("gap_id", nullable=False)
        batch_op.drop_column("created_by")
        batch_op.drop_column("description")
        batch_op.drop_column("org_control_id")
        batch_op.drop_column("org_id")
