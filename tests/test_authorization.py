"""Least privilege for control owners, and engagement-scoped access for auditors.

Both rules must hold in the backend. A 404 (not 403) for an unassigned or
out-of-scope control is deliberate: existence is itself information.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app import db as db_module
from app.models import EvidenceControlLink, OrgControl


def controls_for(org_id):
    with Session(db_module.engine) as s:
        return {(c.framework, c.clause): c.id
                for c in s.query(OrgControl).filter_by(org_id=org_id)}


def first_link(evidence_id):
    with Session(db_module.engine) as s:
        link = s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id).first()
        return link.id, link.framework, link.clause


@pytest.fixture()
def owner_setup(client, bootstrap, upload):
    """An org with evaluated controls and one control owner assigned to exactly one."""
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]

    user = client.post("/admin/users", json={
        "email": "owner@acme.test", "org_id": org_id, "role": "CONTROL_OWNER",
    }).json()

    controls = controls_for(org_id)
    assigned_key = ("ISO-27001", "A.5.15")
    assigned_id = controls[assigned_key]
    client.post("/admin/control-assignments",
                json={"org_control_id": assigned_id, "user_id": user["id"]})
    unassigned_id = controls[("PCI-DSS", "8.3.6")]
    return org_id, engagement_id, evidence_id, user["id"], assigned_id, unassigned_id


def test_control_owner_sees_only_assigned_controls(client, owner_setup):
    _, _, _, user_id, assigned_id, unassigned_id = owner_setup
    headers = {"authorization": f"user:{user_id}"}

    listed = client.get("/controls", headers=headers).json()
    assert [c["id"] for c in listed] == [assigned_id]

    assert client.get(f"/controls/{assigned_id}", headers=headers).status_code == 200
    assert client.get(f"/controls/{unassigned_id}", headers=headers).status_code == 404


def test_control_owner_cannot_read_unassigned_control_evidence_or_history(client, owner_setup):
    _, _, _, user_id, _, unassigned_id = owner_setup
    headers = {"authorization": f"user:{user_id}"}
    for path in ("", "/evidence", "/history"):
        assert client.get(f"/controls/{unassigned_id}{path}", headers=headers).status_code == 404


def test_control_owner_evidence_view_is_filtered_to_assigned_controls(client, owner_setup):
    _, _, evidence_id, user_id, _, _ = owner_setup
    links = client.get(f"/evidence/{evidence_id}/evaluations",
                       headers={"authorization": f"user:{user_id}"}).json()
    assert {(l["framework"], l["clause"]) for l in links} == {("ISO-27001", "A.5.15")}


def test_org_admin_still_sees_everything(client, owner_setup):
    org_id, _, evidence_id, _, _, _ = owner_setup
    links = client.get(f"/evidence/{evidence_id}/evaluations",
                       headers={"authorization": f"org:{org_id}"}).json()
    assert len(links) > 1


def test_auditor_without_allocation_cannot_see_the_framework(client, bootstrap, upload):
    """An ACTIVE engagement is necessary but not sufficient — scope must cover it."""
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]

    firm = client.post("/admin/audit-firms", json={"name": "NarrowScope"}).json()
    narrow = client.post("/admin/engagements", json={
        "audit_firm_id": firm["id"], "org_id": org_id, "frameworks": ["ISO-27001"],
    }).json()

    links = client.get(f"/evidence/{evidence_id}/evaluations",
                       headers={"authorization": f"auditor:{narrow['id']}"}).json()
    assert {l["framework"] for l in links} == {"ISO-27001"}

    pci_link = next(l for l in client.get(
        f"/evidence/{evidence_id}/evaluations",
        headers={"authorization": f"org:{org_id}"}).json() if l["framework"] == "PCI-DSS")
    denied = client.post(f"/audit/links/{pci_link['id']}/lock",
                         headers={"authorization": f"auditor:{narrow['id']}"},
                         json={"verdict": "PASS"})
    assert denied.status_code == 404


def test_closing_an_engagement_revokes_access_immediately(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    headers = {"authorization": f"auditor:{engagement_id}"}

    assert client.get(f"/evidence/{evidence_id}", headers=headers).status_code == 200

    client.post(f"/admin/engagements/{engagement_id}/close")

    assert client.get(f"/evidence/{evidence_id}", headers=headers).status_code == 404
    link_id, _, _ = first_link(evidence_id)
    assert client.post(f"/audit/links/{link_id}/lock", headers=headers,
                       json={"verdict": "PASS"}).status_code == 404


def test_auditee_cannot_lock_a_control(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    link_id, _, _ = first_link(evidence_id)

    resp = client.post(f"/audit/links/{link_id}/lock",
                       headers={"authorization": f"org:{org_id}"}, json={"verdict": "PASS"})
    assert resp.status_code == 403


def test_unknown_engagement_token_is_rejected(client):
    assert client.get("/controls", headers={"authorization": "auditor:does-not-exist"}).status_code == 404
    assert client.get("/controls", headers={"authorization": "user:does-not-exist"}).status_code == 401
    assert client.get("/controls", headers={"authorization": "garbage"}).status_code == 401


# ------------------------------------------------- segregation of duties (BR66)


def test_uploader_cannot_record_the_verdict_on_their_own_evidence(client, bootstrap, upload):
    """Concept note Appendix B rule 66. Structurally an auditor cannot upload, but
    one human holding both identities must be stopped by the backend, not trusted
    to abstain."""
    from sqlalchemy.orm import Session
    from app import db as db_module
    from app.models import AuditEvent, Evidence

    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    link_id, _, _ = first_link(evidence_id)

    # Simulate the conflict: the same principal that recorded the upload now
    # attempts the audit verdict.
    with Session(db_module.engine) as s:
        evidence = s.get(Evidence, evidence_id)
        evidence.uploaded_by = f"auditor:{engagement_id}"
        s.commit()

    headers = {"authorization": f"auditor:{engagement_id}"}
    blocked = client.post(f"/audit/links/{link_id}/verdict", headers=headers,
                          json={"verdict": "COMPLIANT"})
    assert blocked.status_code == 403
    assert "segregation of duties" in blocked.json()["detail"].lower()

    # Locking by the same route is refused too, not just the verdict endpoint.
    assert client.post(f"/audit/links/{link_id}/lock", headers=headers,
                       json={"verdict": "COMPLIANT"}).status_code == 403

    with Session(db_module.engine) as s:
        assert s.query(AuditEvent).filter_by(action="SEGREGATION_OF_DUTIES_BLOCKED").count() >= 1


def test_a_different_auditor_may_still_record_the_verdict(client, bootstrap, upload):
    """The rule separates duties; it must not deadlock the audit."""
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    link_id, _, _ = first_link(evidence_id)

    ok = client.post(f"/audit/links/{link_id}/verdict",
                     headers={"authorization": f"auditor:{engagement_id}"},
                     json={"verdict": "COMPLIANT"})
    assert ok.status_code == 200  # uploaded by org:<id>, reviewed by auditor:<id>
