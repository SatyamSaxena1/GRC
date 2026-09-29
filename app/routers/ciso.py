"""Visibility and manual retry for the CISO Assistant push (app/ciso_sync.py).

A sync failure never blocks the auditor action that caused it, so this router
is how a FAILED row gets noticed and re-tried — there is no automatic retry
queue (see ADR-009: no outbox until a second consumer needs one)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import ciso_sync
from app.auth import Actor, current_actor, deny_read_only
from app.db import get_session
from app.models import CisoSyncState, EvidenceControlLink, GapRow

router = APIRouter(prefix="/admin/ciso-sync", tags=["ciso-sync"])


@router.get("/status")
def sync_status(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    rows = db.query(CisoSyncState).filter_by(org_id=actor.org_id).all()
    return [
        {"entity_type": r.local_entity_type, "entity_id": r.local_entity_id,
         "status": r.last_sync_status, "last_synced_at": r.last_synced_at,
         "error": r.last_error}
        for r in rows
    ]


@router.post("/{entity_type}/{entity_id}/retry")
def retry_sync(entity_type: str, entity_id: str, actor: Actor = Depends(current_actor),
               db: Session = Depends(get_session)):
    if not actor.can_write:
        raise deny_read_only(actor, "retry a CISO Assistant sync")
    state = db.query(CisoSyncState).filter_by(
        org_id=actor.org_id, local_entity_type=entity_type, local_entity_id=entity_id,
    ).one_or_none()
    if state is None:
        raise HTTPException(404)

    if entity_type == "evidence_control_link":
        link = db.get(EvidenceControlLink, entity_id)
        if link is None:
            raise HTTPException(404)
        ciso_sync.push_verdict(db, actor.label(), actor.request_id, link, actor.org_id)
    elif entity_type == "gap":
        gap = db.get(GapRow, entity_id)
        if gap is None:
            raise HTTPException(404)
        ciso_sync.push_gap_resolution(db, actor.label(), actor.request_id, gap, actor.org_id)
    else:
        raise HTTPException(400, "unknown entity_type")

    db.commit()
    return {"entity_type": entity_type, "entity_id": entity_id, "status": state.last_sync_status}
