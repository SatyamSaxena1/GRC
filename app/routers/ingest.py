"""Results uploaded by a customer's own script (ADR-049). The only route here that is not signed in as a person: it is
authenticated by an upload token that only the organisation's admin can create, and it accepts nothing but a few named
yes/no answers (or one count), so there is nothing in it to run, fetch or follow.

Order matters, and is the point of the two dependencies below: the token is checked BEFORE the body is read, and the body
is read as a stream with a hard byte cap, so an anonymous caller cannot make the server buffer a large request (the cap is
enforced on what actually arrives, not on a Content-Length header the caller chooses).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
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


def _authenticate(source: str, authorization: str | None = Header(None), db: Session = Depends(get_session)) -> Connection:
    """The organisation's connection for this source, if (and only if) the bearer token is right. Every way of being wrong
    answers the same 401."""
    kind = connections.PUSH_KINDS.get(source)
    if kind is None:
        raise HTTPException(404, "that source does not take uploads")
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
    return row


async def _limited_json(request: Request, _row: Connection = Depends(_authenticate)) -> dict:
    """The request body as a JSON object, read as a stream and refused (413) the moment it passes the cap. Depends on the
    authentication above, so nothing is read for a caller who is not allowed to upload."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(413, "that is far larger than an upload should be")
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            raise HTTPException(413, "that is far larger than an upload should be")
        chunks.append(chunk)
    try:
        body = json.loads(b"".join(chunks) or b"null")
    except ValueError:
        raise HTTPException(422, "the upload must be JSON") from None
    if not isinstance(body, dict):
        raise HTTPException(422, "the upload must be a JSON object")
    return body


def _clean(source: str, body: dict) -> dict:
    """Only the source's own named attributes (yes/no, or a count for HR) and a short completeness note survive."""
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
    said = declared.get("complete")
    if not isinstance(said, bool):
        # A missing or malformed declaration is never read as "complete": an upload has to say so.
        errors = (errors + ["the upload did not say whether it was complete"])[:10]
        said = False
    return {"attributes": attributes,
            "collection": {"complete": said and not errors, "errors": errors,
                           "region": str(declared.get("region") or "")[:30]}}


@router.post("/{source}", status_code=202)
def ingest(source: str, background: BackgroundTasks, row: Connection = Depends(_authenticate),
           payload: dict = Depends(_limited_json), db: Session = Depends(get_session)):
    org_id = row.org_id
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
