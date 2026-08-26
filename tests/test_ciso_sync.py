"""A CISO Assistant sync failure or missing config must never block the
auditor action that triggered it; a CisoSyncState row is how success/failure
gets noticed afterward."""

from __future__ import annotations

import requests
from sqlalchemy.orm import Session

from app import db as db_module
from app.models import AuditEvent, CisoSyncState


def session():
    return Session(db_module.engine)


def _state(entity_id):
    with session() as s:
        return s.query(CisoSyncState).filter_by(local_entity_id=entity_id).one_or_none()


def test_unconfigured_client_is_skipped_not_failed(client, bootstrap, upload, monkeypatch):
    monkeypatch.delenv("CISO_ASSISTANT_BASE_URL", raising=False)
    monkeypatch.delenv("CISO_ASSISTANT_API_TOKEN", raising=False)
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    with session() as s:
        from app.models import EvidenceControlLink
        link_id = s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id).first().id

    resp = client.post(f"/audit/links/{link_id}/lock",
                       headers={"authorization": f"auditor:{engagement_id}"},
                       json={"verdict": "COMPLIANT"})
    assert resp.status_code == 200

    state = _state(link_id)
    assert state is not None and state.last_sync_status == "SKIPPED"


def test_successful_push_records_the_object_id(client, bootstrap, upload, monkeypatch):
    monkeypatch.setenv("CISO_ASSISTANT_BASE_URL", "http://ciso.test")
    monkeypatch.setenv("CISO_ASSISTANT_API_TOKEN", "secret-token")

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"id": "ca-object-1"}

    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse())

    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    with session() as s:
        from app.models import EvidenceControlLink
        link_id = s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id).first().id

    resp = client.post(f"/audit/links/{link_id}/lock",
                       headers={"authorization": f"auditor:{engagement_id}"},
                       json={"verdict": "COMPLIANT"})
    assert resp.status_code == 200

    state = _state(link_id)
    assert state.last_sync_status == "OK"
    assert state.ciso_assistant_object_id == "ca-object-1"


def test_failed_push_does_not_block_the_lock_and_is_audited(client, bootstrap, upload, monkeypatch):
    monkeypatch.setenv("CISO_ASSISTANT_BASE_URL", "http://ciso.test")
    monkeypatch.setenv("CISO_ASSISTANT_API_TOKEN", "secret-token")

    def _raise(*a, **k):
        raise requests.ConnectionError("ciso assistant unreachable")

    monkeypatch.setattr(requests, "post", _raise)

    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    with session() as s:
        from app.models import EvidenceControlLink
        link_id = s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id).first().id

    resp = client.post(f"/audit/links/{link_id}/lock",
                       headers={"authorization": f"auditor:{engagement_id}"},
                       json={"verdict": "COMPLIANT"})
    assert resp.status_code == 200  # the lock itself must still succeed

    state = _state(link_id)
    assert state.last_sync_status == "FAILED"
    assert "unreachable" in state.last_error

    with session() as s:
        failure = (s.query(AuditEvent).filter_by(action="CISO_SYNC_FAILED")
                   .order_by(AuditEvent.seq.desc()).first())
        assert failure is not None
        assert failure.entity == link_id
