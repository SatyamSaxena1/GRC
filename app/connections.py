"""Connections an organisation sets up itself (ADR-044): encryption of what it pastes, and the rules for
where the server is allowed to send.

Nothing here ever returns, logs or raises a secret. The only functions that see plain text are `encrypt`
(on the way in) and `decrypt` (at the moment of sending).
"""

from __future__ import annotations

import json
import os
import re
from urllib.parse import urlparse

import requests
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

KIND_CHAT = "CHAT_WEBHOOK"
KIND_GITHUB = "GITHUB_CHANGE_CONTROL"


def _keys() -> list[str]:
    return [k.strip() for k in os.environ.get("CONNECTIONS_KEY", "").split(",") if k.strip()]


def available() -> bool:
    """False until the operator sets CONNECTIONS_KEY: then nothing is ever stored, not even in the clear."""
    return bool(_keys())


def _fernet() -> MultiFernet:
    keys = _keys()
    if not keys:
        raise RuntimeError("CONNECTIONS_KEY is not set")
    return MultiFernet([Fernet(k) for k in keys])  # the first encrypts; every one can decrypt (rotation)


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        # The key was lost or replaced. Say so without a trace of the value.
        raise ValueError("the saved connection cannot be read with the current key; paste it again") from None


# Chat webhooks may only point at the chat services themselves, so a customer cannot aim the server at anything
# else (ADR-044, server-side request forgery). Host and path shape are both pinned.
_DISCORD = re.compile(r"^/api/webhooks/\d+/[A-Za-z0-9_\-]+/?$")
_SLACK = re.compile(r"^/services/[A-Za-z0-9_\-]+/[A-Za-z0-9_\-]+/[A-Za-z0-9_\-]+/?$")
ALLOWED_HOSTS = {
    "discord.com": _DISCORD, "ptb.discord.com": _DISCORD, "canary.discord.com": _DISCORD,
    "discordapp.com": _DISCORD, "hooks.slack.com": _SLACK,
}


def validate_chat_webhook(url: str) -> str:
    """The cleaned address, or ValueError saying what is wrong (never echoing the whole address)."""
    p = urlparse((url or "").strip())
    if p.scheme != "https":
        raise ValueError("the address must start with https://")
    if p.username or p.password or p.port not in (None, 443) or p.query or p.fragment:
        raise ValueError("that is not a plain chat webhook address")
    pattern = ALLOWED_HOSTS.get((p.hostname or "").lower())
    if pattern is None:
        raise ValueError("only Discord and Slack webhook addresses are accepted")
    if not pattern.match(p.path):
        raise ValueError("that does not look like a Discord or Slack webhook address")
    return f"https://{p.hostname.lower()}{p.path}"


def hint(url: str) -> str:
    """What the page may show: the service and the last four characters, nothing usable."""
    p = urlparse(url)
    return f"{p.hostname} ...{p.path.rstrip('/')[-4:]}"


def send(url: str, message: str, timeout: float = 5.0) -> tuple[bool, str]:
    """One delivery attempt to a chat webhook. Returns (ok, short reason); the reason is a status or an error
    class, never a response body or the address. Never raises, never follows a redirect."""
    try:
        response = requests.post(url, json={"content": message, "text": message}, timeout=timeout,
                                 allow_redirects=False)
    except Exception as exc:  # noqa: BLE001 - delivery is best effort by design
        return False, f"could not connect ({type(exc).__name__})"
    if 200 <= response.status_code < 300:
        return True, ""
    return False, f"the service answered HTTP {response.status_code}"


# ---- GitHub change control (ADR-045). One fixed host, so nothing the customer types can redirect the server:
# only a token and a list of owner/name repositories are accepted, never an address.
GITHUB_API = "https://api.github.com"
MAX_REPOS = 10
_REPO = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_]{20,255}$")


def validate_github(token: str, repos: list[str]) -> tuple[str, list[str]]:
    """The cleaned (token, repositories), or ValueError saying what is wrong (never echoing the token)."""
    token = (token or "").strip()
    if not _TOKEN.match(token):
        raise ValueError("that does not look like a GitHub access token")
    cleaned = list(dict.fromkeys(r.strip() for r in repos if r and r.strip()))
    if not cleaned:
        raise ValueError("name at least one repository, as owner/name")
    if len(cleaned) > MAX_REPOS:
        raise ValueError(f"at most {MAX_REPOS} repositories")
    for r in cleaned:
        if not _REPO.match(r):
            raise ValueError("repositories must look like owner/name")
    return token, cleaned


def pack_github(token: str, repos: list[str]) -> str:
    return json.dumps({"token": token, "repos": repos}, separators=(",", ":"))


def unpack_github(plain: str) -> tuple[str, list[str]]:
    data = json.loads(plain)
    return data["token"], list(data["repos"])


def github_hint(token: str, repos: list[str]) -> str:
    return f"{len(repos)} repositor{'y' if len(repos) == 1 else 'ies'}, token ...{token[-4:]}"


def github_session(token: str) -> requests.Session:
    s = requests.Session()
    s.trust_env = False
    s.headers.update({"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                      "Authorization": f"Bearer {token}"})
    return s


def github_test(token: str, repos: list[str], timeout: float = 10.0) -> tuple[bool, str]:
    """Can this token see every named repository? Returns (ok, short reason); never the token, never a body."""
    session = github_session(token)
    for repo in repos:
        try:
            r = session.get(f"{GITHUB_API}/repos/{repo}", timeout=timeout, allow_redirects=False)
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            return False, f"could not connect ({type(exc).__name__})"
        if r.status_code == 401:
            return False, "GitHub rejected the token"
        if r.status_code == 404:
            return False, f"{repo} was not found, or the token cannot see it"
        if r.status_code != 200:
            return False, f"GitHub answered HTTP {r.status_code} for {repo}"
    return True, ""
