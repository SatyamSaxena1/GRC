"""The trust page (ADR-039): a public, content-free summary an organisation chooses to publish.

Off until an organisation admin publishes it. The page is reached by an unguessable link, shows counts and
percentages only (never a name, file, gap, task or evidence), is marked noindex, and stops working the
moment it is unpublished. The admin sees exactly what the public sees before sharing the link.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import analytics, audit_log
from app.auth import Actor, current_actor
from app.content.load import load as load_content
from app.db import get_session, set_tenant
from app.models import Evidence, Organization
from app.routers import analytics as analytics_router

router = APIRouter(prefix="/trust-settings", tags=["trust"])
public_router = APIRouter(prefix="/public/trust", tags=["trust"])
CONTENT = load_content()


def summary(db: Session, org: Organization) -> dict:
    """What the public may see. Built from the same figures the Overview shows, read as a viewer."""
    viewer = Actor(org_id=org.id, role="COMPLIANCE_VIEWER")
    details = analytics_router.control_details(viewer, db)
    by = {k: 0 for k in analytics_router.VERDICT_KEYS}
    for c in details:
        v = analytics_router.best_verdict(c["links"])
        by[v] = by.get(v, 0) + 1
    last = db.query(func.max(Evidence.created_at)).filter_by(org_id=org.id).scalar()
    return {
        "organisation": org.name,
        "controls": {"total": len(details), "reviewed_and_locked_by_an_auditor": sum(1 for c in details if c["locked"]),
                     "meeting_requirements": by["PASS"], "partly_meeting": by["PARTIAL"],
                     "not_meeting": by["FAIL"], "awaiting_evidence": by["NO_EVIDENCE"]},
        "frameworks": [
            {"framework": f.framework, "requirements_met": f.satisfied, "requirements": f.total_requirements,
             "readiness_percent": round(f.readiness * 100)}
            for f in (analytics.framework_readiness(db, org.id, code, CONTENT, subscribed=org.frameworks)
                      for code in org.frameworks)],
        "evidence_last_collected": last.date().isoformat() if last else None,
        "practices": ["Verdicts are decided by fixed, versioned rules, not by an AI model.",
                      "A named human auditor reviews and locks each verdict.",
                      "Every action is recorded in a tamper-evident, hash-chained log."],
    }


def _admin(actor: Actor) -> Actor:
    if actor.role != "ORG_ADMIN" or actor.engagement_id:
        raise HTTPException(403, "only an organisation admin can publish or unpublish the trust page")
    return actor


def _state(db: Session, org: Organization) -> dict:
    return {"published": org.trust_token is not None, "token": org.trust_token, "preview": summary(db, org)}


@router.get("")
def trust_state(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    return _state(db, db.get(Organization, _admin(actor).org_id))


@router.post("/publish")
def publish(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    org = db.get(Organization, _admin(actor).org_id)
    if org.trust_token is None:
        org.trust_token = secrets.token_urlsafe(18)
        audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="TRUST_PAGE_PUBLISHED",
                         entity_type="organization", entity=org.id, org_id=org.id)  # never the token itself
        db.commit()
    return _state(db, org)


@router.post("/unpublish")
def unpublish(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    org = db.get(Organization, _admin(actor).org_id)
    if org.trust_token is not None:
        org.trust_token = None
        audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="TRUST_PAGE_UNPUBLISHED",
                         entity_type="organization", entity=org.id, org_id=org.id)
        db.commit()
    return _state(db, org)


@public_router.get("/{token}")
def public_page(token: str, response: Response, db: Session = Depends(get_session)):
    """No sign-in. An unknown, malformed or withdrawn link is the same 404."""
    org = db.query(Organization).filter_by(trust_token=token).one_or_none() if len(token) >= 16 else None
    if org is None:
        raise HTTPException(404)
    set_tenant(db, org.id)  # the figures live in tenant tables under row level security
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Cache-Control"] = "no-store"
    return summary(db, org)
