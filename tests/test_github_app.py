"""The GitHub App install (ADR-068): one click instead of a pasted token. GitHub is replaced by a fake, so nothing here
touches the network. What is proved: the signed install value ties an install to one organisation and expires; the
installation must be the person's own; only the installation number is stored, never a token; the server's proof of
identity is a short RS256 token; and a pasted-token connection still works unchanged."""

from __future__ import annotations

import json
import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.orm import Session

from app import connections
from app import db as db_module
from app.models import Connection

H = lambda org: {"authorization": f"org:{org}"}  # noqa: E731
INSTALL = 4242
TOKEN = "ghs_installationTOKENvalue1234567890"


@pytest.fixture(scope="module")
def pem():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return private, public


@pytest.fixture()
def app_env(monkeypatch, pem):
    monkeypatch.setenv("CONNECTIONS_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("GITHUB_APP_ID", "123456")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", pem[0])
    monkeypatch.setenv("GITHUB_APP_SLUG", "grc-evidence")
    monkeypatch.setenv("GITHUB_APP_CLIENT_ID", "Iv1.clientid")
    monkeypatch.setenv("GITHUB_APP_CLIENT_SECRET", "clientsecretvalue")


class Resp:
    def __init__(self, code, body):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


class FakeGitHub:
    """Answers the five calls the install makes. `owned` is the list of installation ids the person owns."""

    def __init__(self, owned=(INSTALL,), repos=("acme/api", "acme/web"), code_ok=True):
        self.owned, self.repos, self.code_ok, self.calls = list(owned), list(repos), code_ok, []

    def post_oauth(self, url, **kw):
        self.calls.append(("POST", url))
        return Resp(200, {"access_token": "gho_usertoken"} if self.code_ok else {"error": "bad_verification_code"})

    def session(self, token):
        outer = self

        class S:
            def get(self, url, **kw):
                outer.calls.append(("GET", url, token))
                if url.endswith("/user/installations"):
                    return Resp(200, {"installations": [{"id": i} for i in outer.owned]})
                if url.endswith("/installation/repositories"):
                    return Resp(200, {"repositories": [{"full_name": r} for r in outer.repos]})
                return Resp(404, {})

            def post(self, url, **kw):
                outer.calls.append(("POST", url, token))
                if url.endswith(f"/app/installations/{INSTALL}/access_tokens"):
                    return Resp(201, {"token": TOKEN})
                return Resp(404, {})
        return S()


@pytest.fixture()
def gh(monkeypatch, app_env):
    fake = FakeGitHub()
    monkeypatch.setattr(connections.requests, "post", fake.post_oauth)
    monkeypatch.setattr(connections, "github_session", fake.session)
    return fake


def _org(client, bootstrap):
    return bootstrap(client)[0]


def _state(client, org):
    url = client.get("/connections/github-app", headers=H(org)).json()["install_url"]
    return parse_qs(urlparse(url).query)["state"][0]


def _complete(client, org, state, installation=INSTALL, code="onetimecode1"):
    return client.post("/connections/github-app/complete", headers=H(org),
                       json={"installation_id": installation, "code": code, "state": state})


# --- availability ---------------------------------------------------------------------------------------------------
def test_without_the_app_settings_nothing_is_offered(client, bootstrap, monkeypatch):
    for k in connections.APP_ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CONNECTIONS_KEY", Fernet.generate_key().decode())
    org = _org(client, bootstrap)
    assert client.get("/connections/github-app", headers=H(org)).json() == {"available": False}
    assert client.get("/connections", headers=H(org)).json()["github_app_available"] is False
    assert _complete(client, org, "x" * 40).status_code == 503


def test_the_install_link_points_at_the_app_and_carries_a_signed_value(client, bootstrap, gh):
    org = _org(client, bootstrap)
    r = client.get("/connections/github-app", headers=H(org)).json()
    assert r["available"] is True
    assert r["install_url"].startswith("https://github.com/apps/grc-evidence/installations/new?state=")
    assert org not in r["install_url"]          # the organisation id is inside the sealed value, not readable
    assert client.get("/connections", headers=H(org)).json()["github_app_available"] is True


# --- the happy path ---------------------------------------------------------------------------------------------------
def test_a_completed_install_stores_only_the_installation_number(client, bootstrap, gh, app_env, pem):
    org = _org(client, bootstrap)
    r = _complete(client, org, _state(client, org))
    assert r.status_code == 200, r.text
    mine = [c for c in r.json()["connections"] if c["kind"] == "GITHUB_CHANGE_CONTROL"][0]
    assert mine["configured"] and mine["hint"] == "GitHub App, 2 repositories"
    for secret in (TOKEN, "gho_usertoken", "clientsecretvalue", "BEGIN PRIVATE KEY"):
        assert secret not in r.text
    with Session(db_module.engine) as s:
        row = s.query(Connection).filter_by(org_id=org, kind="GITHUB_CHANGE_CONTROL").one()
        plain = json.loads(connections.decrypt(row.config_encrypted))
    assert plain["installation_id"] == INSTALL and "token" not in plain and TOKEN not in json.dumps(plain)


