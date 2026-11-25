"""AI-assessed clauses (ADR-069): the model proposes, a named organisation admin confirms. Never PASS.

A clause qualifies only if its pack marks it assessable and no fixed rule judges it (Requirement.ai_assessable). An
assessment is a record: re-running adds a new row; a confirmed row is never edited and a re-run never replaces it.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import analytics, audit_log
from app.actor_names import resolve_actors
from app.ai import assessor
from app.auth import Actor, current_actor, deny_read_only
from app.content.load import load as load_content
from app.db import get_session
from app.ingest import gateway_for, read_document
from app.models import AiAssessment, Evidence, Organization
from app.service import _ensure_org_control
from app.storage import get_storage

router = APIRouter(prefix="/assessments", tags=["assessments"])
CONTENT = load_content()
OUTCOMES = ("MET", "PARTIAL", "NOT_MET")


def _out(row: AiAssessment, names: dict[str, str] | None = None) -> dict:
    names = names or {}
    return {"id": row.id, "framework": row.framework, "clause": row.clause, "evidence_id": row.evidence_id,
            "outcome": row.outcome, "reason": row.reason, "points": row.points, "model": row.model,
            "provider": row.provider, "prompt_version": row.prompt_version, "document_sha256": row.document_sha256,
            "created_by": row.created_by, "created_at": row.created_at.isoformat(),
            "confirmed_outcome": row.confirmed_outcome, "confirmed_by": row.confirmed_by,
            "confirmed_by_display": names.get(row.confirmed_by or "", row.confirmed_by),
            "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
            "confirm_note": row.confirm_note}


@router.get("")
def list_assessments(framework: str | None = None, actor: Actor = Depends(current_actor),
                     db: Session = Depends(get_session)):
    q = db.query(AiAssessment).filter_by(org_id=actor.org_id)
    if framework:
        q = q.filter_by(framework=framework)
    rows = q.order_by(AiAssessment.created_at.desc()).all()
    names = resolve_actors(db, (r.confirmed_by for r in rows if r.confirmed_by))
    live = {a.id for fw in {r.framework for r in rows} for a in analytics.ai_in_force(db, actor.org_id, fw).values()}
    return [{**_out(r, names), "current": r.id in live} for r in rows]


class AssessIn(BaseModel):
    framework: str
    clause: str
    evidence_id: str | None = None


@router.post("", status_code=201)
def assess(body: AssessIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    req = CONTENT.requirement(body.framework, body.clause)
    if req is None:
        raise HTTPException(404, "no such clause")
    if not req.ai_assessable:
        raise HTTPException(409, "this clause is judged by a fixed rule or by attestation; the model does not assess it")
    if actor.is_auditor or actor.engagement_id:
        raise HTTPException(403, "an auditor reviews assessments and does not run them")
    if not actor.can_write:
        raise deny_read_only(actor, "run an AI assessment")
    org = db.get(Organization, actor.org_id)
    if org is None or body.framework not in (org.frameworks or []):
        raise HTTPException(409, "subscribe to this framework first")
    types = {er.artefact_type for er in req.evidence_requirements}
    if body.evidence_id:
        ev = db.get(Evidence, body.evidence_id)
    else:
        ev = (db.query(Evidence).filter_by(org_id=actor.org_id, lifecycle_status="CURRENT", deleted_at=None)
              .filter(Evidence.artefact_type.in_(types)).order_by(Evidence.created_at.desc()).first())
    if ev is None or ev.org_id != actor.org_id or ev.deleted_at is not None:
        raise HTTPException(422, "no evidence of the right type to assess; upload the document first")
    if ev.artefact_type not in types:
        raise HTTPException(422, f"this clause assesses a {' or '.join(sorted(types))} document")
    data = get_storage().get(ev.storage_key)
    gateway = gateway_for(ev.ai_model, ev.ai_vision_model)
    text, _method = read_document(ev.filename, data, gateway=gateway)
    result = assessor.assess(gateway, req, text)
    row = AiAssessment(org_id=actor.org_id, framework=body.framework, clause=body.clause, evidence_id=ev.id,
                       outcome=result["outcome"], reason=result["reason"], points=result["points"],
                       model=result["model"], provider=result["provider"], prompt_version=result["prompt_version"],
                       document_sha256=hashlib.sha256(data).hexdigest(), created_by=actor.label())
    db.add(row)
    db.flush()
    control = _ensure_org_control(db, actor.org_id, body.framework, body.clause)
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="AI_ASSESSMENT_CREATED",
                     entity_type="org_control", entity=control.id, org_id=actor.org_id,
                     detail={"assessment_id": row.id, "framework": body.framework, "clause": body.clause,
                             "outcome": row.outcome, "model": row.model, "document_sha256": row.document_sha256})
    db.commit()
    return _out(row)


class ConfirmIn(BaseModel):
    outcome: str | None = None  # omit to accept the proposal; give one to override it
    note: str = Field(default="", max_length=2000)


@router.post("/{assessment_id}/confirm")
def confirm(assessment_id: str, body: ConfirmIn, actor: Actor = Depends(current_actor),
            db: Session = Depends(get_session)):
    """Only an organisation admin, naming themselves: the model never confirms."""
    row = db.get(AiAssessment, assessment_id)
    if row is None or row.org_id != actor.org_id:
        raise HTTPException(404)
    if actor.is_auditor or actor.engagement_id or actor.role != "ORG_ADMIN":
        raise HTTPException(403, "only an organisation admin confirms an AI assessment")
    if row.confirmed_at is not None:
        raise HTTPException(409, "already confirmed; run a new assessment instead")
    chosen = body.outcome or row.outcome
    if chosen not in OUTCOMES:
        raise HTTPException(422, "name an outcome (MET, PARTIAL or NOT_MET): this assessment needs a person's judgement")
    row.confirmed_outcome, row.confirmed_by = chosen, actor.label()
    row.confirmed_at, row.confirm_note = datetime.now(timezone.utc).replace(tzinfo=None), body.note.strip()
    control = _ensure_org_control(db, actor.org_id, row.framework, row.clause)
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="AI_ASSESSMENT_CONFIRMED",
                     entity_type="org_control", entity=control.id, org_id=actor.org_id,
                     detail={"assessment_id": row.id, "framework": row.framework, "clause": row.clause,
                             "proposed": row.outcome, "confirmed": chosen})
    db.commit()
    return _out(row)
