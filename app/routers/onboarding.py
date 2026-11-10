"""The first-week checklist (ADR-058). Read-only: every step is derived from data, so there is nothing to write."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import onboarding
from app.auth import Actor, current_actor
from app.db import get_session
from app.models import Organization

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("")
def my_checklist(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    # The steps are an admin's to do (invite, publish, assign), so only an organisation admin is shown them.
    if actor.role != "ORG_ADMIN" or actor.engagement_id or not actor.org_id:
        raise HTTPException(403, "the first-week checklist is for an organisation admin")
    org = db.get(Organization, actor.org_id)
    if org is None:
        raise HTTPException(404)  # as the dashboard does for a sign-in that names an organisation that is not here
    return onboarding.checklist(db, org, actor.user_id)
