"""The content packs in force, by hash (ADR-022)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app import provenance
from app.auth import Actor, current_actor
from app.content.load import load as load_content

router = APIRouter(prefix="/content", tags=["content"])
CONTENT = load_content()


@router.get("/packs")
def list_packs(actor: Actor = Depends(current_actor)):
    return {"engine_version": provenance.ENGINE_VERSION, "build_id": provenance.build_id(),
            "packs": provenance.packs(CONTENT)}
