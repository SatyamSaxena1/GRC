"""OIDC is additive: a JWT-shaped token routes to app/oidc.decode() and is
matched to a pre-provisioned user by email; everything else still falls
through to the untouched stub path (see docs/adr/011-oidc-auth.md).

app.oidc.decode is monkeypatched rather than signing a real JWT — its own
correctness (signature/issuer/audience verification) is PyJWT's, not ours;
what we own is what happens with the claims it returns.
"""

from __future__ import annotations

from app import oidc


FAKE_JWT = "header.payload.signature"  # three segments, nothing more required


def test_unknown_email_is_rejected(client, bootstrap, monkeypatch):
    org_id, _ = bootstrap(client)
    monkeypatch.setattr(oidc, "decode", lambda token: {"email": "nobody@acme.test"})

    resp = client.get("/controls", headers={"authorization": FAKE_JWT})
    assert resp.status_code == 401


def test_provisioned_org_admin_resolves_via_email_claim(client, bootstrap, monkeypatch):
    org_id, _ = bootstrap(client)
    client.post("/admin/users", json={
        "email": "admin@acme.test", "org_id": org_id, "role": "ORG_ADMIN",
    })
    monkeypatch.setattr(oidc, "decode", lambda token: {"email": "admin@acme.test"})

    resp = client.get("/controls", headers={"authorization": f"Bearer {FAKE_JWT}"})
    assert resp.status_code == 200


def test_control_owner_only_sees_assigned_controls_via_oidc(client, bootstrap, upload, monkeypatch):
    """Same least-privilege rule as the stub path (tests/test_authorization.py) —
    OIDC only changes how the actor is identified, not what they may see."""
    org_id, _ = bootstrap(client)
    upload(client, org_id)
    from app.models import OrgControl
    from sqlalchemy.orm import Session
    from app import db as db_module

    with Session(db_module.engine) as s:
        controls = {(c.framework, c.clause): c.id for c in s.query(OrgControl).filter_by(org_id=org_id)}
    assigned = controls[("ISO-27001", "A.5.15")]

    user = client.post("/admin/users", json={
        "email": "owner@acme.test", "org_id": org_id, "role": "CONTROL_OWNER",
    }).json()
    client.post("/admin/control-assignments", json={"org_control_id": assigned, "user_id": user["id"]})

    monkeypatch.setattr(oidc, "decode", lambda token: {"email": "owner@acme.test"})
    resp = client.get(f"/controls/{assigned}", headers={"authorization": f"Bearer {FAKE_JWT}"})
    assert resp.status_code == 200


def test_auditor_requires_engagement_header(client, bootstrap, monkeypatch):
    org_id, engagement_id = bootstrap(client)
    firm_id = client.post("/admin/audit-firms", json={"name": "Second Firm"}).json()["id"]
    client.post("/admin/users", json={
        "email": "auditor@bigfour.test", "audit_firm_id": firm_id, "role": "AUDITOR",
    })
    monkeypatch.setattr(oidc, "decode", lambda token: {"email": "auditor@bigfour.test"})

    without_header = client.get("/controls", headers={"authorization": f"Bearer {FAKE_JWT}"})
    assert without_header.status_code == 401


def test_auditor_engagement_must_belong_to_their_firm(client, bootstrap, monkeypatch):
    org_id, engagement_id = bootstrap(client)  # engagement belongs to the "BigFour" firm
    other_firm_id = client.post("/admin/audit-firms", json={"name": "Other Firm"}).json()["id"]
    client.post("/admin/users", json={
        "email": "auditor@other.test", "audit_firm_id": other_firm_id, "role": "AUDITOR",
    })
    monkeypatch.setattr(oidc, "decode", lambda token: {"email": "auditor@other.test"})

    resp = client.get("/controls", headers={
        "authorization": f"Bearer {FAKE_JWT}", "x-engagement-id": engagement_id,
    })
    assert resp.status_code == 404


def test_auditor_with_matching_engagement_succeeds(client, bootstrap, upload, monkeypatch):
    org_id, engagement_id = bootstrap(client)
    upload(client, org_id)
    # the firm bootstrap() created — read it back so the user belongs to the
    # same firm as the engagement rather than assuming a fixed id
    from app.models import Engagement
    from sqlalchemy.orm import Session
    from app import db as db_module

    with Session(db_module.engine) as s:
        firm_id = s.get(Engagement, engagement_id).audit_firm_id

    client.post("/admin/users", json={
        "email": "auditor@bigfour.test", "audit_firm_id": firm_id, "role": "AUDITOR",
    })
    monkeypatch.setattr(oidc, "decode", lambda token: {"email": "auditor@bigfour.test"})

    resp = client.get("/controls", headers={
        "authorization": f"Bearer {FAKE_JWT}", "x-engagement-id": engagement_id,
    })
    assert resp.status_code == 200
