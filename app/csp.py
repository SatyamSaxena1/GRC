"""Content-Security-Policy (ADR-066): starts in report-only mode, so a wrong policy is reported, never breaks the page.

The policy is written from what the app actually loads: its own scripts, styles and images, same-origin frames (the pitch
page and the document viewer), and one outside connection, the sign-in provider's token address. Styles allow inline
because React writes style attributes. `CSP_MODE` is `report-only` (the default), `enforce`, or `off`; flip to `enforce`
once the reports have been quiet.
"""

from __future__ import annotations

import json
import logging
import os
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, Response

logger = logging.getLogger("app.csp")
router = APIRouter(tags=["csp"])

MAX_REPORT_BYTES = 8192
MAX_LOGGED_PER_MINUTE = 30


def origin_of(url: str) -> str:
    parts = urlsplit(url or "")
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme in ("http", "https") and parts.netloc else ""


def policy(env: dict | None = None) -> str:
    env = os.environ if env is None else env
    sign_in = origin_of(env.get("VITE_OIDC_TOKEN_URL", ""))          # the browser exchanges the sign-in code there
    connect = " ".join(["'self'", sign_in]).strip()
    return "; ".join([
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        f"connect-src {connect}",
        "frame-src 'self' blob:",
        "frame-ancestors 'self'",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "report-uri /csp-report",
    ])


def header(env: dict | None = None) -> tuple[str, str] | None:
    """(header name, value) for the current mode, or None when it is off."""
    mode = (os.environ if env is None else env).get("CSP_MODE", "report-only").strip().lower()
    if mode == "off":
        return None
    name = "Content-Security-Policy" if mode == "enforce" else "Content-Security-Policy-Report-Only"
    return name, policy(env)


_window = {"start": 0.0, "count": 0}


def _clip(value: object, n: int = 160) -> str:
    return " ".join(str(value or "").split())[:n]


def describe(raw: bytes) -> list[str]:
    """One short line per violation in a report body. Both report formats are read. Only the directive, what was blocked
    and the page's path are kept, clipped: the body is written by whoever sent it."""
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return []
    items = data if isinstance(data, list) else [data]
    out = []
    for it in items[:5]:
        body = it.get("csp-report") if isinstance(it, dict) and "csp-report" in it else (it.get("body") if isinstance(it, dict) else None)
        if not isinstance(body, dict):
            continue
        directive = body.get("effective-directive") or body.get("effectiveDirective") or body.get("violated-directive")
        blocked = body.get("blocked-uri") or body.get("blockedURL") or body.get("blocked-url")
        page = urlsplit(str(body.get("document-uri") or body.get("documentURL") or "")).path
        out.append(f"directive={_clip(directive, 60)} blocked={_clip(blocked)} page={_clip(page, 80)}")
    return out


@router.post("/csp-report", include_in_schema=False)
async def csp_report(request: Request) -> Response:
    """Where browsers send policy violations. Public by necessity (a browser sends it with no credentials), so it keeps
    only a clipped summary, reads a small body, and logs a bounded number a minute."""
    raw = (await request.body())[:MAX_REPORT_BYTES]
    now = time.monotonic()
    if now - _window["start"] > 60:
        _window["start"], _window["count"] = now, 0
    for line in describe(raw):
        if _window["count"] >= MAX_LOGGED_PER_MINUTE:
            break
        _window["count"] += 1
        logger.warning("csp_violation %s", line)
    return Response(status_code=204)
