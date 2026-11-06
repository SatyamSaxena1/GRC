"""Read-only Microsoft 365 checks for the two attributes the Microsoft 365 evidence source needs (ADR-050).

Runs in the customer's own tenant with a read-only app registration they create and can revoke, and uploads two
yes/no answers. Standard library only, so this one file can be downloaded and run on its own. A check that cannot run
(a missing permission, a service error) is left out and reported, never reported as false.

    python m365_readonly.py --url https://grc.example.com --tenant <tenant id> --client-id <app id> --dry-run
    (client secret in M365_CLIENT_SECRET, upload token in GRC_UPLOAD_TOKEN)

`collect(get)` takes a function that returns the parsed JSON for a Graph URL, so tests need no network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

GRAPH = "https://graph.microsoft.com/v1.0"
AUDIT_WINDOW_DAYS = 30


def _pages(get: Callable[[str], dict], url: str):
    while url:
        body = get(url)
        yield from body.get("value", [])
        url = body.get("@odata.nextLink", "")


def _privileged_access_mfa(get) -> bool:
    """Every administrator account has registered multi-factor authentication."""
    admins = list(_pages(get, f"{GRAPH}/reports/authenticationMethods/userRegistrationDetails?$filter=isAdmin eq true&$top=999"))
    if not admins:
        raise LookupError("no administrator accounts were returned")     # unknown, not a pass
    return all(a.get("isMfaRegistered") for a in admins)


def _access_logging(get) -> bool:
    """The directory audit log has recorded something in the last 30 days."""
    since = (datetime.now(timezone.utc) - timedelta(days=AUDIT_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = get(f"{GRAPH}/auditLogs/directoryAudits?$top=1&$filter=activityDateTime ge {since}").get("value", [])
    return bool(rows)


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
    return {"attributes": attributes, "collection": {"complete": not errors, "errors": errors, "region": "m365"}}


def _url_ok(url: str) -> bool:
    """The upload token travels in a header, so it is only sent over https (or to this computer, for testing)."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1"))


def _post(request):
    """POST without following redirects: a redirect would carry the token to another address."""
    import urllib.request

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

    parser = argparse.ArgumentParser(description="Read-only Microsoft 365 checks, uploaded as two yes/no answers.")
    parser.add_argument("--url", required=True, help="your GRC address, e.g. https://grc.blinkedit.me")
    parser.add_argument("--tenant", default=os.environ.get("M365_TENANT_ID", ""), help="your Entra tenant id")
    parser.add_argument("--client-id", default=os.environ.get("M365_CLIENT_ID", ""), help="the read-only app's id")
    parser.add_argument("--token", default=os.environ.get("GRC_UPLOAD_TOKEN", ""), help="or set GRC_UPLOAD_TOKEN")
    parser.add_argument("--dry-run", action="store_true", help="print the answers, upload nothing")
    args = parser.parse_args(argv)

    access = os.environ.get("GRAPH_ACCESS_TOKEN", "")
    if not access:
        secret = os.environ.get("M365_CLIENT_SECRET", "")
        if not (args.tenant and args.client_id and secret):
            print("give --tenant, --client-id and M365_CLIENT_SECRET (or GRAPH_ACCESS_TOKEN)")
            return 2
        form = urllib.parse.urlencode({"client_id": args.client_id, "client_secret": secret, "grant_type": "client_credentials",
                                       "scope": "https://graph.microsoft.com/.default"}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    f"https://login.microsoftonline.com/{urllib.parse.quote(args.tenant)}/oauth2/v2.0/token", data=form),
                    timeout=30) as r:
                access = json.load(r)["access_token"]
        except urllib.error.HTTPError as exc:
            print(f"Microsoft refused the app's credentials: HTTP {exc.code}")
            return 2

    def get(url: str) -> dict:
        request = urllib.request.Request(url.replace(" ", "%20"), headers={"Authorization": f"Bearer {access}"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            error = RuntimeError("graph")
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
    upload = urllib.request.Request(args.url.rstrip("/") + "/ingest/m365", data=json.dumps(result).encode(), method="POST",
                                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {args.token}"})
    try:
        with _post(upload) as response:
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
