"""GET /activity — org-wide chronological AuditEvent view, same shape and
authorization as the existing per-entity history endpoints, just not scoped
to one control/evidence item."""

from __future__ import annotations


def test_activity_reflects_org_actions(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    upload(client, org_id)

    events = client.get("/activity", headers={"authorization": f"org:{org_id}"}).json()
    assert any(e["action"] == "EVIDENCE_PROCESSED" for e in events)
    # newest first
    ats = [e["at"] for e in events]
    assert ats == sorted(ats, reverse=True)


def test_activity_is_org_isolated(client, bootstrap, upload):
    org_a, _ = bootstrap(client)
    org_b, _ = bootstrap(client)  # bootstrap itself logs an ENGAGEMENT_OPENED event for org_b
    upload(client, org_a)

    a_events = client.get("/activity", headers={"authorization": f"org:{org_a}"}).json()
    b_events = client.get("/activity", headers={"authorization": f"org:{org_b}"}).json()
    assert any(e["action"] == "EVIDENCE_PROCESSED" for e in a_events)
    assert not any(e["action"] == "EVIDENCE_PROCESSED" for e in b_events)


def test_firm_actor_with_no_engagement_selected_gets_empty_not_an_error(client):
    firm = client.post("/admin/audit-firms", json={"name": "Gemba"}).json()
    admin = client.post("/admin/users", json={
        "email": "admin@gemba.test", "audit_firm_id": firm["id"], "role": "FIRM_ADMIN",
    }).json()
    resp = client.get("/activity", headers={"authorization": f"user:{admin['id']}"})
    assert resp.status_code == 200
    assert resp.json() == []
