"""The audit firm's own console: onboarding requests, staffing, engagements.

The rest of the app is auditee-shaped — one org, its evidence, its verdicts.
This router is the other side of the table: a firm sees many clients, and the
firm-level rows here (requests, staffing) are scoped by audit_firm_id rather
than org_id, which is why app/auth.py binds a second GUC (`set_firm`).

Two roles work here. A FIRM_ADMIN decides onboarding requests and staffs
auditors onto engagements; an AUDITOR only reads the engagements it has been
staffed on. Staffing is the access grant, not a label — see EngagementAuditor.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit_log
from app.auth import Actor, current_actor
from app.db import get_session
from app.models import (
    Engagement, EngagementAllocation, EngagementAuditor, EvidenceControlLink,
    GapRow, OnboardingRequest, OrgControl, Organization, User,
)

router = APIRouter(prefix="/firm", tags=["firm"])


def firm_actor(actor: Actor = Depends(current_actor)) -> Actor:
    """Any firm-side caller. 403 rather than 404: the console itself is not a
    secret, only its contents are."""
    if not actor.is_firm:
        raise HTTPException(403, "firm-side identity required")
    return actor


def firm_admin(actor: Actor = Depends(firm_actor)) -> Actor:
    if actor.role != "FIRM_ADMIN":
        raise HTTPException(403, "only a firm admin may do this")
    return actor


# --------------------------------------------------------------------------- onboarding


class OnboardingIn(BaseModel):
    audit_firm_id: str
    org_name: str = Field(min_length=1, max_length=200)
    contact_email: str = Field(default="", max_length=320)
    registration_detail: str = Field(default="", max_length=4000)
    frameworks: list[str] = Field(default_factory=list, max_length=50)


def _request_out(r: OnboardingRequest) -> dict:
    return {
        "id": r.id, "org_name": r.org_name, "contact_email": r.contact_email,
        "registration_detail": r.registration_detail, "frameworks": r.frameworks,
        "status": r.status, "decision_note": r.decision_note,
        "org_id": r.org_id, "engagement_id": r.engagement_id,
        "created_at": r.created_at, "decided_at": r.decided_at,
    }


@router.post("/onboarding-requests", status_code=201)
def submit_onboarding_request(body: OnboardingIn, db: Session = Depends(get_session)):
    """Unauthenticated on purpose: this is a prospect asking to be onboarded,
    before any identity for them exists. It creates no tenant — only a request
    a firm admin can approve or reject."""
    req = OnboardingRequest(**body.model_dump())
    db.add(req)
    audit_log.record(db, actor="anonymous", action="ONBOARDING_REQUESTED",
                     entity_type="onboarding_request", entity=req.id,
                     detail={"org_name": req.org_name, "frameworks": req.frameworks})
    db.commit()
    return {"id": req.id, "status": req.status}


@router.get("/onboarding-requests")
def list_onboarding_requests(status: str | None = None,
                             actor: Actor = Depends(firm_actor),
                             db: Session = Depends(get_session)):
    q = db.query(OnboardingRequest).filter_by(audit_firm_id=actor.audit_firm_id)
    if status:
        q = q.filter_by(status=status)
    rows = q.order_by(OnboardingRequest.created_at.desc()).all()
    return {"requests": [_request_out(r) for r in rows]}


def _pending(db: Session, actor: Actor, request_id: str) -> OnboardingRequest:
    req = db.get(OnboardingRequest, request_id)
    if req is None or req.audit_firm_id != actor.audit_firm_id:
        raise HTTPException(404)
    if req.status != "PENDING":
        raise HTTPException(409, f"request is already {req.status}")
    return req


class ApprovalIn(BaseModel):
    frameworks: list[str] | None = None  # defaults to what the client asked for
    note: str = ""


@router.post("/onboarding-requests/{request_id}/approve")
def approve_onboarding_request(request_id: str, body: ApprovalIn,
                               actor: Actor = Depends(firm_admin),
                               db: Session = Depends(get_session)):
    """Approval is what brings the tenant into existence: the Organization, the
    Engagement, and the allocations that bound what the auditors may see. The
    firm can narrow the requested frameworks here — the client asks, the firm
    decides."""
    req = _pending(db, actor, request_id)
    frameworks = body.frameworks if body.frameworks is not None else req.frameworks
    if not frameworks:
        raise HTTPException(422, "an approved engagement needs at least one framework")

    org = Organization(name=req.org_name, frameworks=frameworks)
    db.add(org)
    db.flush()

    engagement = Engagement(audit_firm_id=req.audit_firm_id, org_id=org.id)
    db.add(engagement)
    db.flush()
    for framework in frameworks:
        db.add(EngagementAllocation(engagement_id=engagement.id, framework=framework))

    req.status = "APPROVED"
    req.decision_note = body.note
    req.org_id = org.id
    req.engagement_id = engagement.id
    req.decided_at = datetime.now(timezone.utc)
    req.decided_by = actor.label()

    audit_log.record(db, actor=actor.label(), action="ONBOARDING_APPROVED",
                     entity_type="onboarding_request", entity=req.id, org_id=org.id,
                     detail={"org_id": org.id, "engagement_id": engagement.id,
                             "frameworks": frameworks,
                             "requested_frameworks": req.frameworks},
                     reason=body.note, request_id=actor.request_id)
    db.commit()
    return {"id": req.id, "status": req.status, "org_id": org.id,
            "engagement_id": engagement.id, "frameworks": frameworks}


class RejectionIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


@router.post("/onboarding-requests/{request_id}/reject")
def reject_onboarding_request(request_id: str, body: RejectionIn,
                              actor: Actor = Depends(firm_admin),
                              db: Session = Depends(get_session)):
    """A reason is required — a rejected prospect is entitled to one, and the
    trail is worthless without it."""
    req = _pending(db, actor, request_id)
    req.status = "REJECTED"
    req.decision_note = body.note
    req.decided_at = datetime.now(timezone.utc)
    req.decided_by = actor.label()
    audit_log.record(db, actor=actor.label(), action="ONBOARDING_REJECTED",
                     entity_type="onboarding_request", entity=req.id,
                     reason=body.note, request_id=actor.request_id)
    db.commit()
    return {"id": req.id, "status": req.status}


# --------------------------------------------------------------------------- engagements


def _visible_engagements(db: Session, actor: Actor) -> list[Engagement]:
    """A firm admin sees the firm's whole book. An auditor sees only what it is
    staffed on — the dashboard must not become a client directory."""
    q = db.query(Engagement).filter_by(audit_firm_id=actor.audit_firm_id)
    if actor.role != "FIRM_ADMIN":
        staffed = {
            row.engagement_id
            for row in db.query(EngagementAuditor).filter_by(user_id=actor.user_id)
        }
        q = q.filter(Engagement.id.in_(staffed or {""}))
    return q.all()


def _progress(db: Session, org_id: str, frameworks: set[str]) -> dict:
    """Enough for a dashboard row: how much of this client is settled, and how
    much is still open work. Counted over the engagement's allocated frameworks
    only, so a partially-allocated client does not read as half-finished."""
    controls = [c for c in db.query(OrgControl).filter_by(org_id=org_id)
                if c.framework in frameworks]
    clauses = {(c.framework, c.clause) for c in controls}
    links = [link for link in db.query(EvidenceControlLink)
             if (link.framework, link.clause) in clauses]
    link_ids = {link.id for link in links}
    open_gaps = sum(
        1 for g in db.query(GapRow).filter_by(status="OPEN") if g.link_id in link_ids
    )
    return {
        "controls": len(controls),
        "evaluated": len({(link.framework, link.clause) for link in links}),
        "locked": sum(1 for link in links if link.locked),
        "open_gaps": open_gaps,
    }


@router.get("/engagements")
def list_engagements(actor: Actor = Depends(firm_actor), db: Session = Depends(get_session)):
    """The auditor's dashboard: which clients am I on, and where does each stand."""
    out = []
    for engagement in _visible_engagements(db, actor):
        org = db.get(Organization, engagement.org_id)
        frameworks = {a.framework for a in
                      db.query(EngagementAllocation).filter_by(engagement_id=engagement.id)}
        staff = db.query(EngagementAuditor).filter_by(engagement_id=engagement.id).all()
        out.append({
            "id": engagement.id,
            "org_id": engagement.org_id,
            "org_name": org.name if org else "(deleted)",
            "status": engagement.status,
            "frameworks": sorted(frameworks),
            "auditors": [_staff_out(db, s) for s in staff],
            "progress": _progress(db, engagement.org_id, frameworks),
        })
    out.sort(key=lambda e: (e["status"] != "ACTIVE", e["org_name"].lower()))
    return {"engagements": out}


