"""Optional outbound notifications over one generic webhook (ADR-031).

Off unless NOTIFY_WEBHOOK_URL is set, in which case nothing here does anything. When set, two kinds
of message go out: event notices from the request path (a task assigned, evidence or an unlock
requested, a control locked), posted from a background thread so a slow webhook never slows a
request, and a digest from the monitor cron (`python -m app.monitor --notify`) of what needs
attention, de-duplicated through `notification_log` so a daily run does not repeat itself.

The payload is deliberately small and content-free: kind, severity, a one-line message that names
a framework, clause or task and never evidence text, a link, the organisation id and a time. It
carries `text` (Slack-style) and `content` (Discord-style) beside the structured fields, so a chat
webhook shows it directly and a script can read the fields. NOTIFY_WEBHOOK_SECRET, if set, signs the
body as `X-GRC-Signature: sha256=<hmac>`. Delivery is best effort: a failure is logged and never
raised, and never blocks or fails the action that caused it.

Environment is read at call time (not import time) so tests and deploys can change it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy.orm import Session

from app.models import NotificationLog

logger = logging.getLogger("app.notify")


def enabled() -> bool:
    return bool(os.environ.get("NOTIFY_WEBHOOK_URL"))


def _link(path: str) -> str:
    base = os.environ.get("NOTIFY_LINK_BASE_URL", "").rstrip("/")
    return f"{base}{path}" if base and path.startswith("/") else path


def _payload(kind: str, severity: str, message: str, link: str, org_id: str) -> dict:
    line = f"[{severity.upper()}] {message}"
    return {"text": line, "content": line, "kind": kind, "severity": severity, "message": message,
            "link": _link(link), "org_id": org_id, "at": datetime.now(timezone.utc).isoformat()}


def _post(payload: dict) -> bool:
    """One delivery attempt. Never raises."""
    url = os.environ.get("NOTIFY_WEBHOOK_URL", "")
    if not url:
        return False
    body = json.dumps(payload, sort_keys=True).encode()
    headers = {"Content-Type": "application/json"}
    secret = os.environ.get("NOTIFY_WEBHOOK_SECRET", "")
    if secret:
        headers["X-GRC-Signature"] = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    try:
        response = requests.post(url, data=body, headers=headers,
                                 timeout=float(os.environ.get("NOTIFY_TIMEOUT_S", "5")))
        if response.status_code >= 400:
            logger.warning("notify_rejected status=%s kind=%s", response.status_code, payload.get("kind"))
            return False
        return True
    except Exception as exc:  # noqa: BLE001 - delivery is best effort by design
        logger.warning("notify_failed kind=%s error=%s", payload.get("kind"), type(exc).__name__)
        return False


def _spawn(work) -> None:
    """Run delivery off the request thread. A seam so tests can run it inline."""
    threading.Thread(target=work, daemon=True).start()


def event(kind: str, severity: str, message: str, link: str, org_id: str) -> None:
    """A notice from the request path. Call after the change is committed."""
    if not enabled():
        return
    payload = _payload(kind, severity, message, link, org_id)
    _spawn(lambda: _post(payload))


def _key(item: dict) -> str:
    return hashlib.sha256(f"{item['kind']}|{item['link']}|{item['message']}".encode()).hexdigest()


def digest(db: Session, org_id: str, items: list[dict]) -> int:
    """Send what needs attention, once per item until NOTIFY_RESEND_DAYS (default 7) have passed.
    Returns how many were sent. Runs in the cron process, so it posts synchronously."""
    if not enabled() or not items:
        return 0
    resend_after = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        days=float(os.environ.get("NOTIFY_RESEND_DAYS", "7")))
    sent = 0
    for item in items:
        key = _key(item)
        row = db.query(NotificationLog).filter_by(org_id=org_id, item_key=key).one_or_none()
        if row is not None and row.sent_at.replace(tzinfo=None) > resend_after:
            continue
        if not _post(_payload(item["kind"], item["severity"], item["message"], item["link"], org_id)):
            continue
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if row is None:
            db.add(NotificationLog(org_id=org_id, item_key=key, sent_at=now))
        else:
            row.sent_at = now
        sent += 1
    db.commit()
    return sent
