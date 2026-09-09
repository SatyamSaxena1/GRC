from __future__ import annotations

import json
from typing import Iterator

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import audit_log, authorization, events
from app.auth import Actor, current_actor
from app.content.load import load as load_content
from app.db import get_session, session_scope, set_tenant
from app.models import (
    TERMINAL_EVIDENCE_STATUSES, Evidence, EvidenceAttribute, EvidenceControlLink, GapRow,
)
from app.service import link_commitment_stale, process_evidence
from app.storage import get_storage, object_key
from app.upload_security import UploadRejected, get_scanner, validate_upload

router = APIRouter(prefix="/evidence", tags=["evidence"])
CONTENT = load_content()


def _scoped_evidence(db: Session, actor: Actor, evidence_id: str) -> Evidence:
    evidence = db.get(Evidence, evidence_id)
    if evidence is None:
        raise HTTPException(404)
    if evidence.org_id != actor.org_id:
        # Cross-tenant access answers 404 — identical to "doesn't exist" — but is
        # recorded, because someone guessing ids is exactly what we want to see.
        raise authorization.deny(db, actor, f"evidence:{evidence_id}",
                                 reason="cross-tenant evidence access")
    return evidence


def _ingest(db: Session, actor: Actor, file: UploadFile, artefact_type: str,
            *, version: int = 1, supersedes: Evidence | None = None) -> Evidence:
    """Validate at the trust boundary, store immutably, register the row."""
    if not actor.org_id:
        # A firm-side actor with no client open has audit_firm_id but no
        # org_id — there is no tenant for this row to belong to. Letting it
        # through created an orphaned Evidence(org_id="") that no
        # Organization matches, which crashed the background pipeline the
        # instant it tried org.frameworks (see app/service.py::_run_pipeline).
        raise HTTPException(400, "no organisation selected — sign in as an organisation, "
                                 "or open a client first, before uploading evidence")
    try:
        upload = validate_upload(file.file, file.filename or "")
        get_scanner().scan(upload.data)
    except UploadRejected as exc:
        raise HTTPException(400, str(exc)) from exc

    duplicate = db.query(Evidence).filter_by(
        org_id=actor.org_id, sha256=upload.sha256, lifecycle_status="CURRENT"
    ).first()
    if duplicate is not None and supersedes is None:
        raise HTTPException(409, {
            "message": "identical file already uploaded", "evidence_id": duplicate.id,
            "sha256": upload.sha256,
        })

    evidence = Evidence(
        org_id=actor.org_id, artefact_type=artefact_type,
        original_filename=upload.original_filename, filename=upload.filename,
        mime_type=upload.mime_type, size_bytes=upload.size_bytes, sha256=upload.sha256,
        uploaded_by=actor.label(), version=version,
        supersedes_id=supersedes.id if supersedes else None, status="SCANNING",
    )
    db.add(evidence)
    db.flush()

    evidence.storage_key = object_key(
        actor.org_id, evidence.id, evidence.version, upload.filename
    )
    get_storage().put(evidence.storage_key, upload.data)
    evidence.status = "STORED"

    audit_log.record(
        db, actor=actor.label(), request_id=actor.request_id, action="EVIDENCE_UPLOADED", entity_type="evidence",
        entity=evidence.id, org_id=actor.org_id,
        detail={"sha256": upload.sha256, "size": upload.size_bytes,
                "mime": upload.mime_type, "version": evidence.version},
    )
    db.commit()
    return evidence


def _process_in_background(evidence_id: str, org_id: str, actor_label: str,
                           request_id: str = "") -> None:
    """Runs after the response is sent, outside any request. Tenant context and the
    request id are passed explicitly and re-bound on the job's own session — a
    background job inherits nothing, so RLS would otherwise see no tenant at all
    and its audit rows would be untraceable to the upload that caused them."""
    with session_scope() as db:
        set_tenant(db, org_id)
        evidence = db.get(Evidence, evidence_id)
        if evidence is None or evidence.org_id != org_id:
            return
        process_evidence(db, CONTENT, evidence, actor_label, request_id=request_id)


