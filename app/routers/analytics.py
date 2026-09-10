"""Reuse and readiness endpoints — the product's headline numbers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import analytics, monitor
from app.auth import Actor, current_actor
from app.content.load import load as load_content
from app.db import get_session
from app.models import Organization
from app.routers import controls as controls_router
from app.routers import evidence as evidence_router

router = APIRouter(prefix="/analytics", tags=["analytics"])
CONTENT = load_content()

VERDICT_KEYS = ("PASS", "PARTIAL", "FAIL", "NO_EVIDENCE")

# Once an auditor locks a link, app/routers/audit.py::_lock overwrites
# link.verdict with the auditor's own vocabulary. Fold it back to the
# deterministic scale this rollup counts in — otherwise a locked COMPLIANT
# control 500s the dashboard on an unknown key.
_AUDITOR_VERDICT = {"COMPLIANT": "PASS", "PARTIALLY_COMPLIANT": "PARTIAL", "NON_COMPLIANT": "FAIL"}


def best_verdict(links: list[dict]) -> str:
    rank = {"PASS": 3, "PARTIAL": 2, "FAIL": 1}
    if not links:
        return "NO_EVIDENCE"
    verdicts = (_AUDITOR_VERDICT.get(l["verdict"], l["verdict"]) for l in links)
    return max(verdicts, key=lambda v: rank.get(v, 0))


def control_details(actor: Actor, db: Session) -> list[dict]:
    """Every control this actor may see, fully expanded — one DB sweep, reused
    by the dashboard, notifications and export endpoints below instead of each
    re-deriving its own version of 'which controls, with which links'."""
    summaries = controls_router.list_controls(actor=actor, db=db)
    return [controls_router.get_control(s["id"], actor=actor, db=db) for s in summaries]


@router.get("/reuse")
def reuse(effort_hours: float = analytics.DEFAULT_EFFORT_HOURS_PER_ARTEFACT,
          actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """How much duplicate evidence work this organisation has avoided."""
    return analytics.reuse_stats(db, actor.org_id, effort_hours).to_dict()


@router.get("/readiness/{framework}")
def readiness(framework: str, actor: Actor = Depends(current_actor),
              db: Session = Depends(get_session)):
    """Day-1 readiness: how much of a framework the existing evidence already
    satisfies — answerable before the organisation subscribes to it."""
    org = db.get(Organization, actor.org_id)
    if org is None:
        raise HTTPException(404)
    try:
        result = analytics.framework_readiness(
            db, actor.org_id, framework, CONTENT, subscribed=org.frameworks
        )
    except KeyError:
        raise HTTPException(404, f"unknown framework '{framework}'") from None
    return result.to_dict()


@router.get("/attention")
def attention(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """Evidence that has quietly gone stale, or uploads that never finished.

    Read-only: this reports what a human should act on and never rewrites a
    stored verdict — see app/monitor.py. Named "attention" rather than "health"
    because /health/live and /health/ready already mean infrastructure health.
    """
    org = db.get(Organization, actor.org_id)
    if org is None:
        raise HTTPException(404)
    return monitor.attention_report(db, actor.org_id, CONTENT).to_dict()


@router.get("/dashboard")
def dashboard(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """Everything Overview needs, in one round trip.

    Previously the frontend made 7 independent calls plus one `GET /controls/{id}`
    per control — a real N+1 that gets slower as an org accumulates controls (see
    docs/frontend-integration-blueprint.md's "avoid making the browser fan out").
    This still does the same O(N) work, just once, server-side, in one response.
    """
    org = db.get(Organization, actor.org_id)
    if org is None:
        raise HTTPException(404)

    details = control_details(actor, db)
    by_verdict = {k: 0 for k in VERDICT_KEYS}
    for c in details:
        v = best_verdict(c["links"])
        by_verdict[v] = by_verdict.get(v, 0) + 1  # never let an unforeseen verdict 500 the landing page

    evidence_rows = evidence_router.list_evidence(lifecycle_status="CURRENT", actor=actor, db=db)

    return {
        "controls": {
            "total": len(details),
            "locked": sum(1 for c in details if c["locked"]),
            "by_verdict": by_verdict,
        },
        "gaps_open": len(controls_router.list_gaps(status="OPEN", actor=actor, db=db)),
        "tasks_open": len(controls_router.list_tasks(status="OPEN", actor=actor, db=db)),
        "requests_open": len(controls_router.list_requests(status="OPEN", actor=actor, db=db)),
        "evidence": {
            "ready": sum(1 for e in evidence_rows if e["status"] == "READY"),
            "total": len(evidence_rows),
        },
        "reuse": analytics.reuse_stats(db, actor.org_id).to_dict(),
        "readiness": [
            analytics.framework_readiness(
                db, actor.org_id, pack.framework.code, CONTENT, subscribed=org.frameworks
            ).to_dict()
            for pack in CONTENT.packs
        ],
        "attention": monitor.attention_report(db, actor.org_id, CONTENT).to_dict(),
    }


@router.get("/readiness")
def readiness_all(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """Every framework the platform knows, subscribed or not — the comparison
    view that shows what a second framework would actually cost."""
    org = db.get(Organization, actor.org_id)
    if org is None:
        raise HTTPException(404)
    return [
        analytics.framework_readiness(
            db, actor.org_id, pack.framework.code, CONTENT, subscribed=org.frameworks
        ).to_dict()
        for pack in CONTENT.packs
    ]
