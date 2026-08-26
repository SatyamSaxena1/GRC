"""Who may see or change what.

Three rules, enforced here rather than in each route:
  - an org admin sees their own organization, nothing else;
  - a control owner sees only controls granted via ControlAssignment;
  - an auditor sees an auditee only through an ACTIVE engagement whose
    allocation covers the framework in question.

Cross-tenant and unassigned-control reads answer 404, not 403: existence itself
is information we do not leak. An unauthorized *write* to a resource the caller
can legitimately see answers 403.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import audit_log
from app.auth import Actor
from app.models import ControlAssignment, Engagement, EngagementAllocation, OrgControl

logger = logging.getLogger("app.authorization")


class Denied(HTTPException):
    """Refusal, answered as 404 by default so existence is not leaked.

    Raise via `deny()` rather than directly, so every refusal is recorded — an
    attacker probing for another tenant's ids should leave a trail.
    """

    def __init__(self, status: int = 404, detail: str = "not found"):
        super().__init__(status_code=status, detail=detail)


def deny(db: Session, actor: "Actor | None", what: str, *, status: int = 404,
         detail: str = "not found", **context) -> Denied:
    """Record the refusal, then return the exception for the caller to raise."""
    try:
        audit_log.record(
            db,
            actor=actor.label() if actor else "anonymous",
            action="AUTHORIZATION_DENIED",
            entity_type="authorization",
            entity=what,
            org_id=actor.org_id if actor else None,
            detail={"resource": what, "status": status, **context},
            request_id=actor.request_id if actor else "",
        )
        db.commit()
    except Exception:  # never let audit failure mask the refusal itself
        logger.exception("failed to record authorization denial for %s", what)
        db.rollback()
    return Denied(status, detail)


def assert_same_org(db: Session, actor: Actor, org_id: str) -> None:
    if actor.org_id != org_id:
        raise deny(db, actor, f"org:{org_id}", reason="cross-tenant access")


def engagement_frameworks(db: Session, engagement_id: str) -> set[str]:
    return {
        a.framework
        for a in db.query(EngagementAllocation).filter_by(engagement_id=engagement_id)
    }


def assert_engagement_covers(db: Session, actor: Actor, framework: str) -> None:
    """An active engagement is necessary but not sufficient — the allocation must
    cover this framework. Closing the engagement removes access immediately."""
    if actor.engagement_id is None:
        return
    engagement = db.get(Engagement, actor.engagement_id)
    if engagement is None or not engagement.active:
        raise deny(db, actor, f"engagement:{actor.engagement_id}",
                   reason="engagement is closed or unknown")
    if framework not in engagement_frameworks(db, actor.engagement_id):
        raise deny(db, actor, f"framework:{framework}",
                   reason="framework outside engagement allocation")


def assigned_control_ids(db: Session, actor: Actor) -> set[str] | None:
    """Control ids a control owner may touch. None means 'no restriction'."""
    if actor.user_id is None or actor.role != "CONTROL_OWNER":
        return None
    return {
        a.org_control_id
        for a in db.query(ControlAssignment).filter_by(user_id=actor.user_id)
    }


def assert_may_access_control(db: Session, actor: Actor, framework: str, clause: str) -> OrgControl:
    control = db.query(OrgControl).filter_by(
        org_id=actor.org_id, framework=framework, clause=clause
    ).one_or_none()
    if control is None:
        raise Denied(404)  # genuinely absent, not a refusal
    assert_engagement_covers(db, actor, framework)

    allowed = assigned_control_ids(db, actor)
    if allowed is not None and control.id not in allowed:
        # an unassigned control must not even be discoverable
        raise deny(db, actor, f"control:{control.id}",
                   reason="control not assigned to this user",
                   framework=framework, clause=clause)
    return control


def visible_clauses(db: Session, actor: Actor) -> set[tuple[str, str]] | None:
    """(framework, clause) pairs the actor may see, or None for unrestricted."""
    pairs: set[tuple[str, str]] | None = None

    allowed = assigned_control_ids(db, actor)
    if allowed is not None:
        controls = db.query(OrgControl).filter(OrgControl.id.in_(allowed or {""})).all()
        pairs = {(c.framework, c.clause) for c in controls}

    if actor.engagement_id is not None:
        engagement = db.get(Engagement, actor.engagement_id)
        if engagement is None or not engagement.active:
            raise deny(db, actor, f"engagement:{actor.engagement_id}",
                       reason="engagement is closed or unknown")
        frameworks = engagement_frameworks(db, actor.engagement_id)
        scoped = {
            (c.framework, c.clause)
            for c in db.query(OrgControl).filter_by(org_id=actor.org_id)
            if c.framework in frameworks
        }
        pairs = scoped if pairs is None else (pairs & scoped)

    return pairs
