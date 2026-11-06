"""Bootstrap endpoints for the slice: orgs, firms, users, engagements, assignments.
No self-serve signup or role UI — that is product surface, not this slice."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import audit_log, auth0_admin, mailer, welcome
from app.auth import Actor, admin_or_actor, require_admin
from app.db import get_session, identity_lookup, set_firm, set_tenant
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
    if actor is not None and actor.role == "ORG_ADMIN" and not body.org_id and not body.audit_firm_id:
        body.org_id = actor.org_id  # "invite into my own organisation"; the SPA does not hold the org id
    if actor is not None:
        into_own_org = body.org_id and actor.org_id == body.org_id and actor.role == "ORG_ADMIN"
        into_own_firm = (body.audit_firm_id and actor.audit_firm_id == body.audit_firm_id
                         and actor.role == "FIRM_ADMIN")
        if not (into_own_org or into_own_firm):
            raise HTTPException(403, "you may only invite users into your own organisation or firm")
    # Sign-in matches by exact email, so two rows for one address would lock both people out.
    # users is under RLS: the check has to read across tenants, which identity_lookup allows.
    with identity_lookup(db):
        taken = db.query(User).filter(func.lower(User.email) == body.email.strip().lower()).first()
    if taken is not None:
        raise HTTPException(409, "a user with this email already exists")
    # The operator key binds no tenant, and users is under RLS: write the row inside the
    # org or firm it belongs to (a signed-in caller is already bound to that same one).
    set_tenant(db, body.org_id)
    set_firm(db, body.audit_firm_id)
    # The login is created first (ADR-047): if the sign-in service fails, no half-invited person is left behind.
    link = None
    if auth0_admin.enabled():
        try:
            link = auth0_admin.invite(body.email, os.environ.get("NOTIFY_LINK_BASE_URL", ""))
        except auth0_admin.Auth0Error as exc:
            raise HTTPException(502, f"could not create their login: {exc}") from None
    user = User(**body.model_dump())
    db.add(user)
    db.commit()
    out = {"id": user.id, "role": user.role}
    if mailer.enabled():
        # One welcome email, once, at sign-up (ADR-052): their first steps for their role, a way to reach a person, and the
        # one-time sign-in link when a login was just made. When it is sent, the admin never handles the link. If it cannot
        # be sent, the link is returned instead so the invite is not lost, with the reason (an error class, never a message).
        org = db.get(Organization, user.org_id) if user.org_id else db.get(AuditFirm, user.audit_firm_id)
        subject, text = welcome.compose(user.role, getattr(org, "name", ""), link, os.environ.get("NOTIFY_LINK_BASE_URL", ""))
        ok, reason = mailer.send(body.email, subject, text)
        if ok:
            return JSONResponse({**out, "emailed": True}, headers={"Cache-Control": "no-store"})
        out["email_error"] = reason
    if link is None:
        return out
    # The link is a one-time credential: shown once, never stored or logged, and never cached.
    return JSONResponse({**out, "password_link": link}, headers={"Cache-Control": "no-store"})


ORG_ROLES = ("ORG_ADMIN", "CONTROL_OWNER", "COMPLIANCE_VIEWER")
FIRM_ROLES = ("FIRM_ADMIN", "AUDITOR")


def _team_admin(actor: Actor | None) -> Actor:
    """Only an org admin (own org) or a firm admin (own firm), signed in as themselves."""
    if actor is None or actor.engagement_id or actor.role not in ("ORG_ADMIN", "FIRM_ADMIN"):
        raise HTTPException(403, "only an organisation admin or a firm admin can manage users")
    return actor


def _team_view(u: User) -> dict:
    return {"id": u.id, "email": u.email, "role": u.role, "active": u.active}


@router.get("/users")
def list_users(actor: Actor | None = Depends(admin_or_actor), db: Session = Depends(get_session)):
    """The caller's own organisation's users, or their own firm's. RLS already limits the rows;
    the filter says which side."""
    actor = _team_admin(actor)
    q = db.query(User)
    q = q.filter_by(org_id=actor.org_id) if actor.role == "ORG_ADMIN" else q.filter_by(audit_firm_id=actor.audit_firm_id)
    return [_team_view(u) for u in q.order_by(User.email)]


class UserPatch(BaseModel):
    role: str | None = None
    active: bool | None = None


@router.patch("/users/{user_id}")
def update_user(user_id: str, body: UserPatch, actor: Actor | None = Depends(admin_or_actor),
                db: Session = Depends(get_session)):
    """Change a teammate's role, or deactivate or reactivate them (ADR-036). Deactivation ends
    their access at the next request, keeps their history, and is audited with before and after."""
    actor = _team_admin(actor)
    user = db.get(User, user_id)  # RLS: another tenant's user is simply not there
    own_side = (user is not None and (user.org_id == actor.org_id if actor.role == "ORG_ADMIN"
                                      else user.audit_firm_id == actor.audit_firm_id))
    if not own_side:
        raise HTTPException(404)

    side_roles, admin_role = (ORG_ROLES, "ORG_ADMIN") if actor.role == "ORG_ADMIN" else (FIRM_ROLES, "FIRM_ADMIN")
    if body.role is not None and body.role not in side_roles:
        raise HTTPException(422, f"role must be one of {', '.join(side_roles)}")
    new_role = body.role if body.role is not None else user.role
    new_active = body.active if body.active is not None else user.active
    if user.id == actor.user_id and not new_active:
        raise HTTPException(409, "you cannot deactivate your own account")

    stays_admin = new_active and new_role == admin_role
    if user.role == admin_role and user.active and not stays_admin:
        others = db.query(User).filter(User.id != user.id, User.role == admin_role, User.active.is_(True))
        others = others.filter_by(org_id=user.org_id) if user.org_id else others.filter_by(audit_firm_id=user.audit_firm_id)
        if others.count() == 0:
            raise HTTPException(409, "this is the last active admin; make someone else an admin first")

    before = {"role": user.role, "active": user.active}
    user.role, user.active = new_role, new_active
    after = {"role": user.role, "active": user.active}
    detail = {"email": user.email}
    if before["active"] != after["active"] and auth0_admin.enabled():
        # Our own check already ends access at the next request. Blocking the login as well is belt and braces,
        # so a failure there is recorded, not allowed to stop the deactivation.
        try:
            detail["login_found"] = auth0_admin.set_blocked(user.email, not user.active)
            detail["login_blocked"] = not user.active
        except auth0_admin.Auth0Error as exc:
            detail["login_block_error"] = str(exc)
    if before != after:
        audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="USER_UPDATED",
                         entity_type="user", entity=user.id, org_id=user.org_id,
                         detail=detail, before=before, after=after)
    db.commit()
    return _team_view(user)


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
    audit_log.record(db, actor=actor.label() if actor is not None else "admin", action="CONTROL_ASSIGNED",
                     entity_type="org_control",
                     entity=body.org_control_id,
                     org_id=control.org_id if control else None,
                     detail={"user_id": body.user_id})
    db.commit()
    return {"id": assignment.id}
