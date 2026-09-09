"""End-to-end: upload -> evaluate -> lock -> reupload -> tenancy isolation.

No Ollama server is assumed in the test env, so extraction returns all-null
fields and requirements correctly come back FAIL. That is itself a useful
check: the pipeline must never invent a pass when extraction is unavailable.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import db as db_module
from app.models import AuditEvent, Evidence, EvidenceControlLink, GapRow


def session():
    return Session(db_module.engine)


def test_upload_evaluates_against_both_frameworks(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    resp = upload(client, org_id)
    assert resp.status_code == 202
    evidence_id = resp.json()["evidence_id"]

    detail = client.get(f"/evidence/{evidence_id}",
                        headers={"authorization": f"org:{org_id}"}).json()
    assert detail["status"] == "READY"
    assert {l["framework"] for l in detail["links"]} == {"ISO-27001", "PCI-DSS"}
    assert all(l["verdict"] == "FAIL" for l in detail["links"])  # no model -> nothing extracted
    assert detail["sha256"]


def test_status_endpoint_reports_lifecycle(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    status = client.get(f"/evidence/{evidence_id}/status",
                        headers={"authorization": f"org:{org_id}"}).json()
    assert status["status"] in {"READY", "NEEDS_REVIEW"}
    assert status["lifecycle_status"] == "CURRENT"


def test_auditor_cannot_upload_only_review(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    resp = client.post("/evidence", headers={"authorization": f"auditor:{engagement_id}"},
                       files={"file": ("policy.txt", b"x", "text/plain")})
    assert resp.status_code == 403


def test_lock_then_reupload_leaves_locked_link_untouched(client, bootstrap, upload):
    """A locked link belongs only to the version the auditor reviewed: never
    cloned forward, never silently changed, and the change is announced."""
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]

    with session() as s:
        link_id = s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id).first().id

    locked = client.post(f"/audit/links/{link_id}/lock",
                         headers={"authorization": f"auditor:{engagement_id}"},
                         json={"verdict": "PASS"})
    assert locked.status_code == 200

    new_version = client.post(f"/evidence/{evidence_id}/versions",
                              headers={"authorization": f"org:{org_id}"},
                              files={"file": ("policy_v2.txt", b"revised policy", "text/plain")}).json()

    with session() as s:
        original = s.get(EvidenceControlLink, link_id)
        assert original.verdict == "PASS" and original.locked  # untouched on V1

        # V2 gets its own independent evaluation; what must never happen is V2
        # inheriting V1's locked verdict.
        v2_link = s.query(EvidenceControlLink).filter_by(
            evidence_id=new_version["evidence_id"], framework=original.framework,
            clause=original.clause).one()
        assert not v2_link.locked
        assert v2_link.id != original.id

        events = s.query(AuditEvent).filter_by(action="EVIDENCE_CHANGED_AFTER_LOCK").all()
        assert len(events) == 1
        assert events[0].detail["old_evidence_id"] == evidence_id
        assert events[0].detail["new_evidence_id"] == new_version["evidence_id"]


def test_v1_remains_retrievable_after_supersession(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    v1 = upload(client, org_id).json()["evidence_id"]
    v2 = client.post(f"/evidence/{v1}/versions", headers={"authorization": f"org:{org_id}"},
                     files={"file": ("policy_v2.txt", b"revised policy", "text/plain")}).json()

    headers = {"authorization": f"org:{org_id}"}
    assert client.get(f"/evidence/{v1}", headers=headers).json()["lifecycle_status"] == "SUPERSEDED"
    assert client.get(f"/evidence/{v2['evidence_id']}", headers=headers).json()["lifecycle_status"] == "CURRENT"

    lineage = client.get(f"/evidence/{v1}/versions", headers=headers).json()
    assert [e["version"] for e in lineage] == [1, 2]


def test_gap_history_is_preserved_not_deleted(client, bootstrap, upload):
    """Re-evaluating must resolve gaps that stop reproducing, never delete rows."""
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]

    with session() as s:
        before = s.query(GapRow).count()
        assert before > 0

        from types import SimpleNamespace
        from app.service import _reconcile_gaps

        for link in s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id):
            _reconcile_gaps(s, link, [], SimpleNamespace(id=evidence_id))
        s.commit()

        rows = s.query(GapRow).all()
        assert len(rows) == before  # nothing deleted
        assert all(r.status == "RESOLVED_BY_EVIDENCE" and r.resolved_at for r in rows)


def test_gaps_carry_actionable_remediation(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    upload(client, org_id)
    gaps = client.get("/gaps", headers={"authorization": f"org:{org_id}"}).json()
    assert gaps
    assert all(g["required_action"] and "insufficient" not in g["required_action"].lower()
               for g in gaps)


def test_control_detail_carries_requirement_text_and_owners(client, bootstrap, upload):
    """The record header needs more than a bare clause code to be readable —
    see app/routers/controls.py::_requirement_text / _owner_emails."""
    org_id, _ = bootstrap(client)
    upload(client, org_id)
    headers = {"authorization": f"org:{org_id}"}
    control_id = next(c["id"] for c in client.get("/controls", headers=headers).json())

    detail = client.get(f"/controls/{control_id}", headers=headers).json()
    assert detail["title"] and detail["text"]
    assert detail["owner_emails"] == []

    owner = client.post("/admin/users", json={
        "email": "owner@acme.test", "org_id": org_id, "role": "CONTROL_OWNER",
    }).json()
    client.post("/admin/control-assignments",
               json={"org_control_id": control_id, "user_id": owner["id"]})

    detail = client.get(f"/controls/{control_id}", headers=headers).json()
    assert detail["owner_emails"] == ["owner@acme.test"]


def test_submitting_a_control_appears_in_its_own_history(client, bootstrap, upload):
    """CONTROL_SUBMITTED is recorded against the control itself, not a link —
    a filter that only matched link ids silently dropped it forever."""
    org_id, _ = bootstrap(client)
    upload(client, org_id)
    headers = {"authorization": f"org:{org_id}"}
    control_id = next(c["id"] for c in client.get("/controls", headers=headers).json())

    assert client.post(f"/controls/{control_id}/submit", headers=headers).status_code == 200

    history = client.get(f"/controls/{control_id}/history", headers=headers).json()
    assert any(e["action"] == "CONTROL_SUBMITTED" for e in history)


def test_tasks_are_created_per_gap(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    upload(client, org_id)
    tasks = client.get("/tasks", headers={"authorization": f"org:{org_id}"}).json()
    gaps = client.get("/gaps", headers={"authorization": f"org:{org_id}"}).json()
    assert len(tasks) == len(gaps)


def test_task_work_queue_filters_updates_and_audits(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    upload(client, org_id)
    owner_id = client.post("/admin/users", json={
        "email": "owner@example.test", "org_id": org_id, "role": "CONTROL_OWNER",
    }).json()["id"]
    headers = {"authorization": f"org:{org_id}"}
    task = client.get("/tasks", headers=headers).json()[0]

    updated = client.patch(f"/tasks/{task['id']}", headers=headers, json={
        "owner_user_id": owner_id,
        "due_at": "2026-09-30T00:00:00Z",
        "priority": "HIGH",
    })
    assert updated.status_code == 200
    assert updated.json()["owner_email"] == "owner@example.test"
    assert updated.json()["priority"] == "HIGH"

    filtered = client.get("/tasks", headers=headers, params={
        "priority": "HIGH", "owner_user_id": owner_id,
        "q": task["title"].split(":", 1)[0],
    }).json()
    assert [row["id"] for row in filtered] == [task["id"]]

    detail = client.get(f"/tasks/{task['id']}", headers=headers).json()
    assert detail["required_action"] and detail["history"][-1]["action"] == "TASK_UPDATED"
    assert detail["history"][-1]["before"]["priority"] == "MEDIUM"
    assert detail["history"][-1]["after"]["priority"] == "HIGH"

    refused = client.patch(f"/tasks/{task['id']}",
                           headers={"authorization": f"auditor:{engagement_id}"},
                           json={"priority": "LOW"})
    assert refused.status_code == 403


def test_cross_tenant_access_is_404_not_403(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    other = client.post("/admin/organizations",
                        json={"name": "Other", "frameworks": []}).json()["id"]
    evidence_id = upload(client, org_id).json()["evidence_id"]

    for path in ("", "/status", "/attributes", "/evaluations", "/versions", "/history"):
        resp = client.get(f"/evidence/{evidence_id}{path}",
                          headers={"authorization": f"org:{other}"})
        assert resp.status_code == 404, path


def test_cross_tenant_version_upload_is_refused(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    other = client.post("/admin/organizations",
                        json={"name": "Other", "frameworks": []}).json()["id"]
    evidence_id = upload(client, org_id).json()["evidence_id"]

    resp = client.post(f"/evidence/{evidence_id}/versions",
                       headers={"authorization": f"org:{other}"},
                       files={"file": ("x.txt", b"hostile", "text/plain")})
    assert resp.status_code == 404


def test_health_endpoints(client, bootstrap, upload):
    assert client.get("/health/live").json()["status"] == "ok"
    assert "database" in client.get("/health/ready").json()["checks"]


def test_list_evidence_returns_organisation_evidence(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    headers = {"authorization": f"org:{org_id}"}
    first = upload(client, org_id, content=b"policy one", name="one.txt").json()["evidence_id"]
    second = upload(client, org_id, content=b"policy two", name="two.txt").json()["evidence_id"]

    rows = client.get("/evidence", headers=headers).json()
    ids = {r["id"] for r in rows}
    assert ids == {first, second}
    assert all(r["original_filename"] and r["artefact_type"] == "POLICY" for r in rows)


def test_list_evidence_filters_by_artefact_type_and_lifecycle(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    headers = {"authorization": f"org:{org_id}"}
    policy_id = upload(client, org_id, content=b"a policy", name="p.txt", artefact_type="POLICY").json()["evidence_id"]
    scan_id = upload(client, org_id, content=b"a scan", name="s.txt", artefact_type="SCAN_REPORT").json()["evidence_id"]

    policies = client.get("/evidence", headers=headers, params={"artefact_type": "POLICY"}).json()
    assert {r["id"] for r in policies} == {policy_id}

    scans = client.get("/evidence", headers=headers, params={"artefact_type": "SCAN_REPORT"}).json()
    assert {r["id"] for r in scans} == {scan_id}

    # supersede the policy; the list should be filterable to just what is current
    client.post(f"/evidence/{policy_id}/versions", headers=headers,
                files={"file": ("p2.txt", b"a revised policy", "text/plain")})
    current = client.get("/evidence", headers=headers, params={"lifecycle_status": "CURRENT"}).json()
    superseded = client.get("/evidence", headers=headers, params={"lifecycle_status": "SUPERSEDED"}).json()
    assert policy_id in {r["id"] for r in superseded}
    assert policy_id not in {r["id"] for r in current}
    assert scan_id in {r["id"] for r in current}


def test_list_evidence_is_tenant_scoped(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    upload(client, org_id, content=b"policy")
    other = client.post("/admin/organizations", json={"name": "Other", "frameworks": []}).json()["id"]

    theirs = client.get("/evidence", headers={"authorization": f"org:{other}"}).json()
    assert theirs == []
