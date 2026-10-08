"""Auditor actions: verdict, lock, unlock. Locking is enforced here and in the
model layer, never only in a UI."""

from __future__ import annotations

from datetime import datetime, timezone

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit_log, authorization, checkpoints, ciso_sync
from app.auth import Actor, current_actor
from app.db import get_session
from app.models import Evidence, EvidenceControlLink

router = APIRouter(prefix="/audit", tags=["audit"])

CLOSING_VERDICTS = {"COMPLIANT", "PASS"}


class VerdictIn(BaseModel):
    verdict: str
    reason: str = ""


class UnlockIn(BaseModel):
    reason: str = Field(min_length=3)  # unlocking always needs a stated reason


def _auditor_link(db: Session, actor: Actor, link_id: str) -> EvidenceControlLink:
    if not actor.is_auditor:
        raise HTTPException(403, "only an auditor acting under an engagement may do this")
    link = db.get(EvidenceControlLink, link_id)
    if link is None:
        raise HTTPException(404)
    evidence = db.get(Evidence, link.evidence_id)
    if evidence is None or evidence.org_id != actor.org_id:
        raise HTTPException(404)
    authorization.assert_engagement_covers(db, actor, link.framework)

    # Segregation of duties: whoever produced the evidence cannot be the one who
    # passes judgement on it. Structurally an auditor cannot upload, but a single
    # human holding both identities must still be stopped here rather than relied
    # upon to abstain.
    if evidence.uploaded_by and evidence.uploaded_by == actor.label():
        audit_log.record(
            db, actor=actor.label(), request_id=actor.request_id,
            action="SEGREGATION_OF_DUTIES_BLOCKED", entity_type="evidence_control_link",
            entity=link.id, org_id=actor.org_id,
            detail={"evidence_id": evidence.id, "uploaded_by": evidence.uploaded_by},
        )
        db.commit()
        raise HTTPException(
            403, "segregation of duties: the uploader of this evidence cannot record "
                 "its audit verdict"
        )
    return link