@router.get("")
def list_evidence(
    artefact_type: str | None = None,
    lifecycle_status: str | None = None,
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_session),
):
    """Evidence discovery, organisation-wide. Scoped the same way a single
    evidence GET is (tenant match only) — evidence itself isn't restricted by
    control assignment, only which evaluation links are shown on it (see
    _visible_links); a list endpoint following a different rule here would be
    a surprise, not a feature."""
    query = db.query(Evidence).filter_by(org_id=actor.org_id)
    if artefact_type:
        query = query.filter_by(artefact_type=artefact_type)
    if lifecycle_status:
        query = query.filter_by(lifecycle_status=lifecycle_status)
    rows = query.order_by(Evidence.created_at.desc()).all()
    return [
        {
            "id": e.id, "original_filename": e.original_filename,
            "artefact_type": e.artefact_type, "version": e.version,
            "lifecycle_status": e.lifecycle_status, "status": e.status,
            "quality_score": e.quality_score, "uploaded_by": e.uploaded_by,
            "created_at": e.created_at.isoformat(),
        }
        for e in rows
    ]


@router.post("", status_code=202)
def upload_evidence(
    background: BackgroundTasks,
    file: UploadFile,
    artefact_type: str = "POLICY",
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_session),
):
    if actor.is_auditor:
        raise HTTPException(403, "auditors review evidence, they do not upload it")
    evidence = _ingest(db, actor, file, artefact_type)
    background.add_task(_process_in_background, evidence.id, actor.org_id,
                        actor.label(), actor.request_id)
    return {"evidence_id": evidence.id, "id": evidence.id, "status": evidence.status}


@router.post("/{evidence_id}/versions", status_code=202)
def upload_new_version(
    evidence_id: str,
    background: BackgroundTasks,
    file: UploadFile,
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_session),
):
    """Supersede an evidence artefact. A locked link belongs only to the version
    the auditor reviewed — it is never cloned or silently changed. A new version
    over a locked control raises EVIDENCE_CHANGED_AFTER_LOCK instead."""
    if actor.is_auditor:
        raise HTTPException(403, "auditors review evidence, they do not upload it")
    prior = _scoped_evidence(db, actor, evidence_id)
    before = {"lifecycle_status": prior.lifecycle_status, "version": prior.version}

    new = _ingest(db, actor, file, prior.artefact_type,
                  version=prior.version + 1, supersedes=prior)
    prior.lifecycle_status = "SUPERSEDED"

    for link in db.query(EvidenceControlLink).filter_by(evidence_id=prior.id):
        if link.locked:
            audit_log.record(
                db, actor=actor.label(), request_id=actor.request_id, action="EVIDENCE_CHANGED_AFTER_LOCK",
                entity_type="evidence_control_link", entity=link.id, org_id=actor.org_id,
                detail={"framework": link.framework, "clause": link.clause,
                        "locked_by_engagement_id": link.locked_by_engagement_id,
                        "old_evidence_id": prior.id, "new_evidence_id": new.id},
            )
    audit_log.record(
        db, actor=actor.label(), request_id=actor.request_id, action="EVIDENCE_SUPERSEDED", entity_type="evidence",
        entity=prior.id, org_id=actor.org_id,
        detail={"superseded_by": new.id, "version": prior.version},
        before=before,
        after={"lifecycle_status": prior.lifecycle_status, "version": prior.version},
    )
    db.commit()

    background.add_task(_process_in_background, new.id, actor.org_id,
                        actor.label(), actor.request_id)
    return {"evidence_id": new.id, "id": new.id, "status": new.status, "version": new.version}


