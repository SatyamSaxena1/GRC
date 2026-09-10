"""COMPLIANCE_VIEWER: the whole org's posture, read-only.

Same visibility as ORG_ADMIN (unlike CONTROL_OWNER, which is clamped to its
ControlAssignment rows), and every auditee-side write path refused with 403.
See docs/adr/017-compliance-officer-persona.md.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app import db as db_module
from app.models import EvidenceControlLink, OrgControl


def _controls(org_id):
    with Session(db_module.engine) as s:
        return {(c.framework, c.clause): c.id
                for c in s.query(OrgControl).filter_by(org_id=org_id)}


def _first_link(evidence_id):
    with Session(db_module.engine) as s:
        return s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id).first().id


@pytest.fixture()
def viewer_setup(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    viewer = client.post("/admin/users", json={
        "email": "reviewer@acme.test", "org_id": org_id, "role": "COMPLIANCE_VIEWER",
    }).json()["id"]
    return org_id, engagement_id, evidence_id, viewer


def test_viewer_sees_the_whole_org_not_just_assigned_controls(client, viewer_setup):
    org_id, _, evidence_id, viewer = viewer_setup
    headers = {"authorization": f"user:{viewer}"}
    controls = _controls(org_id)

    listed = client.get("/controls", headers=headers).json()
    assert {c["id"] for c in listed} == set(controls.values())          # every clause, both frameworks

    unassigned = controls[("PCI-DSS", "8.3.6")]                          # a CONTROL_OWNER gets 404 here
    assert client.get(f"/controls/{unassigned}", headers=headers).status_code == 200

    links = client.get(f"/evidence/{evidence_id}/evaluations", headers=headers).json()
    assert len({l["framework"] for l in links}) > 1

    for path in ("/analytics/dashboard", "/gaps", "/tasks", f"/evidence/{evidence_id}"):
        assert client.get(path, headers=headers).status_code == 200


@pytest.mark.parametrize("method,path,kwargs", [
    ("post",  "/evidence", {"params": {"artefact_type": "POLICY"},
                            "files": {"file": ("p.txt", b"x", "text/plain")}}),
    ("post",  "/evidence/{ev}/versions", {"files": {"file": ("p.txt", b"x", "text/plain")}}),
    ("post",  "/evidence/{ev}/reprocess", {}),
    ("patch", "/evidence/{ev}", {"json": {"description": "mine now"}}),
    ("delete", "/evidence/{ev}", {}),
    ("post",  "/controls/{ctl}/submit", {}),
    ("post",  "/controls/{ctl}/messages", {"json": {"kind": "COMMENT", "body": "hi"}}),
    ("post",  "/connectors/aws/sync", {}),
    ("post",  "/tasks", {"json": {"title": "not mine to make"}}),
    ("post",  "/admin/ciso-sync/evidence_control_link/{link}/retry", {}),
])
def test_viewer_is_refused_every_write_path(client, viewer_setup, method, path, kwargs):
    org_id, _, evidence_id, viewer = viewer_setup
    ctl = next(iter(_controls(org_id).values()))
    url = path.format(ev=evidence_id, ctl=ctl, link=_first_link(evidence_id))

    resp = getattr(client, method)(url, headers={"authorization": f"user:{viewer}"}, **kwargs)
    assert resp.status_code == 403, (url, resp.status_code, resp.text)


def test_write_gate_still_lets_a_control_owner_upload(client, viewer_setup):
    """The can_write seam must still let an ordinary auditee user upload."""
    org_id, _, _, _ = viewer_setup
    owner = client.post("/admin/users", json={
        "email": "owner@acme.test", "org_id": org_id, "role": "CONTROL_OWNER",
    }).json()["id"]
    resp = client.post("/evidence", headers={"authorization": f"user:{owner}"},
                       params={"artefact_type": "POLICY"},
                       files={"file": ("owner.txt", b"a distinct policy from the control owner", "text/plain")})
    assert resp.status_code == 202
