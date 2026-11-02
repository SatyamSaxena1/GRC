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

from app import audit_log, collection
from app.auth import Actor, current_actor, deny_read_only
from app.collectors import github_change_control
from app.content.load import load as load_content
from app.db import get_session, session_scope, set_tenant
from app.models import CollectionRun, Evidence, Organization
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
    # Change control (ADR-020): read-only facts about how code reached the default branch.
    "github": ("GitHub change control", "CHANGE_CONTROL_SNAPSHOT",
               set(github_change_control.ATTRIBUTES)),
    # Same snapshot, same rules, from GitLab (app/collectors/gitlab_change_control.py).
    "gitlab": ("GitLab change control", "CHANGE_CONTROL_SNAPSHOT",
               set(github_change_control.ATTRIBUTES)),
    "bitbucket": ("Bitbucket change control", "CHANGE_CONTROL_SNAPSHOT",
                  set(github_change_control.ATTRIBUTES)),
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
            # Whether the last run could be trusted (ADR-030); a failed run leaves older evidence in place.
            "collection": _run_view(_last_run(db, actor.org_id, source)),
        }
        for source, (label, _, _) in SOURCES.items()
    ]


def _last_run(db: Session, org_id: str, source: str, status: str | None = None) -> CollectionRun | None:
    query = db.query(CollectionRun).filter_by(org_id=org_id, source=source)
    if status:
        query = query.filter_by(status=status)
    return query.order_by(CollectionRun.started_at.desc()).first()


def _run_view(run: CollectionRun | None) -> dict | None:
    return None if run is None else {
        "status": run.status, "at": run.started_at.isoformat(), "expectation": run.expectation,
        "signals": run.signals}


def _record_run(db: Session, actor_label: str, request_id: str, org_id: str, source: str, assessment: dict,
                evidence_id: str | None) -> CollectionRun:
    """Every run leaves a row and an audit event, whatever it found."""
    run = CollectionRun(org_id=org_id, source=source, evidence_id=evidence_id,
                        started_at=datetime.now(timezone.utc).replace(tzinfo=None), **assessment)
    db.add(run)
    db.flush()
    audit_log.record(db, actor=actor_label, request_id=request_id, action="CONNECTOR_RUN",
                     entity_type="collection_run", entity=run.id, org_id=org_id,
                     detail={"source": source, "status": run.status, "expectation": run.expectation,
                             "signals": run.signals, "evidence_id": evidence_id})
    return run


def _pull(source: str) -> dict:
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

    snapshot = {"source": source, "collected_at": datetime.now(timezone.utc).isoformat(),
                "attributes": filtered, "declared": payload.get("collection")}
    if source in EXCEPTION_SOURCES:
        snapshot["exceptions"], snapshot["exceptions_left_out"] = _exception_rows(payload)
    return snapshot


# Sources whose collector also returns the per-item rows behind its counts. Stored inside
# the snapshot, so the rows are part of the same immutable, hashed evidence as the counts.
EXCEPTION_SOURCES = {"github", "gitlab", "bitbucket"}
_EXCEPTION_KEYS = {"kind", "repo", "ref", "url", "at", "author", "ai_assisted", "reasons"}


def _exception_rows(payload: dict) -> tuple[list[dict], int]:
    """The collector's rows, reduced to known keys and capped — never a reason to fail
    the sync: the counts are the evidence the rules judge, the rows are its working."""
    rows = payload.get("exceptions")
    if not isinstance(rows, list):
        return [], 0
    kept = [
        {k: v for k, v in row.items() if k in _EXCEPTION_KEYS}
        for row in rows[:github_change_control.MAX_EXCEPTIONS] if isinstance(row, dict)
    ]
    left_out = payload.get("exceptions_left_out")
    left_out = left_out if isinstance(left_out, int) and left_out >= 0 else 0
    return kept, left_out + max(0, len(rows) - github_change_control.MAX_EXCEPTIONS)


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

    try:
        snapshot = _pull(source)
    except HTTPException as exc:
        # "Could not collect" is recorded, not swallowed: earlier evidence stays CURRENT but the
        # connector reads as failed, so nothing here can look like a clean run (ADR-030).
        _record_run(db, actor_label, request_id, org_id, source,
                    {"status": "FAILED", "expectation": "NONE", "requested": {}, "returned": {},
                     "signals": [str(exc.detail)]}, None)
        db.commit()
        raise
    baseline = _last_run(db, org_id, source, "COMPLETE")
    assessment = collection.assess(snapshot.pop("declared"), snapshot["attributes"],
                                   baseline.returned if baseline else None)
    note = ""
    if assessment["status"] != "COMPLETE":
        # Withheld, not zero: a partial count read as a count would let a truncated run pass.
        snapshot["unverified_attributes"], snapshot["attributes"] = snapshot["attributes"], {}
        note = (f" Collection {assessment['status']}: {'; '.join(assessment['signals'])}. "
                "Values were withheld from evaluation; re-collect to get a verdict.")
    snapshot["collection"] = {"status": assessment["status"], "expectation": assessment["expectation"],
                              "signals": assessment["signals"]}
    data = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
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
        description=f"Automatically collected from {SOURCES[source][0]}.{note}".replace(".. ", ". "),
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
        detail={"source": source, "version": version, "attributes": list(json.loads(data)["attributes"]),
                "collection": assessment["status"]},
    )
    _record_run(db, actor_label, request_id, org_id, source, assessment, evidence.id)
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
