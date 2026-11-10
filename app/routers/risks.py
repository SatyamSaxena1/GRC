"""The risk register (ADR-057): what could go wrong, how bad by fixed rules, what is being done, and when it is
next due for review. An organisation admin writes everything; a control owner updates the risks that name them
as owner; a compliance viewer reads. Every change is in the audit chain with before and after state.

Scores, bands and review states come from app/risks.py. A model may only draft wording (POST /risks/draft), and
that draft is returned to the caller and stored nowhere: a person edits it and saves, and the saver is the signer.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app import audit_log, authorization, ingest, risks
from app.ai.risk_draft import draft_risk
from app.auth import Actor, current_actor
from app.db import get_session
from app.models import OrgControl, Risk

router = APIRouter(prefix="/risks", tags=["risks"])

Category = Literal["SECURITY", "PRIVACY", "COMPLIANCE", "OPERATIONAL", "VENDOR", "AI", "OTHER"]
Treatment = Literal["MITIGATE", "ACCEPT", "TRANSFER", "AVOID"]
Status = Literal["OPEN", "IN_TREATMENT", "CLOSED"]
MIN_REVIEW_WORDS = 3
# What a PATCH may not blank out: only the treatment and the two residual halves can be cleared.
NOT_NULLABLE = {"title", "description", "category", "owner_email", "inherent_likelihood", "inherent_impact",
                "treatment_plan", "status", "next_review_date", "control_ids"}
ADMIN_ONLY = {"owner_email", "control_ids"}


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _email(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().lower()
    if value and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise ValueError("owner_email must be an email address, or empty")
    return value


class RiskIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=4000)
    category: Category = "OTHER"
    owner_email: str = Field(default="", max_length=254)
    inherent_likelihood: int = Field(ge=1, le=5)
    inherent_impact: int = Field(ge=1, le=5)
    treatment: Treatment | None = None
    treatment_plan: str = Field(default="", max_length=4000)
    residual_likelihood: int | None = Field(default=None, ge=1, le=5)
    residual_impact: int | None = Field(default=None, ge=1, le=5)
    status: Status = "OPEN"
    next_review_date: date | None = None
    control_ids: list[str] = Field(default_factory=list, max_length=50)

    owner_clean = field_validator("owner_email")(_email)

    @model_validator(mode="after")
    def _residual_is_a_pair(self):
        if (self.residual_likelihood is None) != (self.residual_impact is None):
            raise ValueError("state both residual likelihood and residual impact, or neither")
        return self


class RiskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    category: Category | None = None
    owner_email: str | None = Field(default=None, max_length=254)
    inherent_likelihood: int | None = Field(default=None, ge=1, le=5)
    inherent_impact: int | None = Field(default=None, ge=1, le=5)
    treatment: Treatment | None = None
    treatment_plan: str | None = Field(default=None, max_length=4000)
    residual_likelihood: int | None = Field(default=None, ge=1, le=5)
    residual_impact: int | None = Field(default=None, ge=1, le=5)
    status: Status | None = None
    next_review_date: date | None = None
    control_ids: list[str] | None = Field(default=None, max_length=50)

    owner_clean = field_validator("owner_email")(_email)

    @model_validator(mode="after")
    def _no_blanking(self):
        blank = sorted(k for k in self.model_fields_set & NOT_NULLABLE if getattr(self, k) is None)
        if blank:
            raise ValueError(f"cannot be cleared: {', '.join(blank)}")
        return self


class ReviewIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


class DraftIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    context: str = Field(default="", max_length=1000)


def _state(r: Risk) -> dict:
    """What the audit trail records before and after a change: every field a person can set."""
    return {
        "title": r.title, "description": r.description, "category": r.category, "owner_email": r.owner_email,
        "inherent_likelihood": r.inherent_likelihood, "inherent_impact": r.inherent_impact,
        "treatment": r.treatment, "treatment_plan": r.treatment_plan,
        "residual_likelihood": r.residual_likelihood, "residual_impact": r.residual_impact,
        "status": r.status, "next_review_date": r.next_review_date.isoformat() if r.next_review_date else None,
        "control_ids": list(r.control_ids or []),
    }


def _out(r: Risk, today: date, controls: dict[str, OrgControl], visible: set[tuple[str, str]] | None) -> dict:
    now = risks.rating(*risks.position(r))
    return {
        "id": r.id, "title": r.title, "description": r.description, "category": r.category,
        "owner_email": r.owner_email, "treatment": r.treatment, "treatment_plan": r.treatment_plan,
        "status": r.status,
        "inherent": risks.rating(r.inherent_likelihood, r.inherent_impact),
        "residual": (risks.rating(r.residual_likelihood, r.residual_impact)
                     if r.residual_likelihood is not None and r.residual_impact is not None else None),
        "current": now, "review_every_days": risks.REVIEW_EVERY_DAYS[now["band"]],
        "next_review_date": r.next_review_date.isoformat() if r.next_review_date else None,
        "last_reviewed_at": r.last_reviewed_at.isoformat() if r.last_reviewed_at else None,
        "review_state": risks.review_state(r.status, r.next_review_date, today),
        # A control owner only learns the names of controls they could already see.
        "controls": [{"id": c.id, "framework": c.framework, "clause": c.clause}
                     for cid in (r.control_ids or []) if (c := controls.get(cid)) is not None
                     and (visible is None or (c.framework, c.clause) in visible)],
        "created_at": r.created_at.isoformat(), "created_by": r.created_by,
    }


def _controls(db: Session, org_id: str) -> dict[str, OrgControl]:
    return {c.id: c for c in db.query(OrgControl).filter_by(org_id=org_id)}


def _one(db: Session, actor: Actor, r: Risk) -> dict:
    return _out(r, _today(), _controls(db, actor.org_id), authorization.visible_clauses(db, actor))


def _load(db: Session, actor: Actor, risk_id: str) -> Risk:
    r = db.get(Risk, risk_id)  # RLS hides another organisation's row; the org check is the second lock
    if r is None or r.org_id != actor.org_id:
        raise HTTPException(404)
    return r


def _check_controls(db: Session, actor: Actor, ids: list[str]) -> list[str]:
    ids = list(dict.fromkeys(ids))
    if ids and db.query(OrgControl).filter(OrgControl.org_id == actor.org_id, OrgControl.id.in_(ids)).count() != len(ids):
        raise HTTPException(422, "control_ids must all be controls of this organisation")
    return ids


@router.get("")
def list_risks(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    scope = authorization.risk_scope(db, actor)
    query = db.query(Risk).filter_by(org_id=actor.org_id)
    if scope is not None:
        query = query.filter(Risk.owner_email == scope)
    rows = query.all()
    today, controls, visible = _today(), _controls(db, actor.org_id), authorization.visible_clauses(db, actor)
    rows.sort(key=lambda r: (r.status == "CLOSED", -risks.score(*risks.position(r)), r.title.lower()))
    open_rows = [r for r in rows if r.status != "CLOSED"]
    by_band = {name: 0 for name, _ in risks.BANDS}
    for r in open_rows:
        by_band[risks.band(risks.score(*risks.position(r)))] += 1
    return {
        "risks": [_out(r, today, controls, visible) for r in rows],
        "summary": {"open": len(open_rows), "by_band": by_band, "reviews_overdue": risks.overdue_count(rows, today)},
        "heatmap": {"inherent": risks.heatmap(rows, current=False), "current": risks.heatmap(rows, current=True)},
        "bands": [{"band": name, "from": floor} for name, floor in risks.BANDS],
        # What the page may offer: an admin edits everything, a control owner their own risks, a viewer nothing.
        "can_write": actor.can_write, "can_write_all": scope is None and actor.can_write,
    }


@router.post("", status_code=201)
def add_risk(body: RiskIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    if authorization.risk_scope(db, actor) is not None or not actor.can_write:
        raise HTTPException(403, "only an organisation admin may add a risk")
    data = body.model_dump()
    data["control_ids"] = _check_controls(db, actor, data["control_ids"])
    if data["next_review_date"] is None:
        data["next_review_date"] = risks.default_next_review(
            risks.band(risks.score(*risks.position(Risk(**data)))), _today())
    r = Risk(org_id=actor.org_id, created_by=actor.label(), **data)
    r.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(r)
    db.flush()
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="RISK_ADDED",
                     entity_type="risk", entity=r.id, org_id=actor.org_id, after=_state(r))
    db.commit()
    return _one(db, actor, r)


@router.patch("/{risk_id}")
def update_risk(risk_id: str, body: RiskPatch, actor: Actor = Depends(current_actor),
                db: Session = Depends(get_session)):
    r = _load(db, actor, risk_id)
    authorization.assert_may_change_risk(db, actor, r)
    changes = body.model_dump(exclude_unset=True)
    if authorization.risk_scope(db, actor) is not None and ADMIN_ONLY & changes.keys():
        raise HTTPException(403, "only an organisation admin may change a risk's owner or linked controls")
    if "control_ids" in changes:
        changes["control_ids"] = _check_controls(db, actor, changes["control_ids"])
    if (changes.get("residual_likelihood", r.residual_likelihood) is None) != (
            changes.get("residual_impact", r.residual_impact) is None):
        raise HTTPException(422, "state both residual likelihood and residual impact, or neither")
    before = _state(r)
    for key, value in changes.items():
        setattr(r, key, value)
    after = _state(r)
    if after != before:
        action = "RISK_CLOSED" if before["status"] != "CLOSED" and r.status == "CLOSED" else "RISK_UPDATED"
        audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action=action,
                         entity_type="risk", entity=r.id, org_id=actor.org_id, before=before, after=after)
    db.commit()
    return _one(db, actor, r)


@router.post("/{risk_id}/review")
def record_review(risk_id: str, body: ReviewIn, actor: Actor = Depends(current_actor),
                  db: Session = Depends(get_session)):
    """Record that the risk was reviewed now and set the next review from its current band. The note says what
    was checked; it must say something, and it is the reason on the audit event."""
    r = _load(db, actor, risk_id)
    authorization.assert_may_change_risk(db, actor, r)
    if r.status == "CLOSED":
        raise HTTPException(409, "a closed risk needs no review")
    note = body.note.strip()
    if len(re.findall(r"\w+", note)) < MIN_REVIEW_WORDS:
        raise HTTPException(422, f"say what was reviewed, in at least {MIN_REVIEW_WORDS} words")
    before = {"next_review_date": r.next_review_date.isoformat() if r.next_review_date else None,
              "last_reviewed_at": r.last_reviewed_at.isoformat() if r.last_reviewed_at else None}
    r.last_reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    r.next_review_date = risks.default_next_review(risks.band(risks.score(*risks.position(r))), _today())
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="RISK_REVIEWED",
                     entity_type="risk", entity=r.id, org_id=actor.org_id, reason=note, before=before,
                     after={"next_review_date": r.next_review_date.isoformat(),
                            "last_reviewed_at": r.last_reviewed_at.isoformat()},
                     detail={"title": r.title, "band": risks.rating(*risks.position(r))["band"]})
    db.commit()
    return _one(db, actor, r)


@router.post("/draft")
def draft(body: DraftIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """Suggested wording for a description and a treatment plan: a pre-fill for the form, never a decision.
    It stores no risk and sets no score; a person edits the text and saves it. POST because it costs a model
    call, not because it changes state."""
    authorization.risk_scope(db, actor)
    if not actor.can_write:
        raise HTTPException(403, "the compliance-viewer role cannot draft risk wording — access is read-only")
    gateway = ingest._tool_gateway()
    if not gateway.available():
        raise HTTPException(503, "the drafting model is offline: write the wording by hand")
    result = draft_risk(gateway, body.title.strip(), body.context)
    if not (result["description"] or result["treatment_plan"]):
        raise HTTPException(502, "the model gave no usable draft: try again, or write it by hand")
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="RISK_DRAFTED",
                     entity_type="risk_draft", entity=gateway.model, org_id=actor.org_id,
                     detail={"title": body.title.strip(), "model": gateway.model})
    db.commit()
    return {**result, "model": gateway.model,
            "notice": "Drafted by a model. Edit it before you save: you, not the model, answer for what the register says."}
