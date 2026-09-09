"""GET /analytics/dashboard — one round trip replacing what used to be 7 calls
plus one GET /controls/{id} per control (see Overview.tsx and the blueprint
doc's "avoid making the browser fan out" guidance)."""

from __future__ import annotations

from app.content.load import load as load_content


def test_dashboard_reflects_uploaded_evidence_and_open_work(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    upload(client, org_id)  # policy.txt, extraction unavailable in tests -> gaps open

    body = client.get("/analytics/dashboard", headers={"authorization": f"org:{org_id}"}).json()

    assert body["controls"]["total"] > 0
    assert sum(body["controls"]["by_verdict"].values()) == body["controls"]["total"]
    assert body["evidence"]["total"] == 1
    assert body["gaps_open"] >= 1  # extraction unavailable -> missing-attribute gaps
    assert body["tasks_open"] >= 1  # one task per new gap
    assert "reuse_rate" in body["reuse"]
    # Every known framework, subscribed or not — derived from the content packs
    # rather than hard-coded, so adding a pack doesn't fail an assertion that was
    # only ever about "all of them".
    assert len(body["readiness"]) == len(load_content().packs)
    assert "total" in body["attention"]


def test_dashboard_is_org_isolated(client, bootstrap, upload):
    org_a, _ = bootstrap(client)
    org_b, _ = bootstrap(client)
    upload(client, org_a, content=b"org a's policy")

    a = client.get("/analytics/dashboard", headers={"authorization": f"org:{org_a}"}).json()
    b = client.get("/analytics/dashboard", headers={"authorization": f"org:{org_b}"}).json()

    assert a["evidence"]["total"] == 1
    assert b["evidence"]["total"] == 0
    assert b["controls"]["total"] == 0


def test_dashboard_requires_an_identity(client):
    resp = client.get("/analytics/dashboard")
    assert resp.status_code == 422  # missing Authorization header, same as every other route
