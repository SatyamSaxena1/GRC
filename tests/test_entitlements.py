"""The commercial layer (ADR-054): plans, limits and the read-only ended trial.

The rule worth proving is that a limit lives on the server: every door that adds a seat or a framework is checked,
an ended trial closes writes but never reads or data, and one organisation's use never counts against another's.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import db as db_module
from app.models import Organization


def _admin(client, org_id, email="admin@acme.test"):
    uid = client.post("/admin/users", json={"email": email, "org_id": org_id, "role": "ORG_ADMIN"}).json()["id"]
    return {"authorization": f"user:{uid}"}


def _plan(client, org_id, **body):
    return client.put(f"/admin/organizations/{org_id}/plan", json=body)


def test_legacy_org_with_no_plan_has_no_limits(client, bootstrap):
    org_id, _ = bootstrap(client)
    h = _admin(client, org_id)
    for i in range(8):
        assert client.post("/admin/users", headers=h, json={"email": f"p{i}@acme.test", "role": "CONTROL_OWNER"}).status_code == 200
    usage = client.get("/admin/usage", headers=h).json()
    assert usage["plan"] is None and usage["seats"]["limit"] is None and usage["trial_over"] is False


def test_seat_limit_blocks_every_way_to_add_a_seat(client, bootstrap):
    org_id, _ = bootstrap(client)
    h = _admin(client, org_id)  # seat 1
    assert _plan(client, org_id, plan="GROWTH", seats_limit=2).status_code == 200
    mate = client.post("/admin/users", headers=h, json={"email": "a@acme.test", "role": "CONTROL_OWNER"})
    assert mate.status_code == 200  # seat 2

    # signed-in invite, operator-key invite: both refused
    assert client.post("/admin/users", headers=h, json={"email": "b@acme.test", "role": "CONTROL_OWNER"}).status_code == 402
    assert client.post("/admin/users", json={"email": "c@acme.test", "org_id": org_id, "role": "CONTROL_OWNER"}).status_code == 402

    # deactivate then reactivate cannot be used to get past the limit either
    assert client.patch(f"/admin/users/{mate.json()['id']}", headers=h, json={"active": False}).status_code == 200
    assert client.post("/admin/users", headers=h, json={"email": "d@acme.test", "role": "CONTROL_OWNER"}).status_code == 200
    assert client.patch(f"/admin/users/{mate.json()['id']}", headers=h, json={"active": True}).status_code == 402
    assert client.get("/admin/usage", headers=h).json()["seats"] == {"used": 2, "limit": 2}


def test_another_orgs_people_do_not_use_up_my_seats(client, bootstrap, monkeypatch):
    a, _ = bootstrap(client)
    b = client.post("/admin/organizations", json={"name": "Other", "frameworks": ["ISO-27001"]}).json()["id"]
    ha = _admin(client, a)
    for i in range(4):
        client.post("/admin/users", json={"email": f"b{i}@other.test", "org_id": b, "role": "CONTROL_OWNER"})
    _plan(client, a, plan="GROWTH", seats_limit=2)
    assert client.post("/admin/users", headers=ha, json={"email": "x@acme.test", "role": "CONTROL_OWNER"}).status_code == 200
    monkeypatch.setenv("ADMIN_API_KEY", "secret")
    # and an org admin cannot lift their own limit, or read the operator list
    assert client.put(f"/admin/organizations/{a}/plan", headers=ha, json={"plan": "SCALE"}).status_code in (401, 403)


def test_framework_limit_and_unknown_framework(client, bootstrap):
    org_id, _ = bootstrap(client, frameworks=("ISO-27001",))
    h = _admin(client, org_id)
    _plan(client, org_id, plan="DPDP_STARTER")  # one framework, and the org already has one
    assert client.post("/admin/frameworks", headers=h, json={"framework": "PCI-DSS"}).status_code == 402
    assert client.post("/admin/frameworks", headers=h, json={"framework": "NOPE"}).status_code == 422
    assert client.post("/admin/frameworks", headers=h, json={"framework": "ISO-27001"}).status_code == 200  # already held
    _plan(client, org_id, plan="GROWTH")
    assert client.post("/admin/frameworks", headers=h, json={"framework": "PCI-DSS"}).status_code == 200
    assert client.get("/admin/usage", headers=h).json()["frameworks"]["used"] == 2


def test_only_the_operator_can_set_a_plan(client, bootstrap, monkeypatch):
    org_id, _ = bootstrap(client)
    assert _plan(client, org_id, plan="NOPE").status_code == 422
    assert _plan(client, "missing", plan="TRIAL").status_code == 404
    monkeypatch.setenv("ADMIN_API_KEY", "secret")
    assert _plan(client, org_id, plan="SCALE").status_code == 401
    ok = client.put(f"/admin/organizations/{org_id}/plan", headers={"x-admin-key": "secret"}, json={"plan": "SCALE"})
    assert ok.status_code == 200 and ok.json()["seats"]["limit"] == 50
    assert client.get("/admin/organizations").status_code == 401


def test_ended_trial_is_read_only_and_loses_nothing(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    h = _admin(client, org_id)
    assert upload(client, org_id, content=b"first policy").status_code in (200, 201, 202)
    _plan(client, org_id, plan="TRIAL")
    assert upload(client, org_id, content=b"second policy").status_code in (200, 201, 202)  # inside the trial

    from sqlalchemy.orm import Session
    with Session(db_module.engine) as s:  # the trial runs out
        s.get(Organization, org_id).trial_ends_at = datetime.now(timezone.utc) - timedelta(days=1)
        s.commit()

    refused = upload(client, org_id, content=b"third policy")
    assert refused.status_code == 402 and "read-only" in refused.json()["detail"]
    assert client.post("/admin/users", headers=h, json={"email": "n@acme.test", "role": "CONTROL_OWNER"}).status_code == 402
    listed = client.get("/evidence", headers={"authorization": f"org:{org_id}"})
    assert listed.status_code == 200 and len(listed.json()) == 2  # reads work, nothing was deleted
    usage = client.get("/admin/usage", headers=h).json()
    assert usage["trial_over"] is True and usage["evidence_count"] == 2

    assert _plan(client, org_id, plan="GROWTH").status_code == 200  # the operator re-opens it
    assert upload(client, org_id, content=b"fifth policy").status_code in (200, 201, 202)


def test_ended_trial_of_one_org_does_not_touch_another(client, bootstrap, upload):
    a, _ = bootstrap(client)
    b = client.post("/admin/organizations", json={"name": "Other", "frameworks": ["ISO-27001"]}).json()["id"]
    _plan(client, a, plan="TRIAL", trial_days=1)
    from sqlalchemy.orm import Session
    with Session(db_module.engine) as s:
        s.get(Organization, a).trial_ends_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        s.commit()
    assert upload(client, a).status_code == 402
    assert upload(client, b).status_code in (200, 201, 202)


def test_onboarding_approval_starts_a_trial(client):
    firm = client.post("/admin/audit-firms", json={"name": "Gemba"}).json()["id"]
    admin = client.post("/admin/users", json={"email": "a@gemba.test", "audit_firm_id": firm, "role": "FIRM_ADMIN"}).json()["id"]
    req = client.post("/firm/onboarding-requests", json={"audit_firm_id": firm, "org_name": "New Co",
                      "contact_email": "ciso@new.test", "frameworks": ["ISO-27001"]}).json()["id"]
    org_id = client.post(f"/firm/onboarding-requests/{req}/approve", headers={"authorization": f"user:{admin}"},
                         json={}).json()["org_id"]
    org = next(o for o in client.get("/admin/organizations").json() if o["id"] == org_id)
    assert org["plan"] == "TRIAL" and org["trial_ends_at"] and not org["trial_over"]
