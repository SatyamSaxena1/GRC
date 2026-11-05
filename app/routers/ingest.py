"""Results uploaded by a customer's own script (ADR-049). The only route here that is not signed in as a person: it is
authenticated by an upload token that only the organisation's admin can create, and it accepts nothing but four yes/no
answers, so there is nothing in it to run, fetch or follow.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app import connections
from app.db import get_session, set_tenant
from app.models import CollectionRun, Connection
from app.routers import connectors

router = APIRouter(prefix="/ingest", tags=["ingest"])

MAX_BODY_BYTES = 20_000
MIN_SECONDS_BETWEEN = 30
MAX_COUNT = 1_000_000


def _deny() -> HTTPException:
    return HTTPException(401, "invalid upload token")


def _clean(source: str, body: dict) -> dict:
    """Only the source's own named yes/no attributes and a short completeness note survive; everything else is dropped."""
    allowed = connectors.SOURCES[source][2]
    attributes = body.get("attributes")
    if not isinstance(attributes, dict) or not attributes:
        raise HTTPException(422, "send at least one attribute")
    unknown = sorted(set(attributes) - allowed)
    if source in connections.COUNT_SOURCES:
        # whole numbers, 0 or more; a bool is an int in Python but is not a count
        well_formed = all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= MAX_COUNT for v in attributes.values())
        kind = f"whole numbers from 0 to {MAX_COUNT}"
    else:
        well_formed = all(isinstance(v, bool) for v in attributes.values())
        kind = "yes/no values"
    if unknown or not well_formed:
        raise HTTPException(422, f"attributes must be {kind} among: {', '.join(sorted(allowed))}")
    declared = body.get("collection") if isinstance(body.get("collection"), dict) else {}
    errors = [str(e)[:200] for e in (declared.get("errors") or []) if isinstance(e, str)][:10]
    return {"attributes": attributes,
            "collection": {"complete": bool(declared.get("complete", True)) and not errors, "errors": errors,
                           "region": str(declared.get("region") or "")[:30]}}


@router.post("/{source}", status_code=202)
def ingest(source: str, background: BackgroundTasks, payload: dict = Body(...), authorization: str | None = Header(None),
               content_length: int | None = Header(None), db: Session = Depends(get_session)):
    kind = connections.PUSH_KINDS.get(source)
    if kind is None:
        raise HTTPException(404, "that source does not take uploads")
    if content_length is not None and content_length > MAX_BODY_BYTES:
        raise HTTPException(413, "that is far larger than an AWS result")
    parts = connections.split_push_token((authorization or "").removeprefix("Bearer ").strip())
    if parts is None or not connections.available():
        raise _deny()
    org_id, secret = parts
    set_tenant(db, org_id)                                  # the token names the tenant; RLS then scopes everything
    row = db.query(Connection).filter_by(org_id=org_id, kind=kind).one_or_none()
    if row is None:
        raise _deny()
    try:
        stored = json.loads(connections.decrypt(row.config_encrypted))["token_hash"]
    except (ValueError, KeyError):
        raise _deny() from None
    if not connections.push_token_matches(stored, secret):
        raise _deny()

    clean = _clean(source, payload)
    last = (db.query(CollectionRun).filter_by(org_id=org_id, source=source)
            .order_by(CollectionRun.started_at.desc()).first())
    if last is not None and last.started_at > datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=MIN_SECONDS_BETWEEN):
        raise HTTPException(429, "results were received a moment ago; try again shortly")

    evidence = connectors.sync_connector_for_org(db, org_id, f"upload:{source}", "", source, uploaded=clean)
    row.status, row.last_error, row.last_tested_at = "OK", "", datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    background.add_task(connectors._process, evidence.id, org_id, f"upload:{source}", "")
    return {"evidence_id": evidence.id, "complete": clean["collection"]["complete"]}
