"""Connections an organisation sets up itself (ADR-044): encryption of what it pastes, and the rules for
where the server is allowed to send.

Nothing here ever returns, logs or raises a secret. The only functions that see plain text are `encrypt`
(on the way in) and `decrypt` (at the moment of sending).
"""

from __future__ import annotations

import json
import os
import re
import time
from urllib.parse import quote, urlparse

import jwt
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

KIND_CHAT = "CHAT_WEBHOOK"
KIND_GITHUB = "GITHUB_CHANGE_CONTROL"
KIND_AWS = "AWS_PUSH"
KIND_M365 = "M365_PUSH"
KIND_HRMS = "HRMS_PUSH"
KIND_GWS = "GOOGLE_WORKSPACE_PUSH"
# Sources whose evidence the customer uploads from their own script (ADR-049, ADR-050, ADR-055): source -> connection kind.
PUSH_KINDS = {"aws": KIND_AWS, "m365": KIND_M365, "hrms": KIND_HRMS, "google-workspace": KIND_GWS}
# Sources whose uploaded answers are counts (whole numbers, 0 or more) rather than yes/no.
COUNT_SOURCES = {"hrms"}


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


def retrying_adapter() -> HTTPAdapter:
    """One flaky GitHub answer (a 502 or a dropped connection) must not throw away a multi-minute collection of
    hundreds of calls. Retries 5xx and connection errors a few times with a growing pause, honouring Retry-After;
    after the last attempt the response is returned as is, so the collector's own error handling reports it."""
    return HTTPAdapter(max_retries=Retry(total=4, backoff_factor=1.0, status_forcelist=(500, 502, 503, 504),
                                         allowed_methods=None, respect_retry_after_header=True,
                                         raise_on_status=False))


def github_session(token: str) -> requests.Session:
    s = requests.Session()
    s.mount("https://", retrying_adapter())
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
# ---- GitHub App (ADR-068): one click instead of a hand-made token. The platform is registered once as a GitHub App with
# fixed read-only permissions; an organisation installs it on the repositories it chooses. Nothing long-lived is kept:
# only the installation number. At collection time the server proves it is the App (a short signed request) and gets a
# one-hour token for that installation. Every host is fixed (api.github.com, github.com), so nothing a customer types
# can redirect the server.
APP_ENV = ("GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY", "GITHUB_APP_SLUG", "GITHUB_APP_CLIENT_ID", "GITHUB_APP_CLIENT_SECRET")
STATE_TTL_S = 900
_SLUG = re.compile(r"^[A-Za-z0-9-]{1,60}$")


def app_available() -> bool:
    """True only when every App setting and the connections key are present, and the App's slug is plain."""
    return available() and all(os.environ.get(k) for k in APP_ENV) and bool(_SLUG.match(os.environ["GITHUB_APP_SLUG"]))


_PEM = re.compile(r"-----BEGIN ([A-Z ]+)-----(.*?)-----END \1-----", re.S)


def normalise_pem(raw: str) -> str:
    """A private key as a settings box often leaves it: line breaks turned into spaces, written as a literal backslash-n
    on one line, wrapped in quotes, or with stray blank lines. The base64 body is the same in every case, so it is cut out
    and laid back in the standard 64-character lines between the BEGIN and END markers."""
    s = raw.strip().strip("\"'").replace("\\n", "\n")
    m = _PEM.search(s)
    if m is None:
        return s
    body = re.sub(r"\s+", "", m.group(2))
    lines = [body[i:i + 64] for i in range(0, len(body), 64)]
    return f"-----BEGIN {m.group(1)}-----\n" + "\n".join(lines) + f"\n-----END {m.group(1)}-----\n"


def _app_jwt(now: float | None = None) -> str:
    """A signed, nine-minute proof that this server is the App (RS256 over the App's private key). An unreadable key is
    reported as a ValueError with a plain reason, never as a crash and never with any part of the key."""
    t = int(now if now is not None else time.time())
    try:
        return jwt.encode({"iat": t - 60, "exp": t + 540, "iss": os.environ["GITHUB_APP_ID"]},
                          normalise_pem(os.environ["GITHUB_APP_PRIVATE_KEY"]), algorithm="RS256")
    except (jwt.PyJWTError, ValueError, TypeError):
        raise ValueError("the GitHub App private key on this server cannot be read; paste the whole .pem file again") from None


def app_check(timeout: float = 10.0) -> tuple[bool, str]:
    """Do the App settings on this server work? Signs in to GitHub as the App (GET /app) and says what happened, in words that
    never include the key. This is how a wrong or mangled private key, or a wrong App ID, is told apart from a problem with
    one install, without installing anything."""
    try:
        token = _app_jwt()
    except ValueError as exc:
        return False, str(exc)
    try:
        r = github_session(token).get(f"{GITHUB_API}/app", timeout=timeout, allow_redirects=False)
    except requests.RequestException as exc:
        return False, f"could not reach GitHub ({type(exc).__name__})"
    if r.status_code == 200:
        return True, f"GitHub accepts this server as the App \"{r.json().get('slug', '')}\""
    hint = " (the private key or App ID does not match the App)" if r.status_code == 401 else ""
    return False, f"GitHub answered HTTP {r.status_code}{hint}"


