"""The audit-firm side: onboarding approval and auditor staffing.

The rule worth proving here is that staffing is the access grant. Belonging to
a firm gets a user into the firm console and no further — an unstaffed auditor
must not be able to see, or act under, a client it was not put on, and must not
be able to tell an unstaffed client apart from one that does not exist.
"""

from __future__ import annotations


def firm_with_admin(client, name="Gemba Assurance"):
    firm = client.post("/admin/audit-firms", json={"name": name}).json()
    admin = client.post("/admin/users", json={
        "email": "admin@gemba.test", "audit_firm_id": firm["id"], "role": "FIRM_ADMIN",
    }).json()
    return firm["id"], admin["id"]


def auditor(client, firm_id, email="krishna@gemba.test"):
    return client.post("/admin/users", json={
        "email": email, "audit_firm_id": firm_id, "role": "AUDITOR",
    }).json()["id"]


def request_onboarding(client, firm_id, org_name="Acme Corp",
                       frameworks=("ISO-27001", "PCI-DSS")):
    return client.post("/firm/onboarding-requests", json={
        "audit_firm_id": firm_id, "org_name": org_name,
        "contact_email": "ciso@acme.test", "frameworks": list(frameworks),
    }).json()["id"]


def as_user(user_id, engagement_id=None):
    headers = {"authorization": f"user:{user_id}"}
    if engagement_id:
        headers["x-engagement-id"] = engagement_id
    return headers


# --------------------------------------------------------------------------- onboarding


def test_approval_is_what_creates_the_tenant(client):
    firm_id, admin_id = firm_with_admin(client)
    request_id = request_onboarding(client, firm_id)

    pending = client.get("/firm/onboarding-requests", headers=as_user(admin_id),
                         params={"status": "PENDING"}).json()["requests"]
    assert [r["id"] for r in pending] == [request_id]
    assert pending[0]["org_id"] is None  # nothing tenant-owned exists yet

    approved = client.post(f"/firm/onboarding-requests/{request_id}/approve",
                           headers=as_user(admin_id), json={"note": "contract signed"})
    assert approved.status_code == 200
    body = approved.json()
    assert body["status"] == "APPROVED"
    assert body["org_id"] and body["engagement_id"]

    # the org that approval created is real and usable
    assert client.get("/controls", headers={"authorization": f"org:{body['org_id']}"}).status_code == 200


def test_firm_may_narrow_the_requested_frameworks(client):
    firm_id, admin_id = firm_with_admin(client)
    request_id = request_onboarding(client, firm_id, frameworks=("ISO-27001", "PCI-DSS", "SOC-2"))

    body = client.post(f"/firm/onboarding-requests/{request_id}/approve",
                       headers=as_user(admin_id),
                       json={"frameworks": ["ISO-27001"], "note": "scope reduced"}).json()
    assert body["frameworks"] == ["ISO-27001"]

    engagements = client.get("/firm/engagements", headers=as_user(admin_id)).json()["engagements"]
    assert engagements[0]["frameworks"] == ["ISO-27001"]


def test_rejection_creates_no_org_and_cannot_be_redecided(client):
    firm_id, admin_id = firm_with_admin(client)
    request_id = request_onboarding(client, firm_id)

    rejected = client.post(f"/firm/onboarding-requests/{request_id}/reject",
                           headers=as_user(admin_id), json={"note": "out of scope"})
    assert rejected.status_code == 200

    listed = client.get("/firm/onboarding-requests", headers=as_user(admin_id)).json()["requests"]
    assert listed[0]["status"] == "REJECTED" and listed[0]["org_id"] is None

    again = client.post(f"/firm/onboarding-requests/{request_id}/approve",
                        headers=as_user(admin_id), json={})
    assert again.status_code == 409


def test_a_plain_auditor_cannot_decide_onboarding(client):
    firm_id, _ = firm_with_admin(client)
    auditor_id = auditor(client, firm_id)
    request_id = request_onboarding(client, firm_id)

    denied = client.post(f"/firm/onboarding-requests/{request_id}/approve",
                         headers=as_user(auditor_id), json={})
    assert denied.status_code == 403


def test_one_firm_cannot_see_or_decide_another_firms_requests(client):
    firm_a, admin_a = firm_with_admin(client, "Gemba")
    firm_b, admin_b = firm_with_admin(client, "Meridian")
    request_id = request_onboarding(client, firm_a)

    assert client.get("/firm/onboarding-requests", headers=as_user(admin_b)).json()["requests"] == []
    assert client.post(f"/firm/onboarding-requests/{request_id}/approve",
                       headers=as_user(admin_b), json={}).status_code == 404


