"""Bootstrap endpoints for the slice: orgs, firms, users, engagements, assignments.
No self-serve signup or role UI — that is product surface, not this slice."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import audit_log
from app.db import get_session
from app.models import (
    AuditFirm, ControlAssignment, Engagement, EngagementAllocation, OrgControl,
    Organization, User,
)

router = APIRouter(prefix="/admin", tags=["admin"])


class OrgIn(BaseModel):
    name: str
    frameworks: list[str]


@router.post("/organizations")
def create_org(body: OrgIn, db: Session = Depends(get_session)):
    org = Organization(name=body.name, frameworks=body.frameworks)
    db.add(org)
    db.commit()
    return {"id": org.id}


class FirmIn(BaseModel):
    name: str


@router.post("/audit-firms")
def create_firm(body: FirmIn, db: Session = Depends(get_session)):
    firm = AuditFirm(name=body.name)
    db.add(firm)
    db.commit()
    return {"id": firm.id}


class UserIn(BaseModel):
    email: str
    org_id: str | None = None
    audit_firm_id: str | None = None
    role: str = "CONTROL_OWNER"


@router.post("/users")
def create_user(body: UserIn, db: Session = Depends(get_session)):
    user = User(**body.model_dump())
    db.add(user)
    db.commit()
    return {"id": user.id, "role": user.role}


class EngagementIn(BaseModel):
    audit_firm_id: str
    org_id: str
    frameworks: list[str] = []


@router.post("/engagements")
def create_engagement(body: EngagementIn, db: Session = Depends(get_session)):
    engagement = Engagement(audit_firm_id=body.audit_firm_id, org_id=body.org_id)
    db.add(engagement)
    db.flush()
    for framework in body.frameworks:
        db.add(EngagementAllocation(engagement_id=engagement.id, framework=framework))
    audit_log.record(db, actor="admin", action="ENGAGEMENT_OPENED", entity_type="engagement",
                     entity=engagement.id, org_id=body.org_id,
                     detail={"frameworks": body.frameworks})
    db.commit()
    return {"id": engagement.id, "frameworks": body.frameworks}


@router.post("/engagements/{engagement_id}/close")
def close_engagement(engagement_id: str, db: Session = Depends(get_session)):
    """Closing revokes auditor access immediately; the records stay for defensibility."""
    engagement = db.get(Engagement, engagement_id)
    if engagement is None:
        raise HTTPException(404)
    engagement.status = "CLOSED"
    engagement.closed_at = datetime.now(timezone.utc)
    audit_log.record(db, actor="admin", action="ENGAGEMENT_CLOSED", entity_type="engagement",
                     entity=engagement.id, org_id=engagement.org_id)
    db.commit()
    return {"id": engagement.id, "status": engagement.status}


class ControlIn(BaseModel):
    org_id: str
    framework: str
    clause: str


@router.post("/controls")
def create_control(body: ControlIn, db: Session = Depends(get_session)):
    control = db.query(OrgControl).filter_by(**body.model_dump()).one_or_none()
    if control is None:
        control = OrgControl(**body.model_dump())
        db.add(control)
        db.commit()
    return {"id": control.id}


class AssignmentIn(BaseModel):
    org_control_id: str
    user_id: str


@router.post("/control-assignments")
def assign_control(body: AssignmentIn, db: Session = Depends(get_session)):
    existing = db.query(ControlAssignment).filter_by(**body.model_dump()).one_or_none()
    if existing:
        return {"id": existing.id}
    assignment = ControlAssignment(**body.model_dump())
    db.add(assignment)
    control = db.get(OrgControl, body.org_control_id)
    audit_log.record(db, actor="admin", action="CONTROL_ASSIGNED", entity_type="org_control",
                     entity=body.org_control_id,
                     org_id=control.org_id if control else None,
                     detail={"user_id": body.user_id})
    db.commit()
    return {"id": assignment.id}
