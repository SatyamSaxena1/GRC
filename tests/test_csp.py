"""Content-Security-Policy (ADR-066): report-only by default, switchable, built from what the app loads, and a report
endpoint that keeps only a short clipped summary."""

from __future__ import annotations

import json
import logging

import pytest

from app import csp

TOKEN_URL = "https://dev-abc123.us.auth0.com/oauth/token"


@pytest.fixture(autouse=True)
def _fresh_window():
    csp._window.update(start=0.0, count=0)
    yield


def test_the_policy_allows_only_what_the_app_loads():
    p = csp.policy({"VITE_OIDC_TOKEN_URL": TOKEN_URL})
    assert "default-src 'self'" in p and "script-src 'self'" in p and "object-src 'none'" in p
    assert "connect-src 'self' https://dev-abc123.us.auth0.com" in p              # the sign-in token address, origin only
    assert "oauth/token" not in p and "unsafe-eval" not in p
    assert "script-src 'self' 'unsafe-inline'" not in p                           # scripts stay strict
    assert "connect-src 'self'; " in csp.policy({})                               # no sign-in provider configured
    assert csp.origin_of("javascript:alert(1)") == "" and csp.origin_of("") == ""


def test_the_mode_decides_which_header_is_sent():
    assert csp.header({})[0] == "Content-Security-Policy-Report-Only"             # the default: nothing can break
    assert csp.header({"CSP_MODE": "enforce"})[0] == "Content-Security-Policy"
    assert csp.header({"CSP_MODE": " Enforce "})[0] == "Content-Security-Policy"
    assert csp.header({"CSP_MODE": "off"}) is None


def test_every_response_carries_the_report_only_policy(client, monkeypatch):
    monkeypatch.delenv("CSP_MODE", raising=False)
    r = client.get("/health/live")
    assert "report-uri /csp-report" in r.headers["content-security-policy-report-only"]
    assert "content-security-policy" not in r.headers
    monkeypatch.setenv("CSP_MODE", "off")
    assert "content-security-policy-report-only" not in client.get("/health/live").headers


def test_both_report_formats_are_read_and_clipped(client, caplog):
    old = {"csp-report": {"violated-directive": "img-src", "blocked-uri": "https://evil.example/" + "a" * 400,
                          "document-uri": "https://grc.blinkedit.me/overview?token=SECRET"}}
    new = [{"type": "csp-violation", "body": {"effectiveDirective": "script-src-elem", "blockedURL": "inline",
                                              "documentURL": "https://grc.blinkedit.me/login"}}]
    with caplog.at_level(logging.WARNING, logger="app.csp"):
        assert client.post("/csp-report", content=json.dumps(old), headers={"content-type": "application/csp-report"}).status_code == 204
        assert client.post("/csp-report", content=json.dumps(new), headers={"content-type": "application/reports+json"}).status_code == 204
    lines = [r.getMessage() for r in caplog.records]
    assert any("directive=img-src" in l and "page=/overview" in l for l in lines)
    assert any("directive=script-src-elem" in l and "page=/login" in l for l in lines)
    assert not any("SECRET" in l for l in lines)                                   # the query string is never kept
    assert all(len(l) < 400 for l in lines)


def test_junk_and_oversized_reports_are_harmless_and_logging_is_bounded(client, caplog):
    with caplog.at_level(logging.WARNING, logger="app.csp"):
        assert client.post("/csp-report", content=b"not json").status_code == 204
        assert client.post("/csp-report", content=b"[1, 2, {\"x\": 1}]").status_code == 204
        assert client.post("/csp-report", content=b"{" + b"a" * 100_000).status_code == 204
        forged = {"csp-report": {"violated-directive": "x\nFORGED LOG LINE", "blocked-uri": "y\r\nmore"}}
        for _ in range(csp.MAX_LOGGED_PER_MINUTE + 20):
            client.post("/csp-report", content=json.dumps(forged))
    lines = [r.getMessage() for r in caplog.records]
    assert len(lines) == csp.MAX_LOGGED_PER_MINUTE
    assert all("\n" not in l and "\r" not in l for l in lines)                     # no forged log lines
