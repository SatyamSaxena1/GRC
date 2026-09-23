"""Bootstrap endpoints for the slice: orgs, firms, users, engagements, assignments.
No self-serve signup or role UI — that is product surface, not this slice."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import audit_log
from app.auth import Actor, admin_or_actor, require_admin
from app.db import get_session, set_firm, set_tenant
from app.models import (
    AuditFirm, ControlAssignment, Engagement, EngagementAllocation, OrgControl,
    Organization, User,
)

router = APIRouter(prefix="/admin", tags=["admin"])


class OrgIn(BaseModel):
    name: str
    frameworks: list[str]


@router.post("/organizations", dependencies=[Depends(require_admin)])
def create_org(body: OrgIn, db: Session = Depends(get_session)):
    org = Organization(name=body.name, frameworks=body.frameworks)
    db.add(org)
    db.commit()
    return {"id": org.id}


class FirmIn(BaseModel):
    name: str


@router.post("/audit-firms", dependencies=[Depends(require_admin)])
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
def create_user(body: UserIn, actor: Actor | None = Depends(admin_or_actor),
                db: Session = Depends(get_session)):
    """The operator key (actor=None) may create any user, org- or firm-side —
    that's how a brand-new org/firm gets its first admin. A signed-in caller
    may only invite into their own org (as its ORG_ADMIN) or their own firm
    (as its FIRM_ADMIN); everything else is someone else's tenant."""
    if actor is not None:
        into_own_org = body.org_id and actor.org_id == body.org_id and actor.role == "ORG_ADMIN"
        into_own_firm = (body.audit_firm_id and actor.audit_firm_id == body.audit_firm_id
                         and actor.role == "FIRM_ADMIN")
        if not (into_own_org or into_own_firm):
            raise HTTPException(403, "you may only invite users into your own organisation or firm")
    user = User(**body.model_dump())
    db.add(user)
    db.commit()
    return {"id": user.id, "role": user.role}


class EngagementIn(BaseModel):
    audit_firm_id: str
    org_id: str
    frameworks: list[str] = []


@router.post("/engagements", dependencies=[Depends(require_admin)])
def create_engagement(body: EngagementIn, db: Session = Depends(get_session)):
    # engagements carries FORCE ROW LEVEL SECURITY (org_id OR audit_firm_id
    # match, alembic b8c9d0e1f2a3) — no actor here to derive either GUC from,
    # so both are set explicitly from the body or the insert's WITH CHECK sees
    # neither and Postgres rejects it outright.
    set_tenant(db, body.org_id)
    set_firm(db, body.audit_firm_id)
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
def close_engagement(engagement_id: str, org_id: str | None = None, audit_firm_id: str | None = None,
                     actor: Actor | None = Depends(admin_or_actor),
                     db: Session = Depends(get_session)):
    """Closing revokes auditor access immediately; the records stay for defensibility.

    engagements is FORCE ROW LEVEL SECURITY (org_id OR audit_firm_id match) —
    the row is invisible to db.get() below until one of those GUCs is set. An
    authenticated caller's own org/firm already did that (admin_or_actor); the
    operator-key path has no actor, so it must be told which tenant via a
    query param — it cannot look the engagement up to find out first."""
    if actor is None and (org_id or audit_firm_id):
        set_tenant(db, org_id)
        set_firm(db, audit_firm_id)
    engagement = db.get(Engagement, engagement_id)
    if engagement is None:
        raise HTTPException(404)
    if actor is not None:
        is_own_org = actor.role == "ORG_ADMIN" and actor.org_id == engagement.org_id
        is_own_firm = actor.role == "FIRM_ADMIN" and actor.audit_firm_id == engagement.audit_firm_id
        if not (is_own_org or is_own_firm):
            raise HTTPException(403, "you may only close your own engagements")
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
def create_control(body: ControlIn, actor: Actor | None = Depends(admin_or_actor),
                   db: Session = Depends(get_session)):
    if actor is not None:
        if not (actor.role == "ORG_ADMIN" and actor.org_id == body.org_id):
            raise HTTPException(403, "you may only register controls for your own organisation")
    else:
        # org_controls is FORCE ROW LEVEL SECURITY (alembic a1b2c3d4e5f6); the
        # operator key path has no actor to have already set this via
        # admin_or_actor, so the insert's WITH CHECK would otherwise reject it.
        set_tenant(db, body.org_id)
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
def assign_control(body: AssignmentIn, actor: Actor | None = Depends(admin_or_actor),
                   db: Session = Depends(get_session)):
    if actor is not None:
        control = db.get(OrgControl, body.org_control_id)
        if control is None or not (actor.role == "ORG_ADMIN" and actor.org_id == control.org_id):
            raise HTTPException(403, "you may only assign controls within your own organisation")
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
