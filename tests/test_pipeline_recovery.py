"""A failing pipeline must end somewhere a human can see, and be recoverable.

process_evidence runs as a background task, so an exception escaping it reaches
nothing that records it — main.py's handler covers requests, not background
tasks. The row would sit in a non-terminal status forever while the frontend
polls it every 2.5s. These tests pin the guard and the retry path.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app import db as db_module
from app import service
from app.models import AuditEvent, Evidence, EvidenceControlLink
from app.quality import score_evidence as real_score_evidence

# Restore by re-patching, never monkeypatch.undo(): the `client` fixture shares
# this function-scoped monkeypatch and undo() would also revert its engine and
# storage-dir patches, pointing the rest of the test at the real database.
def unbreak(monkeypatch) -> None:
    monkeypatch.setattr(service, "score_evidence", real_score_evidence)


def status_of(evidence_id: str) -> tuple[str, str]:
    with Session(db_module.engine) as s:
        evidence = s.get(Evidence, evidence_id)
        return evidence.status, evidence.status_detail


def boom(*args, **kwargs):
    raise RuntimeError("quality scoring blew up")


def test_a_failure_after_extraction_ends_at_failed_not_stuck(client, bootstrap, upload, monkeypatch):
    """score_evidence sits in what used to be the unguarded half of the pipeline
    (after the old try/except closed). A failure there left the row at ANALYZING."""
    monkeypatch.setattr(service, "score_evidence", boom)
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]

    status, detail = status_of(evidence_id)
    assert status == "FAILED"
    assert "quality scoring blew up" in detail


def test_reprocess_recovers_evidence_that_failed(client, bootstrap, upload, monkeypatch):
    monkeypatch.setattr(service, "score_evidence", boom)
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    assert status_of(evidence_id)[0] == "FAILED"

    unbreak(monkeypatch)  # whatever was broken is fixed; the file was never lost
    resp = client.post(f"/evidence/{evidence_id}/reprocess",
                       headers={"authorization": f"org:{org_id}"})
    assert resp.status_code == 202
    # No model in the test env, so the recovered run lands at NEEDS_REVIEW (not
    # FAILED, not a fake READY) — the point is it left FAILED and is now settled.
    assert status_of(evidence_id)[0] == "NEEDS_REVIEW"


def test_reprocess_of_a_settled_row_without_a_lock_is_allowed(client, bootstrap, upload):
    """A NEEDS_REVIEW row (here: extraction was unavailable) with nothing locked
    is exactly what reprocess exists to rescue — re-running is not a back door."""
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    assert status_of(evidence_id)[0] == "NEEDS_REVIEW"

    resp = client.post(f"/evidence/{evidence_id}/reprocess",
                       headers={"authorization": f"org:{org_id}"})
    assert resp.status_code == 202


def test_reprocess_is_refused_once_an_auditor_has_locked_a_verdict(client, bootstrap, upload):
    """Recovery only — never a back door to recompute verdicts an auditor has
    already acted on. The guard is the lock, not the status."""
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]

    with Session(db_module.engine) as s:
        link_id = s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id).first().id
    locked = client.post(f"/audit/links/{link_id}/lock",
                         headers={"authorization": f"auditor:{engagement_id}"},
                         json={"verdict": "PASS"})
    assert locked.status_code == 200

    resp = client.post(f"/evidence/{evidence_id}/reprocess",
                       headers={"authorization": f"org:{org_id}"})
    assert resp.status_code == 409


def test_auditors_cannot_reprocess_evidence(client, bootstrap, upload, monkeypatch):
    monkeypatch.setattr(service, "score_evidence", boom)
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]

    resp = client.post(f"/evidence/{evidence_id}/reprocess",
                       headers={"authorization": f"auditor:{engagement_id}"})
    assert resp.status_code == 403


def test_reprocess_is_recorded_in_the_audit_trail(client, bootstrap, upload, monkeypatch):
    monkeypatch.setattr(service, "score_evidence", boom)
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    unbreak(monkeypatch)
    client.post(f"/evidence/{evidence_id}/reprocess", headers={"authorization": f"org:{org_id}"})

    with Session(db_module.engine) as s:
        events = [
            e for e in s.query(AuditEvent).filter_by(entity=evidence_id).order_by(AuditEvent.seq)
            if e.action == "EVIDENCE_REPROCESS_REQUESTED"
        ]
    assert len(events) == 1
    assert events[0].detail["from_status"] == "FAILED"


def test_cross_tenant_reprocess_is_invisible(client, bootstrap, upload, monkeypatch):
    monkeypatch.setattr(service, "score_evidence", boom)
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    other = client.post("/admin/organizations",
                        json={"name": "Other", "frameworks": []}).json()["id"]

    resp = client.post(f"/evidence/{evidence_id}/reprocess",
                       headers={"authorization": f"org:{other}"})
    assert resp.status_code == 404
