"""Read-only Google Workspace checks for the two attributes the Google Workspace evidence source needs (ADR-055).

Runs on the customer's own computer with a read-only Google sign-in they create and can revoke, and uploads two yes/no
answers. Standard library only, so this one file can be downloaded and run on its own. A check that cannot run (a missing
scope, a service error) is left out and reported, never reported as false.

    python gworkspace_readonly.py --url https://grc.example.com --dry-run
    (upload token in GRC_UPLOAD_TOKEN; Google sign-in in GOOGLE_ACCESS_TOKEN, or GOOGLE_CLIENT_ID +
     GOOGLE_CLIENT_SECRET + GOOGLE_REFRESH_TOKEN)

Scopes needed, both read-only: admin.directory.user.readonly and admin.reports.audit.readonly.
`collect(get)` takes a function that returns the parsed JSON for a Google URL, so tests need no network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

DIRECTORY = "https://admin.googleapis.com/admin/directory/v1"
REPORTS = "https://admin.googleapis.com/admin/reports/v1"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUDIT_WINDOW_DAYS = 30


def _super_admins(get: Callable[[str], dict]):
    page = ""
    while True:
        body = get(f"{DIRECTORY}/users?customer=my_customer&query=isAdmin%3Dtrue&maxResults=500{page}")
        yield from body.get("users", [])
        if not body.get("nextPageToken"):
            return
        page = f"&pageToken={body['nextPageToken']}"


def _privileged_access_mfa(get) -> bool:
    """Every active super administrator has 2-step verification enforced (not just turned on)."""
    admins = [u for u in _super_admins(get) if not u.get("suspended")]     # a suspended account cannot sign in
    if not admins:
        raise LookupError("no super administrators were returned")          # unknown, not a pass
    return all(u.get("isEnforcedIn2Sv") for u in admins)


def _access_logging(get) -> bool:
    """The admin audit log has recorded something in the last 30 days."""
    since = (datetime.now(timezone.utc) - timedelta(days=AUDIT_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return bool(get(f"{REPORTS}/activity/users/all/applications/admin?maxResults=1&startTime={since}").get("items"))


CHECKS: dict[str, Callable] = {
    "privileged_access_mfa": _privileged_access_mfa,
    "access_logging_enabled": _access_logging,
}


def collect(get: Callable[[str], dict]) -> dict:
    """{"attributes": {...}, "collection": {...}}: the shape every connector returns."""
    attributes: dict[str, bool] = {}
    errors: list[str] = []
    for name, check in CHECKS.items():
        try:
            attributes[name] = bool(check(get))
        except Exception as exc:  # noqa: BLE001 - a short code only, never a message that may name a user
            code = getattr(exc, "code", None)
            errors.append(f"{name} could not be checked ({code or type(exc).__name__})")
    return {"attributes": attributes, "collection": {"complete": not errors, "errors": errors, "region": "google-workspace"}}


def _url_ok(url: str) -> bool:
    """Tokens travel in headers, so they are only sent over https (or to this computer, for testing)."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1"))


def _open(request):
    """Open a request without following redirects (a redirect would carry a token to another address) and only over https
    (or to this computer, for testing)."""
    import urllib.request

    if not _url_ok(request.full_url):
        raise ValueError("not https")

    class _Stop(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    return urllib.request.build_opener(_Stop).open(request, timeout=30)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    import os
    import urllib.error
    import urllib.parse
    import urllib.request

    parser = argparse.ArgumentParser(description="Read-only Google Workspace checks, uploaded as two yes/no answers.")
    parser.add_argument("--url", required=True, help="your GRC address, e.g. https://grc.blinkedit.me")
    parser.add_argument("--token", default=os.environ.get("GRC_UPLOAD_TOKEN", ""), help="or set GRC_UPLOAD_TOKEN")
    parser.add_argument("--dry-run", action="store_true", help="print the answers, upload nothing")
    args = parser.parse_args(argv)

    access = os.environ.get("GOOGLE_ACCESS_TOKEN", "")
    if not access:
        env = {k: os.environ.get(k, "") for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")}
        if not all(env.values()):
            print("set GOOGLE_ACCESS_TOKEN, or GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_REFRESH_TOKEN")
            return 2
        form = urllib.parse.urlencode({"client_id": env["GOOGLE_CLIENT_ID"], "client_secret": env["GOOGLE_CLIENT_SECRET"],
                                       "refresh_token": env["GOOGLE_REFRESH_TOKEN"], "grant_type": "refresh_token"}).encode()
        try:
            with _open(urllib.request.Request(TOKEN_URL, data=form)) as r:
                access = json.load(r)["access_token"]
        except urllib.error.HTTPError as exc:
            print(f"Google refused the sign-in: HTTP {exc.code}")
            return 2
        except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
            print(f"could not get a Google access token: {type(exc).__name__}")
            return 2

    def get(url: str) -> dict:
        try:
            with _open(urllib.request.Request(url, headers={"Authorization": f"Bearer {access}"})) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            error = RuntimeError("google")
            error.code = f"HTTP {exc.code}"          # type: ignore[attr-defined]
            raise error from None

    result = collect(get)
    print(json.dumps(result, indent=2))
    if args.dry_run:
        return 0
    if not args.token:
        print("no upload token: set GRC_UPLOAD_TOKEN (or pass --token)")
        return 2
    if not _url_ok(args.url):
        print("the --url must start with https:// so the token is not sent in clear")
        return 2
    upload = urllib.request.Request(args.url.rstrip("/") + "/ingest/google-workspace", data=json.dumps(result).encode(),
                                    method="POST", headers={"Content-Type": "application/json", "Authorization": f"Bearer {args.token}"})
    try:
        with _open(upload) as response:
            print(f"uploaded: HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        print(f"upload refused: HTTP {exc.code}")
        return 1
    except (urllib.error.URLError, OSError) as exc:
        print(f"could not reach the server: {type(exc).__name__}")
        return 4
    return 0 if result["collection"]["complete"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
