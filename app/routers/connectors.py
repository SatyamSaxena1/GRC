"""Pull normalized evidence snapshots from external systems.

Collectors are server-side URLs so credentials never cross the browser. Each
endpoint returns {"attributes": {...}}; customer/vendor-specific OAuth and API
translation stays at that boundary instead of leaking into the evidence engine.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app import audit_log
from app.auth import Actor, current_actor, deny_read_only
from app.content.load import load as load_content
from app.db import get_session, session_scope, set_tenant
from app.models import Evidence, Organization
from app.service import process_evidence
from app.storage import get_storage, object_key

router = APIRouter(prefix="/connectors", tags=["connectors"])
CONTENT = load_content()
MAX_SNAPSHOT_BYTES = 1_000_000

SOURCES = {
    "aws": ("AWS", "AWS_SNAPSHOT", {
        "encryption_at_rest", "privileged_access_mfa", "access_logging_enabled", "backup_enabled",
    }),
    "m365": ("Microsoft 365", "M365_SNAPSHOT", {
        "privileged_access_mfa", "access_logging_enabled",
    }),
    "google-workspace": ("Google Workspace", "GOOGLE_WORKSPACE_SNAPSHOT", {
        "privileged_access_mfa", "access_logging_enabled",
    }),
    "hrms": ("HRMS", "HRMS_SNAPSHOT", {"terminated_users_with_active_accounts"}),
}


def _env_key(source: str, suffix: str) -> str:
    return f"DPDP_{source.upper().replace('-', '_')}_COLLECTOR_{suffix}"


def _filename(source: str) -> str:
    return f"connector-{source}.json"


def _latest(db: Session, org_id: str, source: str) -> Evidence | None:
    return (
        db.query(Evidence)
        .filter_by(org_id=org_id, original_filename=_filename(source), lifecycle_status="CURRENT")
        .filter(Evidence.deleted_at.is_(None))
        .order_by(Evidence.created_at.desc())
        .first()
    )


@router.get("")
def connector_status(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    org = db.get(Organization, actor.org_id)
    na_sources = set(org.dpdp_na_sources) if org else set()
    return [
        {
            "source": source,
            "label": label,
            "configured": bool(os.environ.get(_env_key(source, "URL"))),
            "evidence_id": latest.id if (latest := _latest(db, actor.org_id, source)) else None,
            "last_synced_at": latest.created_at.isoformat() if latest else None,
            "status": latest.status if latest else "NEVER_SYNCED",
            "applicable": source not in na_sources,
        }
        for source, (label, _, _) in SOURCES.items()
    ]


def _pull(source: str) -> bytes:
    url = os.environ.get(_env_key(source, "URL"))
    if not url:
        raise HTTPException(409, f"{source} collector is not configured")
    token = os.environ.get(_env_key(source, "TOKEN"))
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"} if token else {},
            timeout=float(os.environ.get("DPDP_CONNECTOR_TIMEOUT_S", "20")),
        )
        response.raise_for_status()
        if len(response.content) > MAX_SNAPSHOT_BYTES:
            raise ValueError("snapshot exceeds 1 MB")
        payload = response.json()
        attributes = payload.get("attributes") if isinstance(payload, dict) else None
        if not isinstance(attributes, dict):
            raise ValueError("collector response must contain an attributes object")
        allowed = SOURCES[source][2]
        filtered = {name: value for name, value in attributes.items() if name in allowed}
        if not filtered:
            raise ValueError(f"collector returned no supported attributes: {sorted(allowed)}")
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(502, f"{source} collector failed: {exc}") from exc

    return json.dumps(
        {"source": source, "collected_at": datetime.now(timezone.utc).isoformat(),
         "attributes": filtered},
        sort_keys=True, separators=(",", ":"),
    ).encode()


def _process(evidence_id: str, org_id: str, actor_label: str, request_id: str) -> None:
    with session_scope() as db:
        set_tenant(db, org_id)
        evidence = db.get(Evidence, evidence_id)
        if evidence is not None and evidence.org_id == org_id:
            process_evidence(db, CONTENT, evidence, actor_label, request_id)


def sync_connector_for_org(db: Session, org_id: str, actor_label: str, request_id: str, source: str) -> Evidence:
    """The actual pull-and-store work, independent of the HTTP request that
    triggers it. Shared by the button-click endpoint below and by
    app/monitor.py::sync_all_connectors (periodic/cron sync) so there is one
    implementation of "what a connector sync does", not two."""
    if source not in SOURCES:
        raise HTTPException(404, "unknown connector")

    data = _pull(source)
    digest = hashlib.sha256(data).hexdigest()
    prior = _latest(db, org_id, source)
    # collected_at makes snapshots distinct by design; the source facts and
    # collection time together are the evidence being preserved.
    version = prior.version + 1 if prior else 1
    evidence = Evidence(
        org_id=org_id,
        artefact_type=SOURCES[source][1],
        original_filename=_filename(source),
        filename=_filename(source),
        mime_type="application/vnd.grc.connector+json",
        size_bytes=len(data),
        sha256=digest,
        uploaded_by=actor_label,
        version=version,
        supersedes_id=prior.id if prior else None,
        status="STORED",
        description=f"Automatically collected from {SOURCES[source][0]}",
    )
    db.add(evidence)
    db.flush()
    evidence.storage_key = object_key(org_id, evidence.id, version, evidence.filename)
    get_storage().put(evidence.storage_key, data)
    if prior:
        prior.lifecycle_status = "SUPERSEDED"
    audit_log.record(
        db, actor=actor_label, request_id=request_id, action="CONNECTOR_SYNCED",
        entity_type="evidence", entity=evidence.id, org_id=org_id,
        detail={"source": source, "version": version, "attributes": list(json.loads(data)["attributes"])},
    )
    db.commit()
    return evidence


@router.post("/{source}/sync", status_code=202)
def sync_connector(
    source: str,
    background: BackgroundTasks,
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_session),
):
    if source not in SOURCES:
        raise HTTPException(404, "unknown connector")
    if not actor.org_id:
        raise HTTPException(403, "only the organisation can collect evidence")
    if not actor.can_write:
        raise deny_read_only(actor, "collect evidence")

    evidence = sync_connector_for_org(db, actor.org_id, actor.label(), actor.request_id, source)
    background.add_task(_process, evidence.id, actor.org_id, actor.label(), actor.request_id)
    return {"source": source, "evidence_id": evidence.id, "status": evidence.status}


@router.patch("/{source}/not-applicable")
def set_connector_not_applicable(
    source: str,
    body: dict,
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_session),
):
    """Scope a connector source out of DPDP readiness (see Organization.dpdp_na_sources
    and app/analytics.py::framework_readiness) — an org that genuinely has no AWS
    footprint shouldn't have that clause read as NO_EVIDENCE forever."""
    if source not in SOURCES:
        raise HTTPException(404, "unknown connector")
    if actor.role != "ORG_ADMIN":
        raise HTTPException(403, "only an organisation admin may change DPDP scope")

    org = db.get(Organization, actor.org_id)
    applicable = bool(body.get("applicable", True))
    na = set(org.dpdp_na_sources or [])
    if applicable:
        na.discard(source)
    else:
        na.add(source)
    org.dpdp_na_sources = sorted(na)
    audit_log.record(
        db, actor=actor.label(), request_id=actor.request_id, action="CONNECTOR_MARKED_NA",
        entity_type="organization", entity=org.id, org_id=org.id,
        detail={"source": source, "applicable": applicable},
    )
    db.commit()
    return {"source": source, "applicable": applicable, "dpdp_na_sources": org.dpdp_na_sources}
