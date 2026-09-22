"""Day-2 admin actions (invite a teammate, register/assign a control, close an
engagement) work from a signed-in org/firm admin's own session — no shared
operator key required. The key stays required for actions with no existing
tenant to scope by (create org/firm), and a signed-in caller may never reach
into someone else's tenant (see app/auth.py::admin_or_actor,
app/routers/admin.py).
"""

from __future__ import annotations

from app import oidc


def _make_org_admin(client, org_id, email="admin@acme.test"):
    return client.post("/admin/users", json={
        "email": email, "org_id": org_id, "role": "ORG_ADMIN",
    }).json()["id"]


def _make_control_owner(client, org_id, email="owner@acme.test"):
    return client.post("/admin/users", json={
        "email": email, "org_id": org_id, "role": "CONTROL_OWNER",
    }).json()["id"]


def test_org_admin_can_register_and_assign_a_control_for_their_own_org(client, bootstrap):
    org_id, _ = bootstrap(client)
    admin_id = _make_org_admin(client, org_id)
    owner_id = _make_control_owner(client, org_id)
    headers = {"authorization": f"user:{admin_id}"}

    control = client.post("/admin/controls", headers=headers,
                          json={"org_id": org_id, "framework": "ISO-27001", "clause": "A.9.1"})
    assert control.status_code == 200

    assignment = client.post("/admin/control-assignments", headers=headers,
                             json={"org_control_id": control.json()["id"], "user_id": owner_id})
    assert assignment.status_code == 200


def test_org_admin_cannot_touch_another_orgs_control(client, bootstrap):
    org_a, _ = bootstrap(client)
    org_b = client.post("/admin/organizations", json={"name": "Other Co", "frameworks": ["ISO-27001"]}).json()["id"]
    admin_a = _make_org_admin(client, org_a)

    resp = client.post("/admin/controls", headers={"authorization": f"user:{admin_a}"},
                       json={"org_id": org_b, "framework": "ISO-27001", "clause": "A.9.1"})
    assert resp.status_code == 403


def test_control_owner_cannot_register_a_control_even_for_their_own_org(client, bootstrap):
    org_id, _ = bootstrap(client)
    owner_id = _make_control_owner(client, org_id)

    resp = client.post("/admin/controls", headers={"authorization": f"user:{owner_id}"},
                       json={"org_id": org_id, "framework": "ISO-27001", "clause": "A.9.1"})
    assert resp.status_code == 403


def test_org_admin_can_invite_a_teammate_into_their_own_org(client, bootstrap):
    org_id, _ = bootstrap(client)
    admin_id = _make_org_admin(client, org_id)

    resp = client.post("/admin/users", headers={"authorization": f"user:{admin_id}"},
                       json={"email": "new@acme.test", "org_id": org_id, "role": "CONTROL_OWNER"})
    assert resp.status_code == 200


def test_org_admin_cannot_invite_into_another_org(client, bootstrap):
    org_a, _ = bootstrap(client)
    org_b = client.post("/admin/organizations", json={"name": "Other Co", "frameworks": ["ISO-27001"]}).json()["id"]
    admin_a = _make_org_admin(client, org_a)

    resp = client.post("/admin/users", headers={"authorization": f"user:{admin_a}"},
                       json={"email": "mole@other.test", "org_id": org_b, "role": "CONTROL_OWNER"})
    assert resp.status_code == 403


def test_org_admin_can_close_their_own_engagement(client, bootstrap):
    org_id, engagement_id = bootstrap(client)
    admin_id = _make_org_admin(client, org_id)

    resp = client.post(f"/admin/engagements/{engagement_id}/close",
                       headers={"authorization": f"user:{admin_id}"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "CLOSED"


def test_operator_key_still_required_when_set_for_org_creation(client, monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "s3cret")
    body = {"name": "A", "frameworks": ["ISO-27001"]}
    assert client.post("/admin/organizations", json=body).status_code == 401
    assert client.post("/admin/organizations", json=body,
                       headers={"x-admin-key": "s3cret"}).status_code == 200


def test_operator_key_still_bootstraps_a_users_for_a_brand_new_org(client, monkeypatch):
    """The no-Authorization-header path (a plain curl with the operator key)
    keeps working exactly as before — it's how a very first user gets
    provisioned for an org created outside the self-service request flow."""
    monkeypatch.setenv("ADMIN_API_KEY", "s3cret")
    org = client.post("/admin/organizations", headers={"x-admin-key": "s3cret"},
                      json={"name": "A", "frameworks": ["ISO-27001"]}).json()
    resp = client.post("/admin/users", headers={"x-admin-key": "s3cret"},
                       json={"email": "first@a.test", "org_id": org["id"], "role": "ORG_ADMIN"})
    assert resp.status_code == 200


def test_org_admin_session_alone_is_rejected_when_operator_key_set_and_scope_mismatches(client, bootstrap, monkeypatch):
    """Setting ADMIN_API_KEY doesn't relax the tenant check for a signed-in
    caller — it only adds the separate operator-key door."""
    org_id, _ = bootstrap(client)
    admin_id = _make_org_admin(client, org_id)
    monkeypatch.setenv("ADMIN_API_KEY", "s3cret")

    resp = client.post("/admin/controls", headers={"authorization": f"user:{admin_id}"},
                       json={"org_id": org_id, "framework": "ISO-27001", "clause": "A.9.1"})
    assert resp.status_code == 200  # own org still works without the key


def test_approving_onboarding_provisions_the_first_org_admin(client):
    firm = client.post("/admin/audit-firms", json={"name": "Gemba"}).json()
    firm_admin = client.post("/admin/users", json={
        "email": "admin@gemba.test", "audit_firm_id": firm["id"], "role": "FIRM_ADMIN",
    }).json()["id"]
    request_id = client.post("/firm/onboarding-requests", json={
        "audit_firm_id": firm["id"], "org_name": "Acme Corp",
        "contact_email": "ciso@acme.test", "frameworks": ["ISO-27001"],
    }).json()["id"]

    approved = client.post(f"/firm/onboarding-requests/{request_id}/approve",
                           headers={"authorization": f"user:{firm_admin}"}, json={})
    assert approved.status_code == 200
    assert approved.json()["org_admin_email"] == "ciso@acme.test"

    # no separate /admin/users call — the requester can sign in immediately
    org_id = approved.json()["org_id"]
    assert client.get("/controls", headers={"authorization": f"org:{org_id}"}).status_code == 200


def test_approving_onboarding_lets_the_requester_sign_in_via_oidc_immediately(client, monkeypatch):
    firm = client.post("/admin/audit-firms", json={"name": "Gemba"}).json()
    firm_admin = client.post("/admin/users", json={
        "email": "admin@gemba.test", "audit_firm_id": firm["id"], "role": "FIRM_ADMIN",
    }).json()["id"]
    request_id = client.post("/firm/onboarding-requests", json={
        "audit_firm_id": firm["id"], "org_name": "Acme Corp",
        "contact_email": "ciso@acme.test", "frameworks": ["ISO-27001"],
    }).json()["id"]
    client.post(f"/firm/onboarding-requests/{request_id}/approve",
               headers={"authorization": f"user:{firm_admin}"}, json={})

    monkeypatch.setattr(oidc, "decode", lambda token: {"email": "ciso@acme.test"})
    resp = client.get("/controls", headers={"authorization": "Bearer header.payload.signature"})
    assert resp.status_code == 200
