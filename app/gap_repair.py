"""Close duplicate OPEN gaps left in databases created before the double-click fix (issue 85).

A duplicate is two or more OPEN gaps on one evidence-control link with the same kind and attribute. The earliest
is kept. The others are never deleted: they are closed (RESOLVED_BY_EVIDENCE with a reason naming the kept row), and
each one's open task moves to the kept gap if that has none, otherwise is marked DONE. Safe to run twice: a second
run finds nothing. Dry run unless --apply:

    python -m app.gap_repair            # report only
    python -m app.gap_repair --apply
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import audit_log
from app.models import GapRow, Organization, TaskRow


def repair(db: Session, org_id: str, *, apply: bool) -> int:
    """Number of duplicate gaps found (and closed when `apply`) for one organisation."""
    from app.models import Evidence, EvidenceControlLink

    rows = (db.query(GapRow).join(EvidenceControlLink, GapRow.link_id == EvidenceControlLink.id)
            .join(Evidence, EvidenceControlLink.evidence_id == Evidence.id)
            .filter(Evidence.org_id == org_id, GapRow.status == "OPEN")
            .order_by(GapRow.created_at, GapRow.id).all())
    kept: dict[tuple, GapRow] = {}
    dupes: list[tuple[GapRow, GapRow]] = []
    for g in rows:
        key = (g.link_id, g.kind, g.attribute)
        if key in kept:
            dupes.append((g, kept[key]))
        else:
            kept[key] = g
    if not apply:
        return len(dupes)
    now = datetime.now(timezone.utc)
    for dup, keep in dupes:
        dup.status, dup.resolved_at = "RESOLVED_BY_EVIDENCE", now
        dup.resolution_reason = f"duplicate of gap {keep.id}, closed by repair"
        survivor_has_task = db.query(TaskRow).filter_by(gap_id=keep.id, status="OPEN").first() is not None
        for task in db.query(TaskRow).filter_by(gap_id=dup.id, status="OPEN"):
            if survivor_has_task:
                task.status = "DONE"
            else:
                task.gap_id, survivor_has_task = keep.id, True
        audit_log.record(db, actor="system:gap-repair", action="GAP_DUPLICATE_CLOSED", entity_type="gap",
                         entity=dup.id, org_id=org_id, detail={"kept": keep.id, "kind": dup.kind, "attribute": dup.attribute})
    db.commit()
    return len(dupes)


def main() -> int:
    from app.db import session_scope, set_tenant

    apply = "--apply" in sys.argv
    total = 0
    with session_scope() as db:
        for org in db.query(Organization).order_by(Organization.name).all():
            set_tenant(db, org.id)  # RLS scopes each pass (no-op on SQLite)
            n = repair(db, org.id, apply=apply)
            total += n
            if n:
                print(f"  {org.name}: {n} duplicate gap(s) {'closed' if apply else 'found'}")
    print(f"\n{total} duplicate gap(s) {'closed' if apply else 'found (dry run, pass --apply to close)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
