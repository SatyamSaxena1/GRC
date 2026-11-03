"""User management (ADR-036): list, change role, deactivate, and what deactivation ends."""

from __future__ import annotations

from app.models import AuditEvent


def _org(client, name="Acme"):
    return client.post("/admin/organizations", json={"name": name, "frameworks": ["ISO-27001"]}).json()["id"]


def _user(client, email, org_id=None, firm_id=None, role="CONTROL_OWNER"):
    r = client.post("/admin/users", json={"email": email, "org_id": org_id, "audit_firm_id": firm_id, "role": role})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _as(user_id):
    return {"authorization": f"user:{user_id}"}


def test_an_org_admin_lists_only_their_own_team(client):
    acme, other = _org(client), _org(client, "Other")
    admin = _user(client, "a@acme.test", acme, role="ORG_ADMIN")
    _user(client, "o@acme.test", acme)
    _user(client, "x@other.test", other, role="ORG_ADMIN")

    team = client.get("/admin/users", headers=_as(admin)).json()
    assert [u["email"] for u in team] == ["a@acme.test", "o@acme.test"]
    assert all(u["active"] for u in team)


def test_only_admins_manage_users(client):
    acme = _org(client)
    _user(client, "a@acme.test", acme, role="ORG_ADMIN")
    owner = _user(client, "o@acme.test", acme)

    assert client.get("/admin/users", headers=_as(owner)).status_code == 403
    assert client.patch(f"/admin/users/{owner}", json={"active": False}, headers=_as(owner)).status_code == 403


def test_deactivation_ends_access_and_leaves_the_pickers(client):
    acme = _org(client)
    admin = _user(client, "a@acme.test", acme, role="ORG_ADMIN")
    owner = _user(client, "o@acme.test", acme)
    assert client.get("/controls", headers=_as(owner)).status_code == 200

    r = client.patch(f"/admin/users/{owner}", json={"active": False}, headers=_as(admin))
    assert r.status_code == 200 and r.json()["active"] is False

    assert client.get("/controls", headers=_as(owner)).status_code == 401  # a live session ends too
    pickers = client.get("/tasks/owners", headers=_as(admin)).json()
    assert [u["email"] for u in pickers] == ["a@acme.test"]

    client.patch(f"/admin/users/{owner}", json={"active": True}, headers=_as(admin))
    assert client.get("/controls", headers=_as(owner)).status_code == 200


def test_changes_are_audited_with_before_and_after(client, db):
    acme = _org(client)
    admin = _user(client, "a@acme.test", acme, role="ORG_ADMIN")
    owner = _user(client, "o@acme.test", acme)

    client.patch(f"/admin/users/{owner}", json={"role": "COMPLIANCE_VIEWER"}, headers=_as(admin))
    client.patch(f"/admin/users/{owner}", json={"role": "COMPLIANCE_VIEWER"}, headers=_as(admin))  # no change

    events = db.query(AuditEvent).filter_by(action="USER_UPDATED", entity=owner).all()
    assert len(events) == 1
    assert events[0].before == {"role": "CONTROL_OWNER", "active": True}
    assert events[0].after == {"role": "COMPLIANCE_VIEWER", "active": True}


def test_the_last_admin_cannot_be_removed_or_demoted(client):
    acme = _org(client)
    admin = _user(client, "a@acme.test", acme, role="ORG_ADMIN")

    demote = client.patch(f"/admin/users/{admin}", json={"role": "CONTROL_OWNER"}, headers=_as(admin))
    assert demote.status_code == 409 and "last active admin" in demote.json()["detail"]
    assert client.patch(f"/admin/users/{admin}", json={"active": False}, headers=_as(admin)).status_code == 409

    second = _user(client, "b@acme.test", acme, role="ORG_ADMIN")
    assert client.patch(f"/admin/users/{second}", json={"role": "CONTROL_OWNER"}, headers=_as(admin)).status_code == 200
    # the remaining admin still cannot lock themselves out
    assert client.patch(f"/admin/users/{admin}", json={"active": False}, headers=_as(admin)).status_code == 409


def test_another_organisations_users_are_invisible(client):
    acme, other = _org(client), _org(client, "Other")
    admin = _user(client, "a@acme.test", acme, role="ORG_ADMIN")
    stranger = _user(client, "x@other.test", other)

    assert client.patch(f"/admin/users/{stranger}", json={"active": False}, headers=_as(admin)).status_code == 404


def test_roles_are_checked_against_the_users_side(client):
    acme = _org(client)
    admin = _user(client, "a@acme.test", acme, role="ORG_ADMIN")
    owner = _user(client, "o@acme.test", acme)

    bad = client.patch(f"/admin/users/{owner}", json={"role": "FIRM_ADMIN"}, headers=_as(admin))
    assert bad.status_code == 422


def test_one_email_cannot_be_registered_twice(client):
    acme, other = _org(client), _org(client, "Other")
    _user(client, "a@acme.test", acme, role="ORG_ADMIN")

    dup = client.post("/admin/users", json={"email": "A@Acme.test", "org_id": other, "role": "CONTROL_OWNER"})
    assert dup.status_code == 409


def test_a_firm_admin_manages_the_firms_auditors(client):
    firm = client.post("/admin/audit-firms", json={"name": "BigFour"}).json()["id"]
    fadmin = _user(client, "f@firm.test", firm_id=firm, role="FIRM_ADMIN")
    auditor = _user(client, "u@firm.test", firm_id=firm, role="AUDITOR")

    assert {u["email"] for u in client.get("/admin/users", headers=_as(fadmin)).json()} == {"f@firm.test", "u@firm.test"}
    client.patch(f"/admin/users/{auditor}", json={"active": False}, headers=_as(fadmin))
    staff = client.get("/firm/auditors", headers=_as(fadmin)).json()["auditors"]
    assert [u["email"] for u in staff] == ["f@firm.test"]
    assert client.get("/firm/engagements", headers=_as(auditor)).status_code == 401


def test_an_org_admin_can_invite_without_knowing_the_org_id(client):
    acme = _org(client)
    admin = _user(client, "a@acme.test", acme, role="ORG_ADMIN")

    r = client.post("/admin/users", json={"email": "new@acme.test", "org_id": None, "role": "COMPLIANCE_VIEWER"},
                    headers=_as(admin))
    assert r.status_code == 200, r.text
    assert "new@acme.test" in [u["email"] for u in client.get("/admin/users", headers=_as(admin)).json()]