# --------------------------------------------------------------------------- staffing


def test_staffing_is_the_access_grant_not_firm_membership(client):
    firm_id, admin_id = firm_with_admin(client)
    auditor_id = auditor(client, firm_id)
    request_id = request_onboarding(client, firm_id)
    approved = client.post(f"/firm/onboarding-requests/{request_id}/approve",
                           headers=as_user(admin_id), json={}).json()
    engagement_id = approved["engagement_id"]

    # in the firm, on no client: the dashboard is empty and the engagement is
    # indistinguishable from one that does not exist
    assert client.get("/firm/engagements", headers=as_user(auditor_id)).json()["engagements"] == []
    assert client.get("/controls", headers=as_user(auditor_id, engagement_id)).status_code == 404

    staffed = client.post(f"/firm/engagements/{engagement_id}/auditors",
                          headers=as_user(admin_id), json={"user_id": auditor_id})
    assert staffed.status_code == 201

    visible = client.get("/firm/engagements", headers=as_user(auditor_id)).json()["engagements"]
    assert [e["id"] for e in visible] == [engagement_id]
    assert client.get("/controls", headers=as_user(auditor_id, engagement_id)).status_code == 200


def test_unstaffing_revokes_access_immediately(client):
    firm_id, admin_id = firm_with_admin(client)
    auditor_id = auditor(client, firm_id)
    request_id = request_onboarding(client, firm_id)
    engagement_id = client.post(f"/firm/onboarding-requests/{request_id}/approve",
                                headers=as_user(admin_id), json={}).json()["engagement_id"]
    client.post(f"/firm/engagements/{engagement_id}/auditors",
                headers=as_user(admin_id), json={"user_id": auditor_id})
    assert client.get("/controls", headers=as_user(auditor_id, engagement_id)).status_code == 200

    removed = client.delete(f"/firm/engagements/{engagement_id}/auditors/{auditor_id}",
                            headers=as_user(admin_id))
    assert removed.status_code == 204
    assert client.get("/controls", headers=as_user(auditor_id, engagement_id)).status_code == 404
    assert client.get("/firm/engagements", headers=as_user(auditor_id)).json()["engagements"] == []


def test_an_auditor_sees_only_the_clients_it_is_on(client):
    firm_id, admin_id = firm_with_admin(client)
    auditor_id = auditor(client, firm_id)

    engagements = {}
    for org_name in ("Client A", "Client B"):
        request_id = request_onboarding(client, firm_id, org_name=org_name)
        engagements[org_name] = client.post(
            f"/firm/onboarding-requests/{request_id}/approve",
            headers=as_user(admin_id), json={}).json()["engagement_id"]

    client.post(f"/firm/engagements/{engagements['Client A']}/auditors",
                headers=as_user(admin_id), json={"user_id": auditor_id})

    seen = client.get("/firm/engagements", headers=as_user(auditor_id)).json()["engagements"]
    assert [e["org_name"] for e in seen] == ["Client A"]

    # the firm admin still sees the whole book
    admin_view = client.get("/firm/engagements", headers=as_user(admin_id)).json()["engagements"]
    assert sorted(e["org_name"] for e in admin_view) == ["Client A", "Client B"]


def test_cannot_staff_an_auditor_from_another_firm(client):
    firm_a, admin_a = firm_with_admin(client, "Gemba")
    firm_b, _ = firm_with_admin(client, "Meridian")
    outsider = auditor(client, firm_b, email="outsider@meridian.test")
    request_id = request_onboarding(client, firm_a)
    engagement_id = client.post(f"/firm/onboarding-requests/{request_id}/approve",
                                headers=as_user(admin_a), json={}).json()["engagement_id"]

    denied = client.post(f"/firm/engagements/{engagement_id}/auditors",
                         headers=as_user(admin_a), json={"user_id": outsider})
    assert denied.status_code == 404


def test_the_firm_console_rejects_an_auditee_identity(client, bootstrap):
    org_id, _ = bootstrap(client)
    denied = client.get("/firm/engagements", headers={"authorization": f"org:{org_id}"})
    assert denied.status_code == 403


def test_dashboard_reports_progress_per_client(client, upload):
    firm_id, admin_id = firm_with_admin(client)
    request_id = request_onboarding(client, firm_id)
    approved = client.post(f"/firm/onboarding-requests/{request_id}/approve",
                           headers=as_user(admin_id), json={}).json()
    upload(client, approved["org_id"])

    row = client.get("/firm/engagements", headers=as_user(admin_id)).json()["engagements"][0]
    assert row["progress"]["controls"] > 0
    assert set(row["progress"]) == {"controls", "evaluated", "locked", "open_gaps"}
