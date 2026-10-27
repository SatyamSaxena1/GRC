"""verdict register (ADR-029): immutable verdict history per control

Revision ID: a9b0c1d2e3f4
Revises: f3a4b5c6d7e8

Creates verdict_records and backfills one history per existing control from what survives on
the link row: the verdict and lock, and, when the control was reopened, the single surviving
unlock_reason as a REOPENED record. Rows are marked origin=MIGRATED and say so in their
reasoning: the register does not pretend to hold history the old columns had already lost.

Backfill runs before row level security is enabled on the new table, and reads the links one
organisation at a time with app.tenant_id set, because the links table is already under
FORCE ROW LEVEL SECURITY and the owner would otherwise see no rows at all.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "a9b0c1d2e3f4"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None

NOTE = ("Recorded before the verdict register existed (ADR-029). The original reasoning, if any, "
        "is in the audit log; this entry only preserves what the link row still held.")


def _ts(at: datetime | None) -> str | None:
    return at.replace(tzinfo=None).isoformat(timespec="microseconds") if at else None


def record_hash(row: dict) -> str:
    """Must equal app.verdict_register.record_hash; tests/test_verdict_register.py checks it."""
    fields = ("id", "org_id", "link_id", "seq", "supersedes_id", "kind", "verdict", "engine_verdict",
              "rule_hash", "evaluation_hash", "engine_version", "decided_by", "decided_by_user_id",
              "engagement_id", "decided_at", "reason_code", "reasoning", "origin")
    body = {k: (_ts(row[k]) if k == "decided_at" else row[k]) for k in fields}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def upgrade() -> None:
    op.create_table(
        "verdict_records",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("link_id", sa.String(), sa.ForeignKey("evidence_control_links.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("supersedes_id", sa.String(), sa.ForeignKey("verdict_records.id"), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=True),
        sa.Column("engine_verdict", sa.String(), nullable=True),
        sa.Column("rule_hash", sa.String(), nullable=True),
        sa.Column("evaluation_hash", sa.String(), nullable=True),
        sa.Column("engine_version", sa.String(), nullable=True),
        sa.Column("decided_by", sa.String(), nullable=False),
        sa.Column("decided_by_user_id", sa.String(), nullable=True),
        sa.Column("engagement_id", sa.String(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.Column("reason_code", sa.String(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False, server_default=""),
        sa.Column("origin", sa.String(), nullable=False, server_default="LIVE"),
        sa.Column("record_hash", sa.String(), nullable=False, server_default=""),
        sa.Column("audit_chain_seq", sa.Integer(), nullable=True),
        sa.Column("audit_entry_hash", sa.String(), nullable=True),
        sa.UniqueConstraint("link_id", "seq"),
        sa.UniqueConstraint("supersedes_id"),
    )
    _backfill(op.get_bind())
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("""
        CREATE FUNCTION verdict_records_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'verdict_records is append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER verdict_records_append_only BEFORE UPDATE OR DELETE ON verdict_records
        FOR EACH ROW EXECUTE FUNCTION verdict_records_append_only()
    """)
    op.execute("ALTER TABLE verdict_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE verdict_records FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY verdict_records_tenant_isolation ON verdict_records
        USING (org_id = current_setting('app.tenant_id', true))
        WITH CHECK (org_id = current_setting('app.tenant_id', true))
    """)


def _backfill(bind) -> None:
    postgres = bind.dialect.name == "postgresql"
    records = sa.table(
        "verdict_records", *(sa.column(c, sa.DateTime() if c == "decided_at" else None) for c in (
            "id", "org_id", "link_id", "seq", "supersedes_id", "kind", "verdict", "engine_verdict",
            "rule_hash", "evaluation_hash", "engine_version", "decided_by", "decided_by_user_id",
            "engagement_id", "decided_at", "reason_code", "reasoning", "origin", "record_hash")))
    for (org_id,) in bind.execute(sa.text("SELECT id FROM organizations")).fetchall():
        if postgres:
            bind.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": org_id})
        links = bind.execute(sa.text("""
            SELECT l.id, l.verdict, l.auditor_verdict, l.locked_by_engagement_id, l.locked_at,
                   l.unlocked_at, l.unlock_reason, l.engine_verdict, l.rule_hash, l.evaluation_hash,
                   l.engine_version, l.evaluated_at
            FROM evidence_control_links l JOIN evidence e ON e.id = l.evidence_id
            WHERE e.org_id = :o
              AND (l.auditor_verdict IS NOT NULL OR l.locked_by_engagement_id IS NOT NULL
                   OR l.unlock_reason IS NOT NULL)
        """), {"o": org_id}).mappings().fetchall()
        for link in links:
            _backfill_link(bind, records, org_id, link)


def _stamp(value):
    """Raw text() queries hand SQLite datetimes back as strings."""
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def _backfill_link(bind, records, org_id: str, link) -> None:
    unlocked = _stamp(link["unlocked_at"])
    base = {
        "org_id": org_id, "link_id": link["id"], "engine_verdict": link["engine_verdict"],
        "rule_hash": link["rule_hash"], "evaluation_hash": link["evaluation_hash"],
        "engine_version": link["engine_version"], "decided_by_user_id": None,
        "origin": "MIGRATED", "reason_code": "MIGRATED", "reasoning": NOTE,
    }
    rows, prev = [], None
    verdict = link["auditor_verdict"] or (link["verdict"] if link["locked_by_engagement_id"] or unlocked else None)
    if verdict:
        # The decision's own time is only known while the control is still locked; once reopened
        # the old columns dropped it. The nearest honest stamp is the reopening, or the evaluation.
        rows.append({**base, "id": str(uuid.uuid4()), "seq": 1, "supersedes_id": None, "kind": "DECISION",
                     "verdict": verdict, "decided_by": "unknown (before the register)",
                     "engagement_id": link["locked_by_engagement_id"],
                     "decided_at": _stamp(link["locked_at"]) or unlocked or _stamp(link["evaluated_at"])})
        prev = rows[0]
    if link["unlock_reason"]:
        rows.append({**base, "id": str(uuid.uuid4()), "seq": len(rows) + 1,
                     "supersedes_id": prev["id"] if prev else None, "kind": "REOPENED", "verdict": None,
                     "decided_by": "unknown (before the register)", "engagement_id": None,
                     "decided_at": unlocked or _stamp(link["evaluated_at"]),
                     "reasoning": link["unlock_reason"]})
    for row in rows:
        row["record_hash"] = record_hash(row)
        bind.execute(records.insert().values(**row))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS verdict_records_append_only ON verdict_records")
        op.execute("DROP FUNCTION IF EXISTS verdict_records_append_only()")
    op.drop_table("verdict_records")
