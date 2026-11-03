"""Read the weekly compliance report in the app (ADR-041). The same figures the cron posts to the webhook."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app import notify, reports
from app.auth import Actor, current_actor
from app.db import get_session
from app.models import Organization

router = APIRouter(prefix="/reports", tags=["reports"])


def _org(actor: Actor, db: Session) -> Organization:
    # Aggregates across the whole organisation, so only the roles that already see all of it.
    if actor.role not in ("ORG_ADMIN", "COMPLIANCE_VIEWER") or actor.engagement_id or not actor.org_id:
        raise HTTPException(403, "the weekly report is for an organisation admin or compliance viewer")
    return db.get(Organization, actor.org_id)


@router.get("/weekly")
def weekly(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    report = reports.build(db, _org(actor, db))
    return {**report, "text": reports.text(report),
            "delivery": {"webhook_configured": notify.enabled(),
                         "schedule": os.environ.get("WEEKLY_REPORT_SCHEDULE", "Mondays 07:15 IST")}}


@router.get("/weekly.md", response_class=PlainTextResponse)
def weekly_markdown(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    return reports.markdown(reports.build(db, _org(actor, db)))
