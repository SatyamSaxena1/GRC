"""Reuse and readiness endpoints — the product's headline numbers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import analytics
from app.auth import Actor, current_actor
from app.content.load import load as load_content
from app.db import get_session
from app.models import Organization

router = APIRouter(prefix="/analytics", tags=["analytics"])
CONTENT = load_content()


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
