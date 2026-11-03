"""Read-only smoke check of a deployed GRC: is it up, is its database reachable, does it serve the
web app, and does it carry the API routes this build is supposed to have.

    python scripts/smoke_live.py                      # https://grc.blinkedit.me
    python scripts/smoke_live.py --url https://grc-demo-vu2u.onrender.com

Only GET requests, nothing authenticated, nothing written. Exit 0 when every check passes, 1 and the
reasons otherwise, so a deploy job or a person can use the same command. The database migration
head cannot be read over HTTP; check it where the database is (DEPLOYMENT.md).
"""

from __future__ import annotations

import argparse
import sys

import requests

DEFAULT_URL = "https://grc.blinkedit.me"
# Routes added since the first release: a deploy that serves an older build lacks them.
REQUIRED_ROUTES = (
    "/audit/links/{link_id}/register", "/audit/links/{link_id}/supersede", "/connectors/{source}/runs",
    "/tasks/bulk", "/controls/{control_id}/owners", "/controls/{control_id}/findings", "/findings",
)


def check(base: str, get=requests.get, timeout: float = 60) -> list[tuple[str, bool, str]]:
    """(name, ok, detail) per check. `get` is injectable so the logic can be tested offline."""
    out: list[tuple[str, bool, str]] = []
    base = base.rstrip("/")

    def fetch(path: str):
        try:
            return get(base + path, timeout=timeout)
        except requests.RequestException as exc:
            out.append((path, False, f"unreachable: {type(exc).__name__}"))
            return None

    r = fetch("/health/ready")
    if r is not None:
        try:
            body = r.json()
            ok = r.status_code == 200 and body.get("ready") is True and body.get("checks", {}).get("database") == "ok"
            out.append(("health/ready", ok, f"database={body.get('checks', {}).get('database')} "
                                            f"model={body.get('checks', {}).get('model')} ({body.get('checks', {}).get('model_name')})"))
        except ValueError:
            out.append(("health/ready", False, f"not JSON (HTTP {r.status_code})"))

    r = fetch("/login")
    if r is not None:
        out.append(("web app", r.status_code == 200 and "<div id=\"root\"" in r.text, f"HTTP {r.status_code}"))

    r = fetch("/openapi.json")
    if r is not None:
        try:
            paths = set(r.json().get("paths", {}))
            missing = [p for p in REQUIRED_ROUTES if p not in paths]
            out.append(("api routes", not missing, "all present" if not missing else f"missing: {', '.join(missing)}"))
        except ValueError:
            out.append(("api routes", False, f"openapi not JSON (HTTP {r.status_code})"))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default=DEFAULT_URL)
    args = ap.parse_args(argv)
    results = check(args.url)
    for name, ok, detail in results:
        print(f"{'ok  ' if ok else 'FAIL'} {name:<14} {detail}")
    return 0 if results and all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
