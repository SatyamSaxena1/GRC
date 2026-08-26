"""Pushes closed facts (locked verdicts, resolved gaps) into CISO Assistant.

One-way: this app is source-of-truth for evidence/gaps/verdicts, CISO Assistant
is source-of-truth for risk/policy/vendor. Nothing is read back here — if a
caller needs risk context, it fetches CISO Assistant's API live rather than
letting a local copy drift (see docs/adr/010-ciso-assistant-integration.md).

A sync failure never blocks the auditor action that triggered it: the local
lock/resolution is what the auditee and auditor rely on regardless of whether
CISO Assistant heard about it yet. Retry is manual today (see
app/routers/ciso.py) — the CISO_SYNC_FAILED audit event is the mechanism for
noticing, not an automatic retry queue (see ADR-009: no outbox until a second
consumer needs one).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import requests

from app import audit_log
from app.models import CisoSyncState, EvidenceControlLink, GapRow

logger = logging.getLogger("app.ciso_sync")

TIMEOUT_S = float(os.environ.get("CISO_ASSISTANT_TIMEOUT_S", "10"))

# ponytail: CISO Assistant's requirement-assessment payload schema isn't
# published outside a running instance's Swagger/ReDoc. This is the one place
# that shape is assumed — confirm against a live instance before go-live and
# adjust here; nothing else in this module should need to change.
REQUIREMENT_ASSESSMENT_PATH = "requirement-assessments/"


class CisoAssistantClient:
    """Thin wrapper over CISO Assistant's REST API. Knox token auth, trailing
    slashes required on every endpoint (per its API docs)."""

    def __init__(self, base_url: str | None = None, token: str | None = None):
        # Read env at construction, not import, so tests/ops can override without
        # a process restart (os.environ.get here, not the module-level constant).
        self.base_url = (base_url if base_url is not None
                         else os.environ.get("CISO_ASSISTANT_BASE_URL", "")).rstrip("/")
        self.token = token if token is not None else os.environ.get("CISO_ASSISTANT_API_TOKEN", "")

    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    def _headers(self) -> dict:
        return {"Authorization": f"Token {self.token}"}

    def upsert_requirement_assessment(self, external_id: str, payload: dict) -> str:
        """Creates or updates the CISO Assistant object tracking one of our
        evidence-control-link verdicts. Returns its CISO Assistant object id.

        Uses our own external_id as an idempotency key candidate; the exact
        matching semantics depend on the live instance's API and may need a
        two-step (search-then-create-or-patch) call once wired up for real.
        """
        resp = requests.post(
            f"{self.base_url}/api/{REQUIREMENT_ASSESSMENT_PATH}",
            json={**payload, "external_id": external_id},
            headers=self._headers(), timeout=TIMEOUT_S,
        )
        resp.raise_for_status()
        return resp.json()["id"]


def _sync(db, actor_label: str, request_id: str, org_id: str,
          entity_type: str, entity_id: str, payload: dict) -> None:
    client = CisoAssistantClient()
    state = db.query(CisoSyncState).filter_by(
        org_id=org_id, local_entity_type=entity_type, local_entity_id=entity_id,
    ).one_or_none()
    if state is None:
        state = CisoSyncState(
            org_id=org_id, local_entity_type=entity_type, local_entity_id=entity_id,
        )
        db.add(state)

    if not client.configured():
        state.last_sync_status = "SKIPPED"
        state.last_error = "CISO_ASSISTANT_BASE_URL/CISO_ASSISTANT_API_TOKEN not set"
        return

    try:
        object_id = client.upsert_requirement_assessment(
            external_id=f"{entity_type}:{entity_id}", payload=payload,
        )
        state.ciso_assistant_object_id = object_id
        state.last_sync_status = "OK"
        state.last_error = ""
    except requests.RequestException as exc:
        logger.warning("ciso_sync_failed entity_type=%s entity_id=%s error=%s",
                       entity_type, entity_id, exc)
        state.last_sync_status = "FAILED"
        state.last_error = str(exc)
        audit_log.record(
            db, actor=actor_label, request_id=request_id, action="CISO_SYNC_FAILED",
            entity_type=entity_type, entity=entity_id, org_id=org_id,
            detail={"error": str(exc)},
        )
    finally:
        state.last_synced_at = datetime.now(timezone.utc)


def push_verdict(db, actor_label: str, request_id: str, link: EvidenceControlLink,
                 org_id: str) -> None:
    _sync(
        db, actor_label, request_id, org_id,
        entity_type="evidence_control_link", entity_id=link.id,
        payload={
            "framework": link.framework, "clause": link.clause,
            "result": link.auditor_verdict or link.verdict,
            "locked": link.locked,
        },
    )


def push_gap_resolution(db, actor_label: str, request_id: str, gap: GapRow,
                        org_id: str) -> None:
    _sync(
        db, actor_label, request_id, org_id,
        entity_type="gap", entity_id=gap.id,
        payload={
            "status": gap.status, "attribute": gap.attribute,
            "resolution_reason": gap.resolution_reason,
        },
    )
