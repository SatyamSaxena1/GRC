"""The policy library (ADR-056): the organisation's own policies, approved by a named person, and accepted by each
member of the team.

Three facts are kept, and nothing is inferred: the text of each version, who approved it and when, and who accepted
which version and when. Changing the text makes a new version that must be approved and accepted again; earlier
acceptances stay as history. An organisation admin writes and approves; every member reads and accepts for themselves.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit_log
from app.auth import Actor, current_actor
from app.db import get_session
from app.models import PolicyAcceptance, PolicyDoc, PolicyVersion, User
from app.routers import templates

router = APIRouter(prefix="/policies", tags=["policies"])

REVIEW_EVERY_DAYS = 365   # an approved policy is due for review a year after approval
DUE_SOON_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _member(actor: Actor) -> Actor:
    """Anyone on the organisation's own side. An auditor reads evidence, not the internal policy library."""
    if actor.engagement_id or not actor.org_id:
        raise HTTPException(403, "the policy library is for members of the organisation")
    return actor


def _admin(actor: Actor) -> Actor:
    if _member(actor).role != "ORG_ADMIN":
        raise HTTPException(403, "only an organisation admin may write or approve a policy")
    return actor


def review_state(status: str, review_due: date | None, today: date | None = None) -> str:
    """NOT_APPROVED | CURRENT | DUE_SOON | OVERDUE, from the stored review date alone."""
    if status != "APPROVED" or review_due is None:
        return "NOT_APPROVED"
    left = (review_due - (today or date.today())).days
    return "OVERDUE" if left < 0 else "DUE_SOON" if left <= DUE_SOON_DAYS else "CURRENT"


def _people(db: Session, org_id: str) -> dict[str, str]:
    """The active members who are expected to accept: id -> email."""
    return {u.id: u.email for u in db.query(User).filter(User.org_id == org_id, User.active.is_(True))}


def _out(p: PolicyDoc, people: dict[str, str], accepted: set[str], actor: Actor, body: bool = False) -> dict:
    done = accepted & set(people)                                # a deactivated person no longer counts either way
    out = {
        "id": p.id, "title": p.title, "version": p.version, "status": p.status,
        "approved_by": p.approved_by, "approved_at": p.approved_at.isoformat() if p.approved_at else None,
        "review_due": p.review_due.isoformat() if p.review_due else None,
        "review": review_state(p.status, p.review_due),
        "people": len(people), "accepted": len(done),
        "accepted_by_me": bool(actor.user_id and actor.user_id in accepted),
    }
    if actor.role == "ORG_ADMIN":                                 # who is still to accept is for the admin only
        out["waiting_on"] = sorted(email for uid, email in people.items() if uid not in done) if p.status == "APPROVED" else []
    if body:
        out["body"] = p.body
    return out


def _accepted(db: Session, p: PolicyDoc) -> set[str]:
    return {a.user_id for a in db.query(PolicyAcceptance).filter_by(org_id=p.org_id, policy_id=p.id, version=p.version)}


def _load(db: Session, actor: Actor, policy_id: str) -> PolicyDoc:
    p = db.get(PolicyDoc, policy_id)
    if p is None or p.org_id != actor.org_id:
        raise HTTPException(404)
    return p


class PolicyIn(BaseModel):
    """Either a template to start from, or a title and text of your own."""
    template_id: str | None = None
    title: str | None = Field(default=None, min_length=3, max_length=160)
    body: str | None = Field(default=None, min_length=20, max_length=100_000)


class Seen(BaseModel):
    """The version on the caller's screen. Approving or accepting anything else is refused, so nobody approves or
    accepts text that changed after they read it."""
    version: int


def _same_version(p: PolicyDoc, seen: Seen) -> None:
    if seen.version != p.version:
        raise HTTPException(409, f"this policy is now at version {p.version}; open it again and read the new text")


class PolicyEdit(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=160)
    body: str | None = Field(default=None, min_length=20, max_length=100_000)


