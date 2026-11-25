"""Durable, privacy-minimal request log (ADR-070): the per-request access record kept in our own database for 365 days.

What is stored per request: time, method, path (never the query string), status, request id, how the caller
authenticated (present / none / demo / operator, never the credential), the organisation if one was resolved, the
caller's address and the duration. No bodies, no headers, no tokens, no email addresses.

A request never waits for this and never fails because of it: `record` only appends to an in-memory buffer; a
background task writes batches. If the database is down the buffer is capped and the oldest rows are dropped, with one
warning, not one per row.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, insert, text

from app import db
from app.models import RequestLog

logger = logging.getLogger("app.request_log")

MIN_RETENTION_DAYS = 365          # DPDP Rules 6(1)(e) and 8(3)
BUFFER_CAP = 5000                 # rows held while the database is away; beyond this the oldest are dropped
BATCH = 500
FLUSH_EVERY_S = 5
PRUNE_EVERY_S = 24 * 3600

_buffer: deque[dict] = deque(maxlen=BUFFER_CAP)
_skipped = {"health": 0, "csp_report": 0}   # counted, never stored: polled every few seconds / browser noise
_warned = False
_ID_OK = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def retention_days() -> int:
    """LOG_RETENTION_DAYS, never below 365 unless LOG_RETENTION_ALLOW_SHORT=1 says so out loud."""
    try:
        days = int(os.environ.get("LOG_RETENTION_DAYS", MIN_RETENTION_DAYS))
    except ValueError:
        days = MIN_RETENTION_DAYS
    if days < MIN_RETENTION_DAYS:
        if os.environ.get("LOG_RETENTION_ALLOW_SHORT", "") != "1":
            return MIN_RETENTION_DAYS
        logger.warning("request log retention set to %s days, below the %s the DPDP Rules ask for", days, MIN_RETENTION_DAYS)
    return max(days, 1)


def _clean_path(path: str) -> str:
    # an address in a path segment is personal data: keep the shape, drop the value
    return "/".join("{redacted}" if "@" in seg else seg for seg in path.split("/"))[:200]


def _ip(headers, client_host: str | None) -> str:
    """Cloudflare's own header, else the LAST forwarded hop (the one our host's proxy appended; earlier hops are the
    caller's to write), else the socket peer."""
    forwarded = (headers.get("x-forwarded-for") or "").split(",")[-1].strip()
    return (headers.get("cf-connecting-ip") or forwarded or client_host or "unknown")[:45]


def record(request, status: int, duration_ms: int) -> None:
    """Called from the request middleware after the response. Cannot raise."""
    try:
        path = request.url.path
        if path.startswith("/health/"):
            _skipped["health"] += 1
            return
        if path == "/csp-report":
            _skipped["csp_report"] += 1
            return
        token = request.headers.get("authorization", "")
        if request.headers.get("x-admin-key"):
            kind = "operator"      # a key was presented; whether it was right shows in the status
        elif token.removeprefix("Bearer ").strip() == "demo":
            kind = "demo"
        else:
            kind = "present" if token else "none"
        rid = getattr(request.state, "request_id", "")
        _buffer.append({
            "ts": datetime.now(timezone.utc), "method": request.method[:10], "path": _clean_path(path),
            "status": status, "request_id": rid if _ID_OK.match(rid) else "invalid",
            "auth": kind, "org_id": getattr(request.state, "org_id", None),
            "ip": _ip(request.headers, request.client.host if request.client else None),
            "duration_ms": duration_ms,
        })
    except Exception:  # noqa: BLE001 — logging must never break a request
        logger.debug("request_log_record_failed", exc_info=True)


def _scope_on(session) -> None:
    """request_logs is behind RLS that admits INSERT from anyone but SELECT/DELETE only with this setting, which no
    tenant code path ever sets. A no-op on SQLite."""
    if session.bind.dialect.name == "postgresql":
        session.execute(text("SELECT set_config('app.log_access', 'on', true)"))


def flush() -> int:
    """Write one batch. Returns rows written; on failure the batch goes back (the cap drops the oldest) and one
    warning is logged until a write succeeds again."""
    global _warned
    batch = [_buffer.popleft() for _ in range(min(BATCH, len(_buffer)))]
    if not batch:
        return 0
    try:
        with db.session_scope() as session:
            session.execute(insert(RequestLog), batch)
            session.commit()
    except Exception as exc:  # noqa: BLE001
        _buffer.extendleft(reversed(batch))
        if not _warned:
            logger.warning("request log database write failed (%s); buffering up to %s rows, then dropping the oldest",
                           type(exc).__name__, BUFFER_CAP)
            _warned = True
        return 0
    _warned = False
    return len(batch)


def prune(now: datetime | None = None) -> int:
    """Delete rows older than the retention period. Returns rows deleted; 0 (and a warning) if the database is away."""
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=retention_days())
    try:
        with db.session_scope() as session:
            _scope_on(session)
            n = session.execute(delete(RequestLog).where(RequestLog.ts < cutoff)).rowcount
            session.commit()
        return n or 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("request log prune failed (%s)", type(exc).__name__)
        return 0


async def run() -> None:
    """The background loop: flush every few seconds, prune once a day, the first prune a minute after start so boot is
    never held up. ponytail: the daily gate is in process, so a restart prunes again that day, which is harmless."""
    last_prune = time.monotonic() - PRUNE_EVERY_S + 60
    while True:
        await asyncio.sleep(FLUSH_EVERY_S)
        await asyncio.to_thread(flush)
        if time.monotonic() - last_prune >= PRUNE_EVERY_S:
            last_prune = time.monotonic()
            await asyncio.to_thread(prune)