@router.post("/{evidence_id}/reprocess", status_code=202)
def reprocess_evidence(
    evidence_id: str,
    background: BackgroundTasks,
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_session),
):
    """Re-run the pipeline for evidence that failed, died mid-run, or was
    processed while the analysis model was unavailable.

    Recovery only: refused once an auditor has locked a verdict on this
    evidence, so it cannot be used to quietly recompute a result someone has
    already acted on. A FAILED or NEEDS_REVIEW row with nothing locked is
    exactly what this exists to rescue. The stored file is immutable and reused
    as-is — nothing is re-uploaded.
    """
    if actor.is_auditor:
        raise HTTPException(403, "auditors review evidence, they do not process it")
    evidence = _scoped_evidence(db, actor, evidence_id)

    # `locked` is a property over locked_by_engagement_id, not a column — check it
    # in Python the way the rest of the pipeline does (app/service.py, ::upload_new_version).
    links = db.query(EvidenceControlLink).filter_by(evidence_id=evidence.id).all()
    if any(link.locked for link in links):
        raise HTTPException(409, "an auditor has locked a verdict on this evidence; "
                                 "upload a new version to re-evaluate it")

    audit_log.record(
        db, actor=actor.label(), request_id=actor.request_id, action="EVIDENCE_REPROCESS_REQUESTED",
        entity_type="evidence", entity=evidence.id, org_id=actor.org_id,
        detail={"from_status": evidence.status, "status_detail": evidence.status_detail},
    )
    db.commit()

    background.add_task(_process_in_background, evidence.id, actor.org_id,
                        actor.label(), actor.request_id)
    return {"evidence_id": evidence.id, "id": evidence.id, "status": evidence.status}


@router.get("/{evidence_id}/status")
def evidence_status(evidence_id: str, actor: Actor = Depends(current_actor),
                    db: Session = Depends(get_session)):
    evidence = _scoped_evidence(db, actor, evidence_id)
    return {"evidence_id": evidence.id, "status": evidence.status,
            "detail": evidence.status_detail, "lifecycle_status": evidence.lifecycle_status,
            "quality_score": evidence.quality_score}


@router.get("/{evidence_id}/events")
def evidence_events(evidence_id: str, actor: Actor = Depends(current_actor),
                    db: Session = Depends(get_session)):
    """Live progress for a running pipeline, as Server-Sent Events.

    Authorized exactly like every other read of this evidence — the scope check
    happens once, here, before the stream opens. Purely a faster view of work
    that is being persisted anyway (see app/events.py): a client that never
    connects, or drops, still gets the whole result from the ordinary endpoints.
    """
    evidence = _scoped_evidence(db, actor, evidence_id)
    already_finished = evidence.status in TERMINAL_EVIDENCE_STATUSES

    def emit() -> Iterator[str]:
        # Tell the client where the run already is, so a late subscriber isn't
        # left waiting for a status change that has already happened.
        yield _sse("status", {"status": evidence.status, "detail": evidence.status_detail})
        if already_finished:
            yield _sse("done", {"evidence_id": evidence_id})
            return
        for event, data in events.subscribe(evidence_id):
            yield _sse(event, data)

    return StreamingResponse(emit(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",  # don't let a proxy buffer the stream into uselessness
    })


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get("/{evidence_id}/attributes")
def evidence_attributes(evidence_id: str, actor: Actor = Depends(current_actor),
                        db: Session = Depends(get_session)):
    evidence = _scoped_evidence(db, actor, evidence_id)
    return [
        {"name": a.name, "value": a.value, "confidence": a.confidence,
         "extraction_method": a.extraction_method, "sources": a.sources}
        for a in db.query(EvidenceAttribute).filter_by(evidence_id=evidence.id)
    ]


def _visible_links(db: Session, actor: Actor, evidence_id: str):
    allowed = authorization.visible_clauses(db, actor)
    links = db.query(EvidenceControlLink).filter_by(evidence_id=evidence_id).all()
    if allowed is None:
        return links
    return [l for l in links if (l.framework, l.clause) in allowed]