@router.get("/chain")
def chain_status(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """Whether this organisation's audit chain still verifies end to end, and its head."""
    return audit_log.verify(db, audit_log.chain_of(_org_scope(actor))).to_dict()


def _org_scope(actor: Actor) -> str:
    if not actor.org_id:
        raise HTTPException(400, "no organisation selected")
    return actor.org_id


@router.post("/checkpoints")
def issue_checkpoint(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """A signed statement of this organisation's audit-chain head, for the auditor to keep
    outside the platform (ADR-023). Auditors only: the point is a copy the auditee does not hold."""
    if not actor.is_auditor:
        raise HTTPException(403, "only an auditor under an engagement can take a checkpoint")
    org_id = _org_scope(actor)
    try:
        checkpoint = checkpoints.issue(db, org_id, actor.label(), actor.request_id)
    except checkpoints.NotConfigured as exc:
        raise HTTPException(503, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    db.commit()
    return Response(content=json.dumps(checkpoint, indent=2, sort_keys=True), media_type="application/json",
                    headers={"Content-Disposition":
                             f"attachment; filename=audit-checkpoint-{checkpoint['chain_seq']}.json"})


@router.post("/checkpoints/verify")
def verify_checkpoint(checkpoint: dict, actor: Actor = Depends(current_actor),
                      db: Session = Depends(get_session)):
    return checkpoints.verify(db, _org_scope(actor), checkpoint)


@router.get("/checkpoint-keys")
def checkpoint_keys():
    """Public keys only, so anyone holding a checkpoint can check its signature offline."""
    return {"keys": checkpoints.published_keys()}


@router.get("/events.ndjson")
def export_audit_events(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """This organisation's whole chain, for scripts/verify_audit_export.py to verify offline."""
    if not actor.is_auditor:
        raise HTTPException(403, "only an auditor under an engagement can export the audit chain")
    lines = "".join(json.dumps(e, sort_keys=True, default=str) + "\n"
                    for e in checkpoints.export_events(db, _org_scope(actor)))
    return Response(content=lines, media_type="application/x-ndjson",
                    headers={"Content-Disposition": "attachment; filename=audit-events.ndjson"})


@router.post("/links/{link_id}/verdict")
def record_verdict(link_id: str, body: VerdictIn, actor: Actor = Depends(current_actor),
                   db: Session = Depends(get_session)):
    """Record an opinion. A closing verdict locks the control in the same step."""
    link = _auditor_link(db, actor, link_id)
    if link.locked:
        raise HTTPException(409, "control is locked; unlock it first")

    before = _snapshot(link)
    link.auditor_verdict = body.verdict
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="AUDITOR_VERDICT",
                     entity_type="evidence_control_link", entity=link.id, org_id=actor.org_id,
                     detail={"verdict": body.verdict}, reason=body.reason,
                     before=before, after=_snapshot(link))

    if body.verdict.upper() in CLOSING_VERDICTS:
        _lock(db, actor, link, body.verdict)
    db.commit()
    return {"id": link.id, "auditor_verdict": link.auditor_verdict, "locked": link.locked}


def _snapshot(link: EvidenceControlLink) -> dict:
    """The mutable state an auditor action changes — recorded before and after so
    the trail shows what actually moved, not just that something happened."""
    return {"verdict": link.verdict, "auditor_verdict": link.auditor_verdict,
            "locked": link.locked, "locked_by_engagement_id": link.locked_by_engagement_id}


def _lock(db: Session, actor: Actor, link: EvidenceControlLink, verdict: str) -> None:
    before = _snapshot(link)
    link.verdict = verdict
    link.locked_by_engagement_id = actor.engagement_id
    link.locked_at = datetime.now(timezone.utc)
    link.unlocked_at = None
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="CONTROL_LOCKED",
                     entity_type="evidence_control_link", entity=link.id, org_id=actor.org_id,
                     detail={"verdict": verdict, "evidence_id": link.evidence_id,
                             # what the rules decided, exactly (ADR-022)
                             "engine_verdict": link.engine_verdict, "rule_hash": link.rule_hash,
                             "evaluation_hash": link.evaluation_hash},
                     before=before, after=_snapshot(link))
    ciso_sync.push_verdict(db, actor.label(), actor.request_id, link, actor.org_id)


@router.post("/links/{link_id}/lock")
def lock_link(link_id: str, body: VerdictIn, actor: Actor = Depends(current_actor),
              db: Session = Depends(get_session)):
    link = _auditor_link(db, actor, link_id)
    if link.locked:
        raise HTTPException(409, "already locked")
    link.auditor_verdict = body.verdict
    _lock(db, actor, link, body.verdict)
    db.commit()
    return {"id": link.id, "verdict": link.verdict, "locked": True}


@router.post("/links/{link_id}/unlock")
def unlock_link(link_id: str, body: UnlockIn, actor: Actor = Depends(current_actor),
                db: Session = Depends(get_session)):
    """Reopens a control for re-review. The reason is mandatory and recorded."""
    link = _auditor_link(db, actor, link_id)
    if not link.locked:
        raise HTTPException(409, "control is not locked")

    before = _snapshot(link)
    link.locked_by_engagement_id = None
    link.locked_at = None
    link.unlocked_at = datetime.now(timezone.utc)
    link.unlock_reason = body.reason
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="CONTROL_UNLOCKED",
                     entity_type="evidence_control_link", entity=link.id, org_id=actor.org_id,
                     detail={"framework": link.framework, "clause": link.clause},
                     reason=body.reason, before=before, after=_snapshot(link))
    ciso_sync.push_verdict(db, actor.label(), actor.request_id, link, actor.org_id)
    db.commit()
    return {"id": link.id, "locked": False, "unlock_reason": link.unlock_reason}
