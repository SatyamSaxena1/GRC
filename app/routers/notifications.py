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

from app import monitor
from app.auth import Actor, current_actor
from app.content.load import load as load_content
from app.db import get_session
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


def _request_item(r: dict) -> dict:
    verb = "requested evidence for" if r["kind"] == "EVIDENCE_REQUEST" else "asked to unlock"
    return {
        "kind": r["kind"], "severity": "info", "at": r["created_at"],
        "message": f"Your auditor {verb} {r['framework']} {r['clause']}: {r['body']}",
        "link": f"/controls/{r['org_control_id']}",
    }


def _attention_items(report: dict, checked_at: str) -> list[dict]:
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
    return items


@router.get("/notifications")
def list_notifications(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    now = datetime.now(timezone.utc).isoformat()
    items: list[dict] = []

    items += [_task_item(t) for t in controls_router.list_tasks(status="OPEN", actor=actor, db=db)]
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

    items.sort(key=lambda i: i["at"], reverse=True)
    return {"items": items, "count": len(items)}