def _link_payload(db: Session, link, actor: Actor) -> dict:
    payload = {
        "id": link.id, "framework": link.framework, "clause": link.clause,
        "verdict": link.verdict, "auditor_verdict": link.auditor_verdict,
        "confidence": link.ai_confidence, "ucos": link.ucos, "locked": link.locked,
        "gaps": [
            {"id": g.id, "kind": g.kind, "attribute": g.attribute, "detail": g.detail,
             "actual_value": g.actual_value, "required_value": g.required_value,
             "required_action": g.required_action, "status": g.status,
             "resolved_at": g.resolved_at.isoformat() if g.resolved_at else None}
            for g in db.query(GapRow).filter_by(link_id=link.id)
        ],
    }
    # First field-level redaction in this codebase — every other role check
    # here is object-level (see app/authorization.py). Narrow and explicit
    # rather than a redaction framework for one field; see ADR-012.
    if actor.is_auditor:
        payload["nutshell"] = link.nutshell
    # Not a redaction — every role sees this, the auditee most of all, since
    # they are the one who needs to reprocess (see ADR-013).
    stale, reason = link_commitment_stale(db, CONTENT, actor.org_id, link)
    payload["commitment_stale"] = stale
    payload["stale_reason"] = reason
    return payload


@router.get("/{evidence_id}/evaluations")
def evidence_evaluations(evidence_id: str, actor: Actor = Depends(current_actor),
                         db: Session = Depends(get_session)):
    _scoped_evidence(db, actor, evidence_id)
    return [_link_payload(db, l, actor) for l in _visible_links(db, actor, evidence_id)]


@router.get("/{evidence_id}/history")
def evidence_history(evidence_id: str, actor: Actor = Depends(current_actor),
                     db: Session = Depends(get_session)):
    """Append-only trail for this artefact and its links."""
    from app.models import AuditEvent

    evidence = _scoped_evidence(db, actor, evidence_id)
    link_ids = [l.id for l in db.query(EvidenceControlLink).filter_by(evidence_id=evidence.id)]
    events = db.query(AuditEvent).filter(
        AuditEvent.entity.in_([evidence.id, *link_ids])
    ).order_by(AuditEvent.at).all()
    return [
        {"action": e.action, "actor": e.actor, "entity_type": e.entity_type,
         "entity": e.entity, "detail": e.detail, "reason": e.reason,
         "at": e.at.isoformat()}
        for e in events
    ]


@router.get("/{evidence_id}/versions")
def list_versions(evidence_id: str, actor: Actor = Depends(current_actor),
                  db: Session = Depends(get_session)):
    """Full lineage, oldest first. A superseded version stays permanently retrievable."""
    evidence = _scoped_evidence(db, actor, evidence_id)
    lineage = [evidence]
    while lineage[0].supersedes_id:
        lineage.insert(0, _scoped_evidence(db, actor, lineage[0].supersedes_id))
    cursor = evidence
    while True:
        newer = db.query(Evidence).filter_by(supersedes_id=cursor.id).one_or_none()
        if newer is None:
            break
        lineage.append(newer)
        cursor = newer
    return [{"id": e.id, "version": e.version, "lifecycle_status": e.lifecycle_status,
             "status": e.status, "sha256": e.sha256,
             "original_filename": e.original_filename} for e in lineage]


@router.get("/{evidence_id}")
def get_evidence(evidence_id: str, actor: Actor = Depends(current_actor),
                 db: Session = Depends(get_session)):
    evidence = _scoped_evidence(db, actor, evidence_id)
    return {
        "id": evidence.id,
        "version": evidence.version,
        "lifecycle_status": evidence.lifecycle_status,
        "status": evidence.status,
        "sha256": evidence.sha256,
        "mime_type": evidence.mime_type,
        "size_bytes": evidence.size_bytes,
        "original_filename": evidence.original_filename,
        "quality_score": evidence.quality_score,
        # {} (the column's default before scoring ever runs) is not the shape
        # the frontend's quality type promises — normalize to null so
        # `evidence.quality && evidence.quality.dimensions.map(...)` can't
        # crash on a dimensions-less object (see EvidenceDetail.tsx).
        "quality": evidence.quality_detail or None,
        "download_url": get_storage().url(evidence.storage_key) if evidence.storage_key else "",
        "extracted_attributes": evidence.extracted_attributes,
        "links": [_link_payload(db, l, actor) for l in _visible_links(db, actor, evidence.id)],
    }
