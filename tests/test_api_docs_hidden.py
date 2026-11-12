"""Production (stub auth off) must not serve the interactive API pages; development keeps them (ADR-067)."""

import os
import subprocess
import sys

OIDC = {"OIDC_ISSUER": "https://i.test/", "OIDC_AUDIENCE": "a", "OIDC_JWKS_URL": "https://i.test/jwks"}


def openapi_url(**env):
    r = subprocess.run([sys.executable, "-c", "from app.main import app; print(app.openapi_url, app.docs_url, app.redoc_url)"],
                       capture_output=True, text=True, env={**os.environ, "DATABASE_URL": "sqlite:///:memory:", **env})
    assert r.returncode == 0, r.stderr[-500:]
    return r.stdout.split()


def test_development_keeps_the_docs():
    assert openapi_url(AUTH_STUB_ENABLED="true") == ["/openapi.json", "/docs", "/redoc"]


def test_production_hides_them_and_a_flag_brings_them_back():
    assert openapi_url(AUTH_STUB_ENABLED="false", **OIDC) == ["None", "None", "None"]
    assert openapi_url(AUTH_STUB_ENABLED="false", API_DOCS="on", **OIDC) == ["/openapi.json", "/docs", "/redoc"]
