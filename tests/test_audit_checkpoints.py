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

from datetime import timedelta

from app import checkpoints
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


def _deploy_switchover_row(db, org_id):
    """A row as an instance still running the previous code writes it, after the genesis."""
    from datetime import datetime, timezone
    row = AuditEvent(org_id=org_id, actor="old-instance", action="TASK_CREATED", entity_type="task",
                     entity="t", detail={"n": 1}, reason="", seq=99, prev_hash="", entry_hash="legacy",
                     at=datetime.now(timezone.utc).replace(tzinfo=None))
    db.add(row)
    db.commit()
    return row


def test_rows_written_outside_the_chain_during_a_deploy_are_covered(client, engaged, signed, db, tmp_path,
                                                                    monkeypatch):
    """Review fix: a row the previous code wrote after genesis is outside the hash chain, so the
    checkpoint covers it by digest; changing it afterwards is caught, online and offline."""
    org_id, engagement_id = engaged
    row = _deploy_switchover_row(db, org_id)
    monkeypatch.setattr(checkpoints, "SETTLE", timedelta(0))  # the switchover has settled
    checkpoint = _issue(client, engagement_id)
    assert checkpoint["unchained"]["count"] == 1
    assert _verify(client, org_id, checkpoint)["verified"] is True
    public = client.get("/audit/checkpoint-keys").json()["keys"][0]["public_key"]

    row.detail = {"n": 2}
    db.commit()
    assert "outside the chain" in _verify(client, org_id, checkpoint)["problems"][0]
    events_file, checkpoint_file = tmp_path / "e.ndjson", tmp_path / "c.json"
    events_file.write_text(client.get("/audit/events.ndjson", headers=_auditor(engagement_id)).text)
    checkpoint_file.write_text(json.dumps(checkpoint))
    assert offline.main([str(events_file), str(checkpoint_file), "--public-key", public]) == 1


@pytest.mark.parametrize("junk", [
    {"format": "grc-audit-checkpoint/1", "signature": "bad"},
    {"format": "grc-audit-checkpoint/1", "signature": {}, "chain_seq": "7"},
    {"anything": True},
])
def test_a_malformed_checkpoint_fails_verification_instead_of_erroring(client, engaged, junk):
    org_id, _ = engaged
    response = client.post("/audit/checkpoints/verify", headers={"authorization": f"org:{org_id}"}, json=junk)
    assert response.status_code == 200 and response.json()["verified"] is False


def test_no_checkpoint_while_a_deploy_is_still_writing_outside_the_chain(client, engaged, signed, db):
    """Review fix: rows the previous code writes carry no lock, so a checkpoint is refused until
    they have settled; none can then land behind its signed cutoff."""
    org_id, engagement_id = engaged
    _deploy_switchover_row(db, org_id)
    response = client.post("/audit/checkpoints", headers=_auditor(engagement_id))
    assert response.status_code == 409 and "deploy" in response.json()["detail"]


def test_a_version_1_checkpoint_still_verifies(client, engaged, monkeypatch, tmp_path):
    """Review fix: a checkpoint an auditor already holds keeps verifying after the format moved on."""
    org_id, engagement_id = engaged
    key = _new_key()
    monkeypatch.setenv("AUDIT_CHECKPOINT_SIGNING_KEY", key)
    current = _issue(client, engagement_id)
    body = {k: v for k, v in current.items() if k not in ("signature", "unchained")}
    body["format"] = "grc-audit-checkpoint/1"
    private = Ed25519PrivateKey.from_private_bytes(base64.b64decode(key))
    v1 = {**body, "signature": {**current["signature"],
                                "value": base64.b64encode(private.sign(checkpoints.canonical(body))).decode()}}
    assert _verify(client, org_id, v1)["verified"] is True

    public = client.get("/audit/checkpoint-keys").json()["keys"][0]["public_key"]
    events_file, checkpoint_file = tmp_path / "e.ndjson", tmp_path / "c.json"
    events_file.write_text(client.get("/audit/events.ndjson", headers=_auditor(engagement_id)).text)
    checkpoint_file.write_text(json.dumps(v1))
    assert offline.main([str(events_file), str(checkpoint_file), "--public-key", public]) == 0
