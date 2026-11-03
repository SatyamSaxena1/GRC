"""The trust page (ADR-039): opt-in, content-free, revocable, and isolated per organisation."""

from __future__ import annotations

import json

H = lambda org: {"authorization": f"org:{org}"}  # noqa: E731


def test_nothing_is_public_until_the_admin_publishes(client, bootstrap):
    org, _ = bootstrap(client)
    assert client.get("/trust-settings", headers=H(org)).json()["published"] is False
    assert client.get("/public/trust/" + "x" * 24).status_code == 404


def test_publishing_gives_an_unguessable_link_that_needs_no_sign_in(client, bootstrap, upload):
    org, _ = bootstrap(client)
    upload(client, org, name="secret-board-policy.txt")
    token = client.post("/trust-settings/publish", headers=H(org)).json()["token"]
    assert len(token) >= 20

    page = client.get(f"/public/trust/{token}")  # no authorization header at all
    assert page.status_code == 200
    assert page.headers["x-robots-tag"] == "noindex, nofollow" and page.headers["cache-control"] == "no-store"
    body = page.json()
    assert body["organisation"] == "Acme"
    assert {"total", "meeting_requirements", "awaiting_evidence"} <= set(body["controls"])
    assert [f["framework"] for f in body["frameworks"]] == ["ISO-27001", "PCI-DSS"]


def test_the_page_is_content_free(client, bootstrap, upload):
    org, _ = bootstrap(client)
    upload(client, org, name="secret-board-policy.txt", content=b"confidential merger plan")
    token = client.post("/trust-settings/publish", headers=H(org)).json()["token"]
    text = json.dumps(client.get(f"/public/trust/{token}").json()).lower()
    for leaked in ("secret-board-policy", "confidential", "merger", "gap", "task", "filename", token.lower()):
        assert leaked not in text, leaked


def test_unpublishing_takes_the_page_down_and_republishing_issues_a_new_link(client, bootstrap):
    org, _ = bootstrap(client)
    first = client.post("/trust-settings/publish", headers=H(org)).json()["token"]
    assert client.post("/trust-settings/publish", headers=H(org)).json()["token"] == first  # idempotent

    client.post("/trust-settings/unpublish", headers=H(org))
    assert client.get(f"/public/trust/{first}").status_code == 404
    second = client.post("/trust-settings/publish", headers=H(org)).json()["token"]
    assert second != first and client.get(f"/public/trust/{first}").status_code == 404


def test_only_an_org_admin_may_publish(client, bootstrap):
    org, _ = bootstrap(client)
    owner = {"authorization": "user:" + client.post("/admin/users", json={
        "email": "o@x.test", "org_id": org, "role": "CONTROL_OWNER"}).json()["id"]}
    assert client.post("/trust-settings/publish", headers=owner).status_code == 403
    assert client.get("/trust-settings", headers=owner).status_code == 403


def test_one_organisations_link_shows_only_its_own_figures(client, bootstrap):
    a, _ = bootstrap(client)
    b = client.post("/admin/organizations", json={"name": "Other Ltd", "frameworks": ["SOC-2"]}).json()["id"]
    ta = client.post("/trust-settings/publish", headers=H(a)).json()["token"]
    tb = client.post("/trust-settings/publish", headers=H(b)).json()["token"]
    assert client.get(f"/public/trust/{ta}").json()["organisation"] == "Acme"
    other = client.get(f"/public/trust/{tb}").json()
    assert other["organisation"] == "Other Ltd" and [f["framework"] for f in other["frameworks"]] == ["SOC-2"]


def test_publishing_and_unpublishing_are_audited_without_the_link(client, bootstrap, db):
    from app.models import AuditEvent

    org, _ = bootstrap(client)
    token = client.post("/trust-settings/publish", headers=H(org)).json()["token"]
    client.post("/trust-settings/unpublish", headers=H(org))
    events = db.query(AuditEvent).filter(AuditEvent.action.like("TRUST_PAGE_%")).order_by(AuditEvent.at).all()
    assert [e.action for e in events] == ["TRUST_PAGE_PUBLISHED", "TRUST_PAGE_UNPUBLISHED"]
    assert token not in json.dumps([e.detail for e in events], default=str)
