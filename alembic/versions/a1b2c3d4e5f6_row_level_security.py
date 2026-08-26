"""row level security on tenant-owned tables

Isolation enforced by the database, not only by application WHERE clauses: a
missed filter or a direct-id attack still returns nothing. Postgres only —
SQLite has no RLS, so on SQLite this migration is a documented no-op and
application scoping is the only layer (see ADR-001).

Revision ID: a1b2c3d4e5f6
Revises: fe42a8d6f5a4
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "fe42a8d6f5a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables with a direct org_id column.
DIRECT = ["evidence", "org_controls", "ai_runs", "engagements", "audit_events"]

# Tables reached through evidence; the policy follows the foreign key.
VIA_EVIDENCE = {
    "evidence_control_links": "evidence_id",
    "evidence_attributes": "evidence_id",
}


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    for table in DIRECT:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (org_id IS NULL OR org_id = current_setting('app.tenant_id', true))
            WITH CHECK (org_id IS NULL OR org_id = current_setting('app.tenant_id', true))
        """)

    for table, fk in VIA_EVIDENCE.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (EXISTS (
                SELECT 1 FROM evidence e
                WHERE e.id = {table}.{fk}
                  AND e.org_id = current_setting('app.tenant_id', true)))
        """)

    # gaps and tasks hang off links; same rule, one more hop.
    op.execute("ALTER TABLE gaps ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE gaps FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY gaps_tenant_isolation ON gaps
        USING (EXISTS (
            SELECT 1 FROM evidence_control_links l
            JOIN evidence e ON e.id = l.evidence_id
            WHERE l.id = gaps.link_id
              AND e.org_id = current_setting('app.tenant_id', true)))
    """)
    op.execute("ALTER TABLE tasks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tasks FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tasks_tenant_isolation ON tasks
        USING (EXISTS (
            SELECT 1 FROM gaps g
            JOIN evidence_control_links l ON l.id = g.link_id
            JOIN evidence e ON e.id = l.evidence_id
            WHERE g.id = tasks.gap_id
              AND e.org_id = current_setting('app.tenant_id', true)))
    """)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in [*DIRECT, *VIA_EVIDENCE, "gaps", "tasks"]:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
