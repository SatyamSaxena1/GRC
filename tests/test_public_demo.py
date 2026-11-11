"""The public demo (ADR-062): anyone may look at the DEMO_ORG_ID organisation without an account, as a read-only viewer,
and never at any other; it exists only when configured. And the FREE plan: one framework, three people, no end date."""

from __future__ import annotations

from app import entitlements
from app.models import Organization

DEMO = {"authorization": "demo"}


def _org(client, name, frameworks=("ISO-27001",)):
    return client.post("/admin/organizations", json={"name": name, "frameworks": list(frameworks)}).json()["id"]


def test_without_a_configured_demo_there_is_none(client, monkeypatch):
    monkeypatch.delenv("DEMO_ORG_ID", raising=False)
    assert client.get("/public/demo").json() == {"available": False}
    assert client.get("/controls", headers=DEMO).status_code == 404


def test_the_demo_reads_its_own_organisation_only_and_cannot_write(client, monkeypatch):
    demo = _org(client, "Sample Co")
    other = _org(client, "Real Customer")
    client.post("/vendors", json={"name": "Other's vendor", "data_access": "NONE", "criticality": "LOW"},
                headers={"authorization": f"org:{other}"})
    monkeypatch.setenv("DEMO_ORG_ID", demo)
    assert client.get("/public/demo").json() == {"available": True}

    assert client.get("/analytics/readiness/ISO-27001", headers=DEMO).status_code == 200
    assert "Other's vendor" not in client.get("/vendors", headers=DEMO).text

    for method, path, body in [
        ("post", "/vendors", {"name": "x", "data_access": "NONE", "criticality": "LOW"}),
        ("post", "/policies", {"title": "x", "body": "y" * 40}),
        ("post", "/assistant/ask", {"question": "hello"}),
        ("post", "/admin/users", {"email": "a@b.test", "org_id": demo, "role": "ORG_ADMIN"}),
    ]:
        r = getattr(client, method)(path, json=body, headers=DEMO)
        assert r.status_code == 403, (path, r.status_code, r.text)
        assert "read-only demo" in r.text


def test_the_free_plan_allows_one_framework_and_three_people_and_never_ends():
    assert entitlements.PLANS["FREE"] == (1, 3)
    org = Organization(name="x", plan="FREE", trial_ends_at=None)
    assert not entitlements.trial_over(org)
