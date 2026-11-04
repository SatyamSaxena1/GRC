"""Repair of duplicate OPEN gaps from before the double-click fix (issue 85)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import db as db_module, gap_repair
from app.models import AuditEvent, GapRow, Organization, TaskRow
from test_demo_collectors import _sync


def _duplicate_one(s: Session) -> tuple[GapRow, GapRow]:
    orig = s.query(GapRow).filter_by(status="OPEN").order_by(GapRow.created_at, GapRow.id).first()
    dup = GapRow(link_id=orig.link_id, kind=orig.kind, attribute=orig.attribute, detail=orig.detail,
                 required_action=orig.required_action, actual_value=orig.actual_value,
                 required_value=orig.required_value, created_at=orig.created_at.replace(year=orig.created_at.year + 1))
    s.add(dup)
    s.flush()
    return orig, dup


def test_duplicates_are_reported_then_closed_once_and_nothing_is_deleted(client, bootstrap, monkeypatch):
    _sync(client, bootstrap, monkeypatch, "aws")
    with Session(db_module.engine) as s:
        org = s.query(Organization).first().id
        before = s.query(GapRow).count()
        orig, dup = _duplicate_one(s)
        s.commit()
        orig_id, dup_id = orig.id, dup.id

        assert gap_repair.repair(s, org, apply=False) == 1       # dry run reports
        assert s.get(GapRow, dup_id).status == "OPEN"            # and changes nothing

        assert gap_repair.repair(s, org, apply=True) == 1
        s.expire_all()
        assert s.get(GapRow, orig_id).status == "OPEN"
        d = s.get(GapRow, dup_id)
        assert d.status == "RESOLVED_BY_EVIDENCE" and orig_id in d.resolution_reason
        assert s.query(GapRow).count() == before + 1             # closed, never deleted
        assert s.query(AuditEvent).filter_by(action="GAP_DUPLICATE_CLOSED", entity=dup_id).count() == 1

        assert gap_repair.repair(s, org, apply=True) == 0        # second run finds nothing


def test_the_duplicates_open_task_moves_to_the_kept_gap_or_is_closed(client, bootstrap, monkeypatch):
    _sync(client, bootstrap, monkeypatch, "aws")
    with Session(db_module.engine) as s:
        org = s.query(Organization).first().id
        orig, dup = _duplicate_one(s)
        orig_tasks = s.query(TaskRow).filter_by(gap_id=orig.id, status="OPEN")
        had_task = orig_tasks.count() > 0
        dup_task = TaskRow(org_id=org, gap_id=dup.id, title="dup task", status="OPEN")
        s.add(dup_task)
        s.commit()
        task_id = dup_task.id

        gap_repair.repair(s, org, apply=True)
        s.expire_all()
        t = s.get(TaskRow, task_id)
        if had_task:
            assert t.status == "DONE"           # the kept gap already has its task
        else:
            assert t.gap_id == orig.id and t.status == "OPEN"