def new_state(org_id: str) -> str:
    """A tamper-proof, 15-minute value that ties an install to the organisation that started it."""
    return encrypt(json.dumps({"org": org_id}))


def read_state(state: str) -> str:
    """The organisation id inside a state value, or ValueError when it is forged, old or unreadable."""
    try:
        return json.loads(_fernet().decrypt(state.encode(), ttl=STATE_TTL_S))["org"]
    except (InvalidToken, ValueError, KeyError, TypeError, UnicodeError):
        raise ValueError("this install link has expired or was not started here; start the install again") from None


def install_url(org_id: str) -> str:
    return f"https://github.com/apps/{os.environ['GITHUB_APP_SLUG']}/installations/new?state={quote(new_state(org_id))}"


def user_owns_installation(code: str, installation_id: int, timeout: float = 10.0) -> bool:
    """Did the person who came back from GitHub really get this installation? The installation number travels in the
    browser address and could be swapped for someone else's, so GitHub is asked, with the person's own one-time code,
    whether that installation is among theirs."""
    r = requests.post("https://github.com/login/oauth/access_token", timeout=timeout, allow_redirects=False,
                      headers={"Accept": "application/json"},
                      data={"client_id": os.environ["GITHUB_APP_CLIENT_ID"],
                            "client_secret": os.environ["GITHUB_APP_CLIENT_SECRET"], "code": code})
    token = r.json().get("access_token") if r.status_code == 200 else None
    if not token:
        return False
    session = github_session(token)
    for page in range(1, 11):
        resp = session.get(f"{GITHUB_API}/user/installations", params={"per_page": 100, "page": page},
                           timeout=timeout, allow_redirects=False)
        if resp.status_code != 200:
            return False
        found = resp.json().get("installations", [])
        if any(i.get("id") == installation_id for i in found):
            return True
        if len(found) < 100:
            return False
    return False


def installation_token(installation_id: int, timeout: float = 10.0) -> str:
    """A one-hour read token for one installation. Raises ValueError with a short reason; never the key or the token."""
    r = github_session(_app_jwt()).post(f"{GITHUB_API}/app/installations/{int(installation_id)}/access_tokens",
                                        timeout=timeout, allow_redirects=False)
    if r.status_code != 201:
        raise ValueError(f"GitHub answered HTTP {r.status_code} when asked for access to the installation")
    return r.json()["token"]


def installation_repos(token: str, timeout: float = 10.0) -> list[str]:
    """The repositories the installation was given, as owner/name."""
    session, names = github_session(token), []
    for page in range(1, 11):
        r = session.get(f"{GITHUB_API}/installation/repositories", params={"per_page": 100, "page": page},
                        timeout=timeout, allow_redirects=False)
        if r.status_code != 200:
            raise ValueError(f"GitHub answered HTTP {r.status_code} when listing the installation's repositories")
        batch = r.json().get("repositories", [])
        names += [x["full_name"] for x in batch if _REPO.match(x.get("full_name", ""))]
        if len(batch) < 100:
            break
    return names


def pack_github_app(installation_id: int, repos: list[str]) -> str:
    return json.dumps({"installation_id": int(installation_id), "repos": repos}, separators=(",", ":"))


def github_app_hint(repos: list[str]) -> str:
    return f"GitHub App, {len(repos)} repositor{'y' if len(repos) == 1 else 'ies'}"


def github_credentials(plain: str) -> tuple[str, list[str]]:
    """(token, repositories) from a saved GitHub connection of either kind. A pasted-token connection returns what was
    saved. An App connection asks GitHub for a fresh one-hour token and for the repositories it can see right now, so a
    repository added or removed in GitHub is picked up without anyone editing anything here."""
    data = json.loads(plain)
    if "installation_id" not in data:
        return data["token"], list(data["repos"])
    if not app_available():
        raise ValueError("the GitHub App is not set up on this server")
    token = installation_token(data["installation_id"])
    repos = installation_repos(token)[:MAX_REPOS]
    if not repos:
        raise ValueError("the GitHub App has no repositories shared with it")
    return token, repos


# ---- AWS by upload (ADR-049). The platform holds no AWS identity and calls nothing in AWS. The customer runs a small
# read-only script in their own account; it posts four yes/no answers to us with an upload token. The token carries
# the organisation id (not secret) so the right tenant can be selected before anything is read; only its SHA-256 is kept.
import hashlib
import hmac
import secrets as _secrets


def new_push_token(org_id: str) -> tuple[str, str]:
    """(the token to show once, the hash to keep)."""
    secret = _secrets.token_urlsafe(32)
    return f"{org_id}.{secret}", hashlib.sha256(secret.encode()).hexdigest()


def split_push_token(raw: str) -> tuple[str, str] | None:
    org_id, _, secret = (raw or "").partition(".")
    return (org_id, secret) if org_id and len(secret) >= 20 else None


def push_token_matches(stored_hash: str, secret: str) -> bool:
    return hmac.compare_digest(stored_hash, hashlib.sha256(secret.encode()).hexdigest())


def push_hint(token: str) -> str:
    return f"upload token ...{token[-4:]}"
