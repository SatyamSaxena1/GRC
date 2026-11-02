"""The verdict register (ADR-029): history is added to, never rewritten."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app import db as db_module, verdict_register
from app.models import AuditEvent, EvidenceControlLink, GapException, VerdictRecord

ROOT = Path(__file__).resolve().parent.parent
GOOD = "the auditee supplied a corrected access review covering all production systems"


def _load(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def locked(client, bootstrap, upload):
    """A control locked COMPLIANT by an auditor: (client, org_id, engagement_id, link_id, headers)."""
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    with Session(db_module.engine) as s:
        link_id = s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id).first().id
    headers = {"authorization": f"auditor:{engagement_id}"}
    assert client.post(f"/audit/links/{link_id}/lock", headers=headers,
                       json={"verdict": "COMPLIANT", "reason": "reviewed"}).status_code == 200
    return client, org_id, engagement_id, link_id, headers


def records(link_id):
    with Session(db_module.engine) as s:
        return s.query(VerdictRecord).filter_by(link_id=link_id).order_by(VerdictRecord.seq).all()


def test_supersession_builds_one_chain_and_leaves_the_original_untouched(locked):
    client, _, _, link_id, headers = locked
    original = records(link_id)[0]
    snapshot = {c.name: getattr(original, c.name) for c in VerdictRecord.__table__.columns}

    resp = client.post(f"/audit/links/{link_id}/supersede", headers=headers,
                       json={"verdict": "NON_COMPLIANT", "reason_code": "NEW_EVIDENCE", "reasoning": GOOD})
    assert resp.status_code == 200 and resp.json()["locked"] is False

    rows = records(link_id)
    assert [(r.seq, r.kind, r.verdict) for r in rows] == [
        (1, "DECISION", "COMPLIANT"), (2, "REOPENED", None), (3, "DECISION", "NON_COMPLIANT")]
    assert [r.supersedes_id for r in rows] == [None, rows[0].id, rows[1].id]
    assert {c.name: getattr(rows[0], c.name) for c in VerdictRecord.__table__.columns} == snapshot
    assert rows[2].reason_code == "NEW_EVIDENCE" and rows[2].reasoning == GOOD

    view = client.get(f"/audit/links/{link_id}/register", headers=headers).json()
    assert view["original_verdict"] == "COMPLIANT"
    assert view["current"]["verdict"] == "NON_COMPLIANT" and len(view["entries"]) == 3


def test_a_closing_replacement_relocks_and_the_chain_still_verifies(locked):
    client, _, _, link_id, headers = locked
    client.post(f"/audit/links/{link_id}/supersede", headers=headers,
                json={"verdict": "PASS", "reason_code": "ERROR_IN_ORIGINAL", "reasoning": GOOD})
    with Session(db_module.engine) as s:
        assert s.get(EvidenceControlLink, link_id).locked
        assert audit_ok(s)


def audit_ok(session):
    from app.audit_log import verify_chain
    return verify_chain(session)


@pytest.mark.parametrize("reasoning", ["", "ok", "see above", "n/a", "aaaaaaaaaaaaaaaaaaaa", "two words"])
def test_boilerplate_or_missing_reasoning_is_refused_and_nothing_changes(locked, reasoning):
    client, _, _, link_id, headers = locked
    for path, body in (("supersede", {"verdict": "FAIL", "reason_code": "OTHER", "reasoning": reasoning}),
                       ("unlock", {"reason": reasoning, "reason_code": "OTHER"})):
        assert client.post(f"/audit/links/{link_id}/{path}", headers=headers, json=body).status_code == 422
    assert len(records(link_id)) == 1
    with Session(db_module.engine) as s:
        assert s.get(EvidenceControlLink, link_id).locked


def test_an_unknown_reason_code_is_refused(locked):
    client, _, _, link_id, headers = locked
    assert client.post(f"/audit/links/{link_id}/supersede", headers=headers,
                       json={"verdict": "FAIL", "reason_code": "BECAUSE", "reasoning": GOOD}).status_code == 422


def test_unlock_no_longer_overwrites_and_every_reopening_keeps_its_reason(locked):
    client, _, _, link_id, headers = locked
    reasons = ["the first corrected policy version arrived from the auditee",
               "a second corrected policy version changed the review cadence"]
    for reason in reasons:
        assert client.post(f"/audit/links/{link_id}/unlock", headers=headers,
                           json={"reason": reason, "reason_code": "NEW_EVIDENCE"}).status_code == 200
        client.post(f"/audit/links/{link_id}/lock", headers=headers, json={"verdict": "COMPLIANT"})
    assert [r.reasoning for r in records(link_id) if r.kind == "REOPENED"] == reasons
    with Session(db_module.engine) as s:
        assert s.get(EvidenceControlLink, link_id).unlock_reason is None  # the old overwrite is gone


def test_a_replacement_needs_a_locked_control(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    with Session(db_module.engine) as s:
        link_id = s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id).first().id
    resp = client.post(f"/audit/links/{link_id}/supersede", headers={"authorization": f"auditor:{engagement_id}"},
                       json={"verdict": "FAIL", "reason_code": "OTHER", "reasoning": GOOD})
    assert resp.status_code == 409


def test_whoever_asked_for_an_exception_cannot_replace_the_verdict(locked):
    client, org_id, engagement_id, link_id, headers = locked
    with Session(db_module.engine) as s:
        link = s.get(EvidenceControlLink, link_id)
        s.add(GapException(org_id=org_id, framework=link.framework, clause=link.clause, attribute="x",
                           gap_kind="MISSING", rule_hash="r", value_fingerprint="v", justification="j",
                           requested_by=f"auditor:{engagement_id}", expires_at=datetime(2099, 1, 1)))
        s.commit()
    resp = client.post(f"/audit/links/{link_id}/supersede", headers=headers,
                       json={"verdict": "FAIL", "reason_code": "OTHER", "reasoning": GOOD})
    assert resp.status_code == 403 and len(records(link_id)) == 1


def test_the_uploader_still_cannot_supersede(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    with Session(db_module.engine) as s:
        link_id = s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id).first().id
    headers = {"authorization": f"auditor:{engagement_id}"}
    client.post(f"/audit/links/{link_id}/lock", headers=headers, json={"verdict": "COMPLIANT"})
    from app.models import Evidence
    with Session(db_module.engine) as s:
        s.get(Evidence, evidence_id).uploaded_by = f"auditor:{engagement_id}"
        s.commit()
    assert client.post(f"/audit/links/{link_id}/supersede", headers=headers,
                       json={"verdict": "FAIL", "reason_code": "OTHER", "reasoning": GOOD}).status_code == 403


def test_a_rule_change_between_two_verdicts_is_visible(locked):
    client, _, _, link_id, headers = locked
    with Session(db_module.engine) as s:
        s.get(EvidenceControlLink, link_id).rule_hash = "rules-v2"
        s.commit()
    client.post(f"/audit/links/{link_id}/supersede", headers=headers,
                json={"verdict": "FAIL", "reason_code": "RULES_CHANGED", "reasoning": GOOD})
    entries = client.get(f"/audit/links/{link_id}/register", headers=headers).json()["entries"]
    assert [e["rules_changed_since_previous"] for e in entries] == [False, True, False]
    assert entries[0]["rule_hash"] != entries[2]["rule_hash"] == "rules-v2"


def test_the_export_verifies_against_the_chain_and_tampering_is_caught(locked):
    client, _, _, link_id, headers = locked
    client.post(f"/audit/links/{link_id}/supersede", headers=headers,
                json={"verdict": "NON_COMPLIANT", "reason_code": "NEW_EVIDENCE", "reasoning": GOOD})
    register = client.get("/audit/register.json", headers=headers).json()
    events = [json.loads(line) for line in client.get("/audit/events.ndjson", headers=headers).text.splitlines()]
    verifier = _load("scripts/verify_audit_export.py", "verify_audit_export")

    assert verifier.verify_chain(events) == [] and verifier.verify_register(events, register) == []

    altered = json.loads(json.dumps(register))
    altered["records"][0]["verdict"] = "FAIL"
    assert any("does not hash" in p for p in verifier.verify_register(events, altered))
    dropped = json.loads(json.dumps(register))
    del dropped["records"][1]
    assert any("supersession chain" in p for p in verifier.verify_register(events, dropped))
    forged_events = json.loads(json.dumps(events))
    for e in forged_events:
        if e["action"] == "VERDICT_REGISTERED":
            e["detail"]["record_hash"] = "0" * 64
    assert any("committed to" in p for p in verifier.verify_register(forged_events, register))


def test_only_an_auditor_can_export_the_register(locked):
    client, org_id, *_ = locked
    assert client.get("/audit/register.json", headers={"authorization": f"org:{org_id}"}).status_code == 403


def test_every_step_is_in_the_audit_chain_with_its_hash(locked):
    _, _, _, link_id, _ = locked
    with Session(db_module.engine) as s:
        events = s.query(AuditEvent).filter_by(action="VERDICT_REGISTERED").all()
        assert {e.detail["record_hash"] for e in events} == {r.record_hash for r in records(link_id)}


def test_migration_turns_the_surviving_unlock_reason_into_the_first_register_entries(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    migration = _load("alembic/versions/a9b0c1d2e3f4_verdict_register.py", "verdict_register_migration")
    with Session(db_module.engine) as s:
        link = s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id).first()
        link_id = link.id
        # the old shape: reopened once, only the last reason survives, no register rows
        link.auditor_verdict, link.verdict = "COMPLIANT", "COMPLIANT"
        link.unlocked_at, link.unlock_reason = datetime(2026, 5, 1, 9, 30), "the auditee supplied corrected evidence"
        other = s.query(EvidenceControlLink).filter(EvidenceControlLink.id != link_id).first()
        untouched_id = other.id
        s.commit()

    with db_module.engine.begin() as conn:
        migration._backfill(conn)

    rows = records(link_id)
    assert [(r.seq, r.kind, r.verdict, r.origin) for r in rows] == [
        (1, "DECISION", "COMPLIANT", "MIGRATED"), (2, "REOPENED", None, "MIGRATED")]
    assert rows[1].reasoning == "the auditee supplied corrected evidence" and rows[1].supersedes_id == rows[0].id
    assert "before the verdict register existed" in rows[0].reasoning
    assert not records(untouched_id)  # a control with no verdict history gets no invented one
    for r in rows:  # the migration's hash is the app's hash
        fields = {k: getattr(r, k) for k in verdict_register.HASHED_FIELDS}
        assert r.record_hash == verdict_register.record_hash(fields)


def test_a_migrated_history_can_be_continued(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    migration = _load("alembic/versions/a9b0c1d2e3f4_verdict_register.py", "verdict_register_migration")
    with Session(db_module.engine) as s:
        link = s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id).first()
        link_id = link.id
        link.auditor_verdict, link.verdict = "COMPLIANT", "COMPLIANT"
        link.locked_by_engagement_id, link.locked_at = engagement_id, datetime(2026, 5, 1)
        s.commit()
    with db_module.engine.begin() as conn:
        migration._backfill(conn)
    headers = {"authorization": f"auditor:{engagement_id}"}
    assert client.post(f"/audit/links/{link_id}/supersede", headers=headers,
                       json={"verdict": "FAIL", "reason_code": "OTHER", "reasoning": GOOD}).status_code == 200
    assert [r.seq for r in records(link_id)] == [1, 2, 3]
