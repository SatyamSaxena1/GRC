"""Connections an organisation sets up itself (ADR-044): encryption of what it pastes, and the rules for
where the server is allowed to send.

Nothing here ever returns, logs or raises a secret. The only functions that see plain text are `encrypt`
(on the way in) and `decrypt` (at the moment of sending).
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import requests
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

KIND_CHAT = "CHAT_WEBHOOK"


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