# --------------------------------------------------------------------------- staffing


def _staff_out(db: Session, row: EngagementAuditor) -> dict:
    user = db.get(User, row.user_id)
    return {"user_id": row.user_id, "email": user.email if user else "(deleted)",
            "role": user.role if user else "", "assigned_at": row.assigned_at}


class StaffIn(BaseModel):
    user_id: str


@router.post("/engagements/{engagement_id}/auditors", status_code=201)
def staff_auditor(engagement_id: str, body: StaffIn,
                  actor: Actor = Depends(firm_admin),
                  db: Session = Depends(get_session)):
    """Put one of the firm's auditors on one client. Both sides must belong to
    this firm — staffing is not a way to reach across firms."""
    engagement = db.get(Engagement, engagement_id)
    if engagement is None or engagement.audit_firm_id != actor.audit_firm_id:
        raise HTTPException(404)
    user = db.get(User, body.user_id)
    if user is None or user.audit_firm_id != actor.audit_firm_id:
        raise HTTPException(404)

    existing = db.query(EngagementAuditor).filter_by(
        engagement_id=engagement_id, user_id=body.user_id).one_or_none()
    if existing:
        return {"id": existing.id, "user_id": existing.user_id}

    row = EngagementAuditor(engagement_id=engagement_id, user_id=body.user_id,
                            audit_firm_id=actor.audit_firm_id, assigned_by=actor.label())
    db.add(row)
    audit_log.record(db, actor=actor.label(), action="AUDITOR_STAFFED",
                     entity_type="engagement", entity=engagement_id,
                     org_id=engagement.org_id,
                     detail={"user_id": body.user_id, "email": user.email},
                     request_id=actor.request_id)
    db.commit()
    return {"id": row.id, "user_id": row.user_id}