@router.get("")
def list_policies(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    _member(actor)
    people = _people(db, actor.org_id)
    rows = db.query(PolicyDoc).filter_by(org_id=actor.org_id).order_by(PolicyDoc.title).all()
    if actor.role != "ORG_ADMIN":
        rows = [p for p in rows if p.status == "APPROVED"]       # a draft is the admin's until it is approved
    # can_manage tells the page whether to offer the admin's buttons; the routes above decide for real.
    return {"can_manage": actor.role == "ORG_ADMIN", "policies": [_out(p, people, _accepted(db, p), actor) for p in rows]}


@router.get("/{policy_id}")
def get_policy(policy_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    p = _load(db, _member(actor), policy_id)
    if p.status != "APPROVED" and actor.role != "ORG_ADMIN":
        raise HTTPException(404)
    return _out(p, _people(db, actor.org_id), _accepted(db, p), actor, body=True)


@router.post("")
def add_policy(body: PolicyIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    _admin(actor)
    if body.template_id:
        if body.template_id not in templates.TEMPLATES:
            raise HTTPException(422, "unknown template")
        title, text = body.title or templates.TEMPLATES[body.template_id][0], templates.render(body.template_id)[0]
    elif body.title and body.body:
        title, text = body.title, body.body
    else:
        raise HTTPException(422, "give a template, or a title and the policy text")
    p = PolicyDoc(org_id=actor.org_id, title=title.strip(), body=text, created_by=actor.label(), created_at=_now())
    db.add(p)
    db.flush()
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="POLICY_ADDED", entity_type="policy",
                     entity=p.id, org_id=actor.org_id, after={"title": p.title, "version": 1, "template": body.template_id})
    db.commit()
    return _out(p, _people(db, actor.org_id), set(), actor, body=True)


@router.put("/{policy_id}")
def edit_policy(policy_id: str, body: PolicyEdit, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """A change to the title or text is a new version: it goes back to draft and everyone accepts it again."""
    p = _load(db, _admin(actor), policy_id)
    title, text = (body.title or p.title).strip(), body.body if body.body is not None else p.body
    if (title, text) != (p.title, p.body):
        before = {"title": p.title, "version": p.version, "status": p.status}
        p.title, p.body, p.version, p.status = title, text, p.version + 1, "DRAFT"
        p.approved_by, p.approved_at, p.review_due = "", None, None
        audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="POLICY_EDITED",
                         entity_type="policy", entity=p.id, org_id=actor.org_id, before=before,
                         after={"title": p.title, "version": p.version, "status": p.status})
        db.commit()
    return _out(p, _people(db, actor.org_id), _accepted(db, p), actor, body=True)


@router.post("/{policy_id}/approve")
def approve_policy(policy_id: str, seen: Seen, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    p = _load(db, _admin(actor), policy_id)
    _same_version(p, seen)
    if p.status != "APPROVED":
        now = _now()
        p.status, p.approved_by, p.approved_at = "APPROVED", actor.label(), now
        p.review_due = (now + timedelta(days=REVIEW_EVERY_DAYS)).date()
        # The approved words are kept for good: a later edit replaces the working text, never this row.
        db.add(PolicyVersion(org_id=p.org_id, policy_id=p.id, version=p.version, title=p.title, body=p.body,
                             sha256=hashlib.sha256(p.body.encode()).hexdigest(), approved_by=p.approved_by, approved_at=now))
        audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="POLICY_APPROVED",
                         entity_type="policy", entity=p.id, org_id=actor.org_id,
                         after={"version": p.version, "review_due": p.review_due.isoformat()})
        db.commit()
    return _out(p, _people(db, actor.org_id), _accepted(db, p), actor)


@router.post("/{policy_id}/accept")
def accept_policy(policy_id: str, seen: Seen, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """A person accepts the approved version they have on screen, for themselves. Asking twice changes nothing."""
    p = _load(db, _member(actor), policy_id)
    if not actor.user_id:
        raise HTTPException(422, "sign in as a named person to accept a policy")
    if p.status != "APPROVED":
        raise HTTPException(409, "this version has not been approved yet")
    _same_version(p, seen)
    accepted = _accepted(db, p)
    if actor.user_id not in accepted:
        db.add(PolicyAcceptance(org_id=p.org_id, policy_id=p.id, version=p.version, user_id=actor.user_id, accepted_at=_now()))
        audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="POLICY_ACCEPTED",
                         entity_type="policy", entity=p.id, org_id=actor.org_id, after={"version": p.version})
        db.commit()
        accepted.add(actor.user_id)
    return _out(p, _people(db, actor.org_id), accepted, actor)


@router.get("/{policy_id}/versions/{version}")
def get_version(policy_id: str, version: int, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """The exact approved text of an earlier version, with who accepted it: what an auditor asks an admin to show."""
    p = _load(db, _admin(actor), policy_id)
    v = db.query(PolicyVersion).filter_by(org_id=p.org_id, policy_id=p.id, version=version).one_or_none()
    if v is None:
        raise HTTPException(404)
    emails = {u.id: u.email for u in db.query(User).filter(User.org_id == p.org_id)}
    accepted = db.query(PolicyAcceptance).filter_by(org_id=p.org_id, policy_id=p.id, version=version).all()
    return {"version": v.version, "title": v.title, "body": v.body, "sha256": v.sha256, "approved_by": v.approved_by,
            "approved_at": v.approved_at.isoformat(),
            "accepted_by": sorted((emails.get(a.user_id, a.user_id), a.accepted_at.isoformat()) for a in accepted)}
