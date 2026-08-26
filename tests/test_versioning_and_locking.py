"""The V1 -> V2 -> V3 lifecycle, including what a lock does and does not stop.

Extraction is stubbed here so the versioning logic is tested deterministically:
the point of these tests is the state machine, not the model.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app import db as db_module, service
from app.ai.schemas import ExtractedField, ExtractionRun
from app.models import AuditEvent, Evidence, EvidenceControlLink, GapRow

COMPLIANT = {
    "approval_date": "2026-03-12", "approver_role": "Chief Information Security Officer",
    "effective_date": "2026-03-12",
    "systems_covered": ["Corporate IT", "Cardholder Data Environment"],
    "password_min_length": 14,
    "mfa_required_for": ["remote access", "administrative access"],
    "access_review_frequency_days": 90,
}
NON_COMPLIANT = COMPLIANT | {
    "password_min_length": 8, "systems_covered": ["Corporate IT"],
}


@pytest.fixture()
def stub_extraction(monkeypatch):
    """Swap the model call for a scripted result, keyed by file content."""
    def _install(mapping: dict[bytes, dict]):
        state = {"current": {}}

        def fake_read_document(filename, content, gateway=None):
            state["current"] = mapping.get(content, {})
            return "stubbed text", "native_text"

        def fake_extract(text, names, method="native_text", gateway=None):
            values = state["current"]
            return ExtractionRun(
                fields={n: ExtractedField(value=values.get(n), confidence=0.9 if n in values else None,
                                          extraction_method=method if n in values else "none")
                        for n in names},
                model="stub", provider="stub", prompt_template_version="stub:v1",
            )

        monkeypatch.setattr(service, "read_document", fake_read_document)
        monkeypatch.setattr(service, "extract_attributes", fake_extract)
    return _install


def links_of(evidence_id):
    with Session(db_module.engine) as s:
        return {(l.framework, l.clause): l
                for l in s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id)}


def test_v2_resolves_gaps_and_keeps_their_history(client, bootstrap, upload, stub_extraction):
    stub_extraction({b"v1": NON_COMPLIANT, b"v2": COMPLIANT})
    org_id, _ = bootstrap(client)
    headers = {"authorization": f"org:{org_id}"}

    v1 = upload(client, org_id, content=b"v1").json()["evidence_id"]
    v1_gaps = client.get("/gaps", headers=headers).json()
    assert {g["attribute"] for g in v1_gaps} >= {"password_min_length", "systems_covered"}
    assert all(g["status"] == "OPEN" for g in v1_gaps)

    v2 = client.post(f"/evidence/{v1}/versions", headers=headers,
                     files={"file": ("policy_v2.txt", b"v2", "text/plain")}).json()

    v2_links = links_of(v2["evidence_id"])
    assert v2_links[("PCI-DSS", "8.3.6")].verdict == "PASS"

    # V1's gap rows stay on record — resolved, never deleted
    all_gaps = client.get("/gaps", headers=headers).json()
    v1_gaps = [g for g in all_gaps if g["evidence_id"] == v1]
    assert v1_gaps, "historical gaps must remain queryable"

    password_gap = next(g for g in v1_gaps if g["attribute"] == "password_min_length")
    assert password_gap["status"] == "RESOLVED_BY_EVIDENCE"
    assert password_gap["resolved_by_evidence_id"] == v2["evidence_id"]
    assert password_gap["actual_value"] == "8"  # what V1 actually said, preserved


def test_gap_still_failing_in_v2_stays_open(client, bootstrap, upload, stub_extraction):
    """Only gaps the new version actually fixes are resolved."""
    partially_fixed = NON_COMPLIANT | {"password_min_length": 14}  # scope still wrong
    stub_extraction({b"v1": NON_COMPLIANT, b"v2": partially_fixed})
    org_id, _ = bootstrap(client)
    headers = {"authorization": f"org:{org_id}"}

    v1 = upload(client, org_id, content=b"v1").json()["evidence_id"]
    client.post(f"/evidence/{v1}/versions", headers=headers,
                files={"file": ("v2.txt", b"v2", "text/plain")})

    v1_gaps = {g["attribute"]: g for g in client.get("/gaps", headers=headers).json()
               if g["evidence_id"] == v1}
    assert v1_gaps["password_min_length"]["status"] == "RESOLVED_BY_EVIDENCE"
    assert v1_gaps["systems_covered"]["status"] == "OPEN"  # never fixed, stays open


def test_reevaluating_same_version_resolves_gap_and_closes_task(client, bootstrap, upload,
                                                                stub_extraction, monkeypatch):
    """A gap that stops reproducing is RESOLVED_BY_EVIDENCE with its task closed."""
    stub_extraction({b"v1": NON_COMPLIANT})
    org_id, _ = bootstrap(client)
    headers = {"authorization": f"org:{org_id}"}
    evidence_id = upload(client, org_id, content=b"v1").json()["evidence_id"]

    open_gaps = [g for g in client.get("/gaps", headers=headers).json() if g["status"] == "OPEN"]
    assert open_gaps

    # same evidence, now extracting compliant values
    stub_extraction({b"v1": COMPLIANT})
    with Session(db_module.engine) as s:
        evidence = s.get(Evidence, evidence_id)
        from app.routers.evidence import CONTENT
        service.process_evidence(s, CONTENT, evidence, "org:test")

    gaps = client.get("/gaps", headers=headers).json()
    resolved = [g for g in gaps if g["status"] == "RESOLVED_BY_EVIDENCE"]
    assert resolved
    assert all(g["resolved_by_evidence_id"] == evidence_id for g in resolved)

    tasks = client.get("/tasks", headers=headers).json()
    assert any(t["status"] == "DONE" for t in tasks)


def test_locked_control_blocks_auditee_submission(client, bootstrap, upload, stub_extraction):
    stub_extraction({b"v1": COMPLIANT})
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id, content=b"v1").json()["evidence_id"]

    link = links_of(evidence_id)[("ISO-27001", "A.5.15")]
    client.post(f"/audit/links/{link.id}/verdict",
                headers={"authorization": f"auditor:{engagement_id}"},
                json={"verdict": "COMPLIANT", "reason": "reviewed"})

    from app.models import OrgControl
    with Session(db_module.engine) as s:
        control = s.query(OrgControl).filter_by(
            org_id=org_id, framework="ISO-27001", clause="A.5.15").one()
        control_id = control.id

    blocked = client.post(f"/controls/{control_id}/submit",
                          headers={"authorization": f"org:{org_id}"})
    assert blocked.status_code == 423


def test_compliant_verdict_locks_the_control(client, bootstrap, upload, stub_extraction):
    stub_extraction({b"v1": COMPLIANT})
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id, content=b"v1").json()["evidence_id"]
    link = links_of(evidence_id)[("ISO-27001", "A.5.15")]

    resp = client.post(f"/audit/links/{link.id}/verdict",
                       headers={"authorization": f"auditor:{engagement_id}"},
                       json={"verdict": "COMPLIANT", "reason": "evidence reviewed"})
    assert resp.json()["locked"] is True


def test_unlock_requires_a_reason_and_is_recorded(client, bootstrap, upload, stub_extraction):
    stub_extraction({b"v1": COMPLIANT})
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id, content=b"v1").json()["evidence_id"]
    link = links_of(evidence_id)[("ISO-27001", "A.5.15")]
    headers = {"authorization": f"auditor:{engagement_id}"}

    client.post(f"/audit/links/{link.id}/lock", headers=headers, json={"verdict": "COMPLIANT"})

    assert client.post(f"/audit/links/{link.id}/unlock", headers=headers,
                       json={"reason": ""}).status_code == 422

    ok = client.post(f"/audit/links/{link.id}/unlock", headers=headers,
                     json={"reason": "new evidence supplied after lock"})
    assert ok.status_code == 200 and ok.json()["locked"] is False

    with Session(db_module.engine) as s:
        event = s.query(AuditEvent).filter_by(action="CONTROL_UNLOCKED").one()
        assert event.reason == "new evidence supplied after lock"


def test_v3_after_lock_leaves_the_locked_verdict_alone(client, bootstrap, upload, stub_extraction):
    """The full scenario: lock on V2, then upload V3."""
    stub_extraction({b"v1": NON_COMPLIANT, b"v2": COMPLIANT, b"v3": NON_COMPLIANT})
    org_id, engagement_id = bootstrap(client)
    headers = {"authorization": f"org:{org_id}"}

    v1 = upload(client, org_id, content=b"v1").json()["evidence_id"]
    v2 = client.post(f"/evidence/{v1}/versions", headers=headers,
                     files={"file": ("v2.txt", b"v2", "text/plain")}).json()["evidence_id"]

    link = links_of(v2)[("PCI-DSS", "8.3.6")]
    client.post(f"/audit/links/{link.id}/lock",
                headers={"authorization": f"auditor:{engagement_id}"},
                json={"verdict": "COMPLIANT"})

    v3 = client.post(f"/evidence/{v2}/versions", headers=headers,
                     files={"file": ("v3.txt", b"v3", "text/plain")}).json()["evidence_id"]

    with Session(db_module.engine) as s:
        locked = s.get(EvidenceControlLink, link.id)
        assert locked.verdict == "COMPLIANT" and locked.locked  # untouched by V3

        changed = s.query(AuditEvent).filter_by(action="EVIDENCE_CHANGED_AFTER_LOCK").all()
        assert any(e.detail["new_evidence_id"] == v3 for e in changed)

        # every version remains retrievable
        assert s.get(Evidence, v1).lifecycle_status == "SUPERSEDED"
        assert s.get(Evidence, v2).lifecycle_status == "SUPERSEDED"
        assert s.get(Evidence, v3).lifecycle_status == "CURRENT"


def test_audit_log_is_hash_chained_and_verifiable(client, bootstrap, upload, stub_extraction):
    from app.audit_log import verify_chain

    stub_extraction({b"v1": COMPLIANT})
    org_id, _ = bootstrap(client)
    upload(client, org_id, content=b"v1")

    with Session(db_module.engine) as s:
        assert verify_chain(s) is True

        tampered = s.query(AuditEvent).filter_by(action="EVIDENCE_UPLOADED").first()
        tampered.detail = {"sha256": "0" * 64}
        s.commit()
        assert verify_chain(s) is False  # tampering is detectable
