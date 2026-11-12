"""Create, link and block sign-in identities in Auth0 when someone is invited or deactivated (ADR-047).

Off unless AUTH0_DOMAIN, AUTH0_M2M_CLIENT_ID and AUTH0_M2M_CLIENT_SECRET are all set: then inviting only writes our
own row, exactly as before. The server never chooses, sees or stores anyone's password. An invited person gets a
random password nobody knows plus a one-time password-change link, shown once to the admin and never kept.

Nothing here logs or raises a secret, a token or a link. Errors carry a short reason only.
"""

from __future__ import annotations

import os
import re
import secrets
import time

import requests

CONNECTION = os.environ.get("AUTH0_CONNECTION", "Username-Password-Authentication")
TICKET_TTL_S = 7 * 24 * 3600
TIMEOUT_S = 10.0
_HOST = re.compile(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$")
_cache: dict = {"token": "", "until": 0.0}


class Auth0Error(Exception):
    """A short, secret-free reason the sign-in service could not do what was asked."""


def _settings() -> tuple[str, str, str] | None:
    domain = (os.environ.get("AUTH0_DOMAIN") or "").strip().lower()
    cid, secret = os.environ.get("AUTH0_M2M_CLIENT_ID", ""), os.environ.get("AUTH0_M2M_CLIENT_SECRET", "")
    if not (domain and cid and secret):
        return None
    if not _HOST.match(domain):
        raise Auth0Error("AUTH0_DOMAIN must be a plain hostname such as example.eu.auth0.com")
    return domain, cid, secret


def enabled() -> bool:
    return all(os.environ.get(k) for k in ("AUTH0_DOMAIN", "AUTH0_M2M_CLIENT_ID", "AUTH0_M2M_CLIENT_SECRET"))


def _call(method: str, path: str, *, json: dict | None = None, params: dict | None = None):
    settings = _settings()
    if settings is None:
        raise Auth0Error("sign-in management is not configured")
    domain, cid, secret = settings
    try:
        if time.time() >= _cache["until"]:
            r = requests.request("POST", f"https://{domain}/oauth/token", timeout=TIMEOUT_S, allow_redirects=False,
                                 json={"grant_type": "client_credentials", "client_id": cid, "client_secret": secret,
                                       "audience": f"https://{domain}/api/v2/"})
            if r.status_code != 200:
                raise Auth0Error(f"the sign-in service refused our credentials (HTTP {r.status_code})")
            body = r.json()
            _cache.update(token=body["access_token"], until=time.time() + max(60, int(body.get("expires_in", 3600)) - 60))
        r = requests.request(method, f"https://{domain}/api/v2{path}", json=json, params=params, timeout=TIMEOUT_S,
                             allow_redirects=False, headers={"Authorization": f"Bearer {_cache['token']}"})
    except Auth0Error:
        raise
    except Exception as exc:  # noqa: BLE001 - class only; the message could carry a URL or token
        raise Auth0Error(f"could not reach the sign-in service ({type(exc).__name__})") from None
    if r.status_code == 401:
        _cache["until"] = 0.0
    if r.status_code >= 400:
        raise Auth0Error(f"the sign-in service answered HTTP {r.status_code}")
    return r.json() if r.content else None


def _find(email: str) -> dict | None:
    rows = _call("GET", "/users-by-email", params={"email": email}) or []
    return next((u for u in rows if (u.get("email") or "").lower() == email.lower()), None)


def invite(email: str, result_url: str = "") -> str:
    """Make sure a login exists for this email and return a one-time password-change link. An existing login is
    reused, never overwritten. A person who already signs in another way (Google, say) has no password to change, so
    nothing is made and "" is returned: they sign in as they always do. Raises Auth0Error."""
    email = email.strip().lower()
    user = _find(email)
    if user is not None and not str(user.get("user_id", "")).startswith("auth0|"):
        return ""
    if user is None:
        user = _call("POST", "/users", json={"email": email, "connection": CONNECTION, "email_verified": False,
                                              "verify_email": False, "password": secrets.token_urlsafe(32)})
    body = {"user_id": user["user_id"], "ttl_sec": TICKET_TTL_S}
    if result_url:
        body["result_url"] = result_url
    return _call("POST", "/tickets/password-change", json=body)["ticket"]


def set_blocked(email: str, blocked: bool) -> bool:
    """Block or unblock this person's login. False when they have no login there (nothing to do). Raises Auth0Error."""
    user = _find(email.strip().lower())
    if user is None:
        return False
    _call("PATCH", f"/users/{user['user_id']}", json={"blocked": blocked})
    return True
