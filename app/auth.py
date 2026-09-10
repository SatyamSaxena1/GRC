"""Identity. One dependency, not a check copy-pasted into every route.

Two paths into _resolve(): the original stub ("org:<id>" / "user:<id>" /
"auditor:<engagement_id>", no signature) for local dev/tests/demo, and real
OIDC JWTs (app/oidc.py) once OIDC_JWKS_URL/OIDC_ISSUER/OIDC_AUDIENCE are set —
see docs/adr/011-oidc-auth.md for why both coexist rather than one replacing
the other. app/authorization.py holds the real access rules and does not
change for either path.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app import oidc
from app.db import get_session, set_firm, set_tenant
from app.models import AuditFirm, Engagement, EngagementAuditor, User


@dataclass(frozen=True)
class Actor:
    """Who is calling, on which of the two tenancy axes.

    `org_id` is the auditee tenant. `audit_firm_id` is the firm tenant, and is
    set for anyone on the firm side — an auditor working an engagement has
    both. A firm user with no engagement selected has an empty `org_id`: it can
    reach the firm console (app/routers/firm.py) and nothing auditee-owned.
    """

    org_id: str
    engagement_id: str | None = None  # set only for an auditor acting under an engagement
    user_id: str | None = None
    audit_firm_id: str | None = None  # set for firm-side callers
    role: str = "ORG_ADMIN"
    request_id: str = ""  # carried so every audit row can be traced to its request

    def label(self) -> str:
        if self.engagement_id:
            # keep the human when there is one: "which auditor" matters in the
            # trail now that several of a firm's staff can share an engagement
            return (f"auditor:{self.engagement_id}/user:{self.user_id}"
                    if self.user_id else f"auditor:{self.engagement_id}")
        if self.user_id:
            return f"user:{self.user_id}"
        if self.audit_firm_id:
            return f"firm:{self.audit_firm_id}"
        return f"org:{self.org_id}"

    @property
    def is_auditor(self) -> bool:
        return self.engagement_id is not None

    @property
    def is_firm(self) -> bool:
        return self.audit_firm_id is not None

    @property
    def can_write(self) -> bool:
        """May this caller mutate auditee-owned data? Two roles see an org's
        rows in full but never change them: an auditor (reviews, does not edit)
        and a COMPLIANCE_VIEWER (oversight, read-only). Everything else on the
        auditee side may write, subject to the per-resource rules in
        app/authorization.py. See docs/adr/017-compliance-officer-persona.md."""
        return not self.is_auditor and self.role != "COMPLIANCE_VIEWER"


def deny_read_only(actor: Actor, action: str) -> HTTPException:
    """The 403 for a read-only caller reaching a write path, phrased for
    whichever read-only role it is."""
    who = "auditors" if actor.is_auditor else "the compliance-viewer role"
    return HTTPException(403, f"{who} cannot {action} — access is read-only")


def current_actor(
    request: Request,
    authorization: str = Header(...),
    x_engagement_id: str | None = Header(None),
    db: Session = Depends(get_session),
) -> Actor:
    """Resolves the caller and binds the tenant to this transaction, so Postgres
    RLS filters every subsequent query in the request (see ADR-001). Without the
    set_tenant call the policies would match nothing and every read would be empty."""
    actor = _resolve(authorization, db, x_engagement_id)
    actor = replace(actor, request_id=getattr(request.state, "request_id", ""))
    set_tenant(db, actor.org_id)
    set_firm(db, actor.audit_firm_id)
    return actor


def _resolve(authorization: str, db: Session, engagement_header: str | None = None) -> Actor:
    token = authorization.removeprefix("Bearer ").strip()
    if oidc.looks_like_jwt(token):
        return _resolve_oidc(token, db, engagement_header)

    if authorization.startswith("org:"):
        return Actor(org_id=authorization.removeprefix("org:"))

    if authorization.startswith("firm:"):
        firm_id = authorization.removeprefix("firm:")
        if db.get(AuditFirm, firm_id) is None:
            raise HTTPException(401)
        return Actor(org_id="", audit_firm_id=firm_id, role="FIRM_ADMIN")

    if authorization.startswith("user:"):
        user = db.get(User, authorization.removeprefix("user:"))
        if user is None:
            raise HTTPException(401)
        if user.audit_firm_id:
            return _firm_user_actor(db, user, engagement_header)
        if user.org_id is None:
            raise HTTPException(401)
        return Actor(org_id=user.org_id, user_id=user.id, role=user.role)

    if authorization.startswith("auditor:"):
        engagement_id = authorization.removeprefix("auditor:")
        engagement = db.get(Engagement, engagement_id)
        if engagement is None or not engagement.active:
            raise HTTPException(404)  # a closed/unknown engagement reveals nothing
        return Actor(
            org_id=engagement.org_id, engagement_id=engagement_id, role="AUDITOR"
        )

    raise HTTPException(401)


def _resolve_oidc(token: str, db: Session, engagement_header: str | None) -> Actor:
    """Real identity comes from the JWT (its signature, its email claim); org,
    role and engagement scope still come from our own tables, exactly as the
    stub path does — a JWT proves who someone is, not what they may see. Users
    must already be provisioned via /admin/users and matched by email; no new
    column, no JIT provisioning (see docs/adr/011-oidc-auth.md)."""
    claims = oidc.decode(token)
    email = claims.get("email")
    if not email:
        raise HTTPException(401, "token has no email claim")

    user = db.query(User).filter_by(email=email).one_or_none()
    if user is None:
        raise HTTPException(401, "no user provisioned for this identity")

    if user.audit_firm_id:
        if user.role == "AUDITOR" and not engagement_header:
            raise HTTPException(401, "x-engagement-id header required for an auditor")
        return _firm_user_actor(db, user, engagement_header)

    if user.org_id is None:
        raise HTTPException(401)
    return Actor(org_id=user.org_id, user_id=user.id, role=user.role)


def _firm_user_actor(db: Session, user: User, engagement_header: str | None) -> Actor:
    """The one place a firm user's engagement access is decided, for both the
    stub and the OIDC path.

    With no engagement selected the caller gets a firm-console actor bound to no
    auditee. With one selected, firm membership alone is not enough: an AUDITOR
    must be staffed on that engagement (EngagementAuditor). An unstaffed client
    answers 404 like any other invisible resource — a firm's auditor must not be
    able to enumerate the clients it was not put on.
    """
    if not engagement_header:
        return Actor(org_id="", audit_firm_id=user.audit_firm_id,
                     user_id=user.id, role=user.role)

    engagement = db.get(Engagement, engagement_header)
    if (engagement is None or not engagement.active
            or engagement.audit_firm_id != user.audit_firm_id):
        raise HTTPException(404)

    if user.role != "FIRM_ADMIN" and not is_staffed(db, engagement.id, user.id):
        raise HTTPException(404)

    return Actor(org_id=engagement.org_id, engagement_id=engagement.id,
                 user_id=user.id, audit_firm_id=user.audit_firm_id, role="AUDITOR")


def is_staffed(db: Session, engagement_id: str, user_id: str) -> bool:
    return db.query(EngagementAuditor).filter_by(
        engagement_id=engagement_id, user_id=user_id
    ).first() is not None
