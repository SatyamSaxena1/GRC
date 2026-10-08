"""Auditor-held signed checkpoints (ADR-023): a checkpoint the auditor keeps proves, later and
even offline, that nothing at or before it in the organisation's audit chain was changed."""

from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from app.models import AuditEvent

_spec = importlib.util.spec_from_file_location(
    "verify_audit_export", Path(__file__).parent.parent / "scripts" / "verify_audit_export.py")
offline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(offline)


def _new_key() -> str:
    raw = Ed25519PrivateKey.generate().private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return base64.b64encode(raw).decode()


@pytest.fixture()
def signed(monkeypatch):
    monkeypatch.setenv("AUDIT_CHECKPOINT_SIGNING_KEY", _new_key())


@pytest.fixture()
def engaged(client, bootstrap):
    org_id, engagement_id = bootstrap(client)
    # some history in the chain: a few audited actions by the organisation
    for name in ("one", "two", "three"):
        client.post("/tasks", headers={"authorization": f"org:{org_id}"}, json={"title": f"task {name}"})
    return org_id, engagement_id


def _auditor(engagement_id):
    return {"authorization": f"auditor:{engagement_id}"}


def _issue(client, engagement_id):
    response = client.post("/audit/checkpoints", headers=_auditor(engagement_id))
    assert response.status_code == 200, response.text
    return response.json()


def _verify(client, org_id, checkpoint):
    return client.post("/audit/checkpoints/verify", headers={"authorization": f"org:{org_id}"},
                       json=checkpoint).json()


def test_a_checkpoint_verifies_and_keeps_verifying_as_the_chain_grows(client, engaged, signed):
    org_id, engagement_id = engaged
    checkpoint = _issue(client, engagement_id)
    assert checkpoint["signature"]["alg"] == "Ed25519" and checkpoint["org_id"] == org_id
    assert _verify(client, org_id, checkpoint)["verified"] is True

    client.post("/tasks", headers={"authorization": f"org:{org_id}"}, json={"title": "later"})
    later = _verify(client, org_id, checkpoint)
    assert later["verified"] is True and later["events_since"] >= 2   # the issue event + the task
    assert _issue(client, engagement_id)["previous"]["chain_seq"] == checkpoint["chain_seq"]


def test_changing_history_before_the_checkpoint_is_caught(client, engaged, signed, db):
    org_id, engagement_id = engaged
    checkpoint = _issue(client, engagement_id)
    event = db.query(AuditEvent).filter_by(chain=org_id, chain_seq=2).one()
    event.detail = {"quietly": "edited"}
    db.commit()
    result = _verify(client, org_id, checkpoint)
    assert result["verified"] is False and result["problems"]


def test_a_doctored_checkpoint_or_another_orgs_does_not_verify(client, engaged, signed, bootstrap):
    org_id, engagement_id = engaged
    checkpoint = _issue(client, engagement_id)
    doctored = {**checkpoint, "chain_seq": checkpoint["chain_seq"] - 1}
    assert "signature" in _verify(client, org_id, doctored)["problems"][0]
    other, _ = bootstrap(client)
    assert "another organisation" in _verify(client, other, checkpoint)["problems"][0]


def test_only_auditors_take_checkpoints_and_only_with_a_key(client, engaged, monkeypatch):
    org_id, engagement_id = engaged
    monkeypatch.delenv("AUDIT_CHECKPOINT_SIGNING_KEY", raising=False)
    assert client.post("/audit/checkpoints", headers=_auditor(engagement_id)).status_code == 503
    monkeypatch.setenv("AUDIT_CHECKPOINT_SIGNING_KEY", _new_key())
    assert client.post("/audit/checkpoints", headers={"authorization": f"org:{org_id}"}).status_code == 403


def test_a_rotated_key_still_verifies_old_checkpoints(client, engaged, monkeypatch):
    org_id, engagement_id = engaged
    old = _new_key()
    monkeypatch.setenv("AUDIT_CHECKPOINT_SIGNING_KEY", old)
    checkpoint = _issue(client, engagement_id)
    old_public = client.get("/audit/checkpoint-keys").json()["keys"][0]["public_key"]
    monkeypatch.setenv("AUDIT_CHECKPOINT_SIGNING_KEY", _new_key())
    assert _verify(client, org_id, checkpoint)["verified"] is False          # unknown key
    monkeypatch.setenv("AUDIT_CHECKPOINT_RETIRED_KEYS", old_public)
    assert _verify(client, org_id, checkpoint)["verified"] is True


def test_the_offline_verifier_needs_nothing_from_the_platform(client, engaged, signed, tmp_path, capsys):
    org_id, engagement_id = engaged
    checkpoint = _issue(client, engagement_id)
    public = client.get("/audit/checkpoint-keys").json()["keys"][0]["public_key"]
    export = client.get("/audit/events.ndjson", headers=_auditor(engagement_id))
    assert export.status_code == 200
    events_file, checkpoint_file = tmp_path / "events.ndjson", tmp_path / "checkpoint.json"
    events_file.write_text(export.text)
    checkpoint_file.write_text(json.dumps(checkpoint))
    assert offline.main([str(events_file), str(checkpoint_file), "--public-key", public]) == 0

    lines = export.text.splitlines()
    tampered = json.loads(lines[1])
    tampered["actor"] = "someone else"
    events_file.write_text("\n".join([lines[0], json.dumps(tampered), *lines[2:]]) + "\n")
    assert offline.main([str(events_file), str(checkpoint_file), "--public-key", public]) == 1
    assert "does not hash" in capsys.readouterr().out