@router.delete("/engagements/{engagement_id}/auditors/{user_id}", status_code=204)
def unstaff_auditor(engagement_id: str, user_id: str,
                    actor: Actor = Depends(firm_admin),
                    db: Session = Depends(get_session)):
    """Removing the row revokes that auditor's access to this client at once —
    the same immediacy as closing an engagement."""
    row = db.query(EngagementAuditor).filter_by(
        engagement_id=engagement_id, user_id=user_id,
        audit_firm_id=actor.audit_firm_id).one_or_none()
    if row is None:
        raise HTTPException(404)
    engagement = db.get(Engagement, engagement_id)
    db.delete(row)
    audit_log.record(db, actor=actor.label(), action="AUDITOR_UNSTAFFED",
                     entity_type="engagement", entity=engagement_id,
                     org_id=engagement.org_id if engagement else None,
                     detail={"user_id": user_id}, request_id=actor.request_id)
    db.commit()


@router.get("/auditors")
def list_firm_auditors(actor: Actor = Depends(firm_actor), db: Session = Depends(get_session)):
    """The firm's own staff — who there is to assign."""
    users = db.query(User).filter_by(audit_firm_id=actor.audit_firm_id).all()
    return {"auditors": [{"id": u.id, "email": u.email, "role": u.role} for u in users]}