def test_a_saved_app_connection_mints_a_fresh_token_and_reads_the_current_repositories(gh, app_env):
    plain = connections.pack_github_app(INSTALL, ["old/one"])
    gh.repos = ["acme/api", "acme/new"]
    assert connections.github_credentials(plain) == (TOKEN, ["acme/api", "acme/new"])


def test_a_pasted_token_connection_still_works_unchanged():
    plain = connections.pack_github("ghp_AbCdEfGh1234secretTOKENvalue", ["a/b"])
    assert connections.github_credentials(plain) == ("ghp_AbCdEfGh1234secretTOKENvalue", ["a/b"])


# --- the checks that keep it safe -------------------------------------------------------------------------------------
def test_a_value_started_by_another_organisation_is_refused(client, bootstrap, gh):
    a, b = _org(client, bootstrap), bootstrap(client)[0]
    r = _complete(client, b, _state(client, a))
    assert r.status_code == 403 and "different organisation" in r.text
    with Session(db_module.engine) as s:
        assert s.query(Connection).filter_by(org_id=b, kind="GITHUB_CHANGE_CONTROL").count() == 0


def test_a_forged_or_expired_value_is_refused(client, bootstrap, gh, monkeypatch):
    org = _org(client, bootstrap)
    assert _complete(client, org, "x" * 40).status_code == 400
    state = _state(client, org)
    monkeypatch.setattr(connections, "STATE_TTL_S", -1)   # anything is older than "negative seconds"
    assert _complete(client, org, state).status_code == 400


def test_an_installation_that_is_not_the_persons_own_is_refused_and_nothing_is_saved(client, bootstrap, gh):
    org = _org(client, bootstrap)
    gh.owned = [9999]                                       # the person owns a different installation
    r = _complete(client, org, _state(client, org))
    assert r.status_code == 403
    with Session(db_module.engine) as s:
        assert s.query(Connection).filter_by(org_id=org, kind="GITHUB_CHANGE_CONTROL").count() == 0


def test_a_bad_one_time_code_is_refused(client, bootstrap, gh):
    org = _org(client, bootstrap)
    gh.code_ok = False
    assert _complete(client, org, _state(client, org)).status_code == 403


def test_an_install_with_no_repositories_is_refused(client, bootstrap, gh):
    org = _org(client, bootstrap)
    gh.repos = []
    assert _complete(client, org, _state(client, org)).status_code == 422


def test_the_proof_of_identity_is_a_short_rs256_token_naming_the_app(app_env, pem):
    token = connections._app_jwt(now=1_000_000)
    claims = jwt.decode(token, pem[1], algorithms=["RS256"], options={"verify_exp": False})
    assert claims["iss"] == "123456" and claims["exp"] - claims["iat"] <= 600
    assert jwt.get_unverified_header(token)["alg"] == "RS256"


def test_the_private_key_may_be_stored_on_one_line(monkeypatch, app_env, pem):
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", pem[0].replace("\n", "\\n"))
    assert jwt.decode(connections._app_jwt(now=int(time.time())), pem[1], algorithms=["RS256"])["iss"] == "123456"


# --- a private key as a settings box really leaves it (the first live install failed on exactly this) ----------------
def _pkcs1(pem):
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    key = load_pem_private_key(pem[0].encode(), password=None)
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                             serialization.NoEncryption()).decode()   # "BEGIN RSA PRIVATE KEY", what GitHub gives out


@pytest.mark.parametrize("mangle", [
    lambda p: p,                                              # as downloaded
    lambda p: p.replace("\n", " ").strip(),                   # line breaks became spaces
    lambda p: p.replace("\n", "\n"),                         # one line, literal backslash-n
    lambda p: '"' + p.replace("\n", "\n") + '"',             # wrapped in quotes
    lambda p: p.replace("\n", "\r\n"),                        # Windows line endings
    lambda p: "\n\n" + p + "\n\n",                            # stray blank lines
])
def test_a_mangled_private_key_is_still_read(monkeypatch, app_env, pem, mangle):
    for source in (pem[0], _pkcs1(pem)):
        monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", mangle(source))
        token = connections._app_jwt(now=int(time.time()))
        assert jwt.decode(token, pem[1], algorithms=["RS256"])["iss"] == "123456"


def test_an_unreadable_private_key_is_a_clear_refusal_not_a_crash_and_never_echoed(client, bootstrap, gh, monkeypatch):
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "-----BEGIN PRIVATE KEY-----\nnot a real key at all\n-----END PRIVATE KEY-----")
    with pytest.raises(ValueError) as e:
        connections.installation_token(INSTALL)
    assert "not a real key" not in str(e.value)
    org = _org(client, bootstrap)
    r = _complete(client, org, _state(client, org))
    assert r.status_code == 502 and "not a real key" not in r.text
