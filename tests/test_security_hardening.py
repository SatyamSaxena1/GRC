"""Standard browser security headers on every response, and a limit on wrong operator keys (ADR-065)."""

from __future__ import annotations

import pytest

from app import auth


@pytest.fixture(autouse=True)
def _clean():
    auth._admin_fails.clear()
    yield
    auth._admin_fails.clear()


def test_every_response_carries_the_standard_headers(client):
    r = client.get("/health/live")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in r.headers["permissions-policy"]
    assert "strict-transport-security" not in r.headers            # plain http: not told to insist on https
    https = client.get("/health/live", headers={"x-forwarded-proto": "https"})
    assert "max-age=31536000" in https.headers["strict-transport-security"]
    assert client.get("/nope-not-a-route").headers["x-content-type-options"] == "nosniff"   # errors too


def test_wrong_operator_keys_are_stopped_after_ten_and_a_right_one_resets(client, monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "right-key")
    who = {"cf-connecting-ip": "203.0.113.9"}
    for _ in range(auth.ADMIN_KEY_MAX_FAILS):
        assert client.get("/admin/organizations", headers={**who, "x-admin-key": "wrong"}).status_code == 401
    blocked = client.get("/admin/organizations", headers={**who, "x-admin-key": "right-key"})
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == str(auth.ADMIN_KEY_WINDOW_S)
    other = {"cf-connecting-ip": "198.51.100.4"}                    # someone else is unaffected
    assert client.get("/admin/organizations", headers={**other, "x-admin-key": "right-key"}).status_code == 200


def test_a_right_key_clears_earlier_misses(client, monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "right-key")
    who = {"cf-connecting-ip": "203.0.113.20"}
    for _ in range(auth.ADMIN_KEY_MAX_FAILS - 1):
        client.get("/admin/organizations", headers={**who, "x-admin-key": "wrong"})
    assert client.get("/admin/organizations", headers={**who, "x-admin-key": "right-key"}).status_code == 200
    for _ in range(auth.ADMIN_KEY_MAX_FAILS - 1):                  # the count started again from zero
        assert client.get("/admin/organizations", headers={**who, "x-admin-key": "wrong"}).status_code == 401


def test_a_forged_forwarded_for_does_not_dodge_the_limit(client, monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "right-key")
    for i in range(auth.ADMIN_KEY_MAX_FAILS):
        client.get("/admin/organizations", headers={"x-forwarded-for": f"10.0.0.{i}", "x-admin-key": "wrong"})
    r = client.get("/admin/organizations", headers={"x-forwarded-for": "10.9.9.9", "x-admin-key": "wrong"})
    assert r.status_code == 429
