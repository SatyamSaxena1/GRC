"""One feed for everything that would otherwise require logging in and looking:
open tasks, evidence/unlock requests awaiting a response, evidence going stale,
and a control whose org-defined commitment has moved since it was evaluated.

Pure read-model, no new table: every item below is derived by calling the
*existing*, already-authorization-correct list functions as plain Python (see
app/routers/analytics.py::dashboard for the same pattern) — this file adds no
new authorization rule, only reshapes what those already allow this actor to see.

Scope cut, deliberate: no persisted read/unread state. The count is "how many
open items right now," not "how many since you last looked" — that needs a
per-user "last seen" column, which is real but separate work.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import authorization, drift, monitor
from app.auth import Actor, current_actor
from app.content.load import load as load_content
from app.db import get_session
from app.models import Evidence, Organization
from app.routers import controls as controls_router
from app.routers.analytics import control_details

router = APIRouter(tags=["notifications"])
CONTENT = load_content()


def _task_item(t: dict) -> dict:
    # t["title"] already reads "FRAMEWORK CLAUSE: remediate X" for a
    # gap-derived task (app/service.py::_reconcile_gaps) — don't repeat it.
    return {
        "kind": "TASK_OPEN", "severity": t["priority"], "at": t["created_at"],
        "message": f"Open task: {t['title']}", "link": "/tasks",
    }


def _task_items(db: Session, tasks: list[dict]) -> list[dict]:
    """One item per piece of work, not per row.

    Every gap opens its own task, so one weak upload is dozens of tasks — but one
    thing to do: open that evidence and fix what it names. Counting them 1:1 made
    the nav badge read 43 for a single document and duplicated the Tasks and Gaps
    pages. Gap-derived tasks from the same evidence roll up into one item pointing
    at it; a lone one, and every manual task (someone deliberately assigned it),
    keeps its own line.
    """
    items, by_evidence = [], {}
    for t in tasks:
        if t["gap_id"] and t["evidence_id"]:
            by_evidence.setdefault(t["evidence_id"], []).append(t)
        else:
            items.append(_task_item(t))
    names = {e.id: e.original_filename for e in db.query(Evidence).filter(Evidence.id.in_(list(by_evidence)))} if by_evidence else {}
    for evidence_id, group in by_evidence.items():
        if len(group) == 1:
            items.append(_task_item(group[0]))
            continue
        items.append({
            "kind": "TASK_OPEN",
            "severity": max(group, key=lambda t: controls_router.PRIORITY_RANK.get(t["priority"], 1))["priority"],
            "at": max(t["created_at"] for t in group),
            "message": f"{names.get(evidence_id) or 'Evidence'}: {len(group)} open remediation tasks from its gaps",
            "link": f"/evidence/{evidence_id}", "count": len(group),
        })
    return items


def _request_item(r: dict) -> dict:
    verb = "requested evidence for" if r["kind"] == "EVIDENCE_REQUEST" else "asked to unlock"
    return {
        "kind": r["kind"], "severity": "info", "at": r["created_at"],
        "message": f"Your auditor {verb} {r['framework']} {r['clause']}: {r['body']}",
        "link": f"/controls/{r['org_control_id']}",
    }


def _attention_items(report: dict, checked_at: str, *, names: bool = True) -> list[dict]:
    """`names=False` is for chat delivery: a vendor's name says who the organisation buys from, so the digest
    carries one counted line instead."""
    items = []
    for e in report["expired"]:
        items.append({"kind": "EVIDENCE_EXPIRED", "severity": "high", "at": checked_at,
                      "message": f"{e['original_filename']}: {e['detail']}",
                      "link": f"/evidence/{e['evidence_id']}"})
    for e in report["expiring_soon"]:
        items.append({"kind": "EVIDENCE_EXPIRING", "severity": "medium", "at": checked_at,
                      "message": f"{e['original_filename']}: {e['detail']}",
                      "link": f"/evidence/{e['evidence_id']}"})
    for e in report["failed"]:
        items.append({"kind": "EVIDENCE_FAILED", "severity": "high", "at": checked_at,
                      "message": f"{e['original_filename']}: {e['detail']}",
                      "link": f"/evidence/{e['evidence_id']}"})
    for e in report["stuck"]:
        items.append({"kind": "EVIDENCE_STUCK", "severity": "medium", "at": checked_at,
                      "message": f"{e['original_filename']}: {e['detail']}",
                      "link": f"/evidence/{e['evidence_id']}"})
    for b in report["breach"]:
        items.append({"kind": "BREACH_DEADLINE", "severity": "high" if b["overdue"] else "medium",
                      "at": checked_at, "message": f"{b['title']} — due {b['due_at']}",
                      "link": "/dpdp/operations"})
    for d in report["dsr"]:
        items.append({"kind": "DSR_DEADLINE", "severity": "high" if d["overdue"] else "medium",
                      "at": checked_at, "message": f"{d['title']} — due {d['due_at']}",
                      "link": "/dpdp/operations"})
    vendor_rows = report.get("vendors", [])
    if vendor_rows and not names:
        items.append({"kind": "VENDOR_REVIEW", "severity": "medium", "at": checked_at,
                      "message": f"{len(vendor_rows)} vendor review(s) overdue or never done",
                      "link": "/vendors"})
    elif vendor_rows:
        for v in vendor_rows:
            items.append({"kind": "VENDOR_REVIEW", "severity": "medium", "at": checked_at,
                          "message": f"{v['title']}: {v['detail']}", "link": "/vendors"})
    return items


def _drift_items(db: Session, actor: Actor) -> list[dict]:
    """What turned worse this week and which connectors have gone quiet (ADR-058). Evidence expiring within 30 days is
    already in the attention items above. A control owner sees only the controls they own, as everywhere else."""
    allowed = authorization.visible_clauses(db, actor)
    items = [{"kind": "CONTROL_WORSE", "severity": "high" if c["now"] == "FAIL" else "medium", "at": c["changed_at"],
              "message": f"{c['framework']} {c['clause']} turned worse this week: {c['was']} to {c['now']}",
              "link": f"/controls/{c['control_id']}" if c["control_id"] else "/controls"}
             for c in drift.controls_worse(db, actor.org_id)
             if allowed is None or (c["framework"], c["clause"]) in allowed]
    org = db.get(Organization, actor.org_id)
    checked = datetime.now(timezone.utc).isoformat()
    items += [{"kind": "CONNECTOR_STALE", "severity": "medium", "at": checked,
               "message": f"{c['label']} has not been refreshed in {c['days']} days",
               "link": "/connections"} for c in (drift.stale_connectors(db, org) if org else [])]  # a stale sign-in names no organisation
    return items


@router.get("/notifications")
def list_notifications(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    now = datetime.now(timezone.utc).isoformat()
    items: list[dict] = []

    items += _task_items(db, controls_router.list_tasks(status="OPEN", actor=actor, db=db))
    items += [_request_item(r) for r in controls_router.list_requests(status="OPEN", actor=actor, db=db)]

    report = monitor.attention_report(db, actor.org_id, CONTENT).to_dict()
    items += _attention_items(report, report["checked_at"])

    for control in control_details(actor, db):
        for link in control["links"]:
            if link.get("commitment_stale"):
                items.append({
                    "kind": "COMMITMENT_STALE", "severity": "medium", "at": now,
                    "message": f"{control['framework']} {control['clause']}: {link['stale_reason']}",
                    "link": f"/controls/{control['id']}",
                })

    items += _drift_items(db, actor)

    items.sort(key=lambda i: i["at"], reverse=True)
    return {"items": items, "count": len(items)}
