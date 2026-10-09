"""Typed-decision provenance (ADR-025): every decision the pipeline asks a model is hashed,
the hash lands in the audit chain and the OSCAL export, and the nightly report says how the
decisions held up against what people did afterwards."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import audit_log, monitor, service
from app.ai import decision
from app.ai.schemas import ExtractedField, ExtractionRun, Source
from app.models import AiRun, AuditEvent, Evidence, Organization

TYPE_ANSWER = {"POLICY": 0.9, "REPORT": 0.1}
QUOTE_ANSWER = {"YES": 0.95, "NO": 0.05}


def _process(client, bootstrap, upload, monkeypatch, content=b"an access control policy"):
    def fake_extract(text, names, method="native_text", gateway=None):
        fields = {n: ExtractedField() for n in names}
        fields["password_min_length"] = ExtractedField(
            value=12, confidence=0.9, sources=[Source(quote="Passwords must be at least 12 characters.")])
        return ExtractionRun(fields=fields, model="stub", provider="stub", status="OK")

    def fake_choose(gateway, question, state, options, **_):
        return dict(TYPE_ANSWER) if "SCAN_REPORT" in options else dict(QUOTE_ANSWER)

    monkeypatch.setattr(service, "extract_attributes", fake_extract)
    monkeypatch.setattr(service, "generate_nutshell", lambda *a, **k: "")
    monkeypatch.setattr(decision, "choose", fake_choose)
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id, content=content).json()["evidence_id"]
    return org_id, engagement_id, evidence_id


def test_each_decision_is_hashed_and_the_hash_can_be_recomputed(client, bootstrap, upload, monkeypatch, db):
    content = b"an access control policy"
    org_id, _, evidence_id = _process(client, bootstrap, upload, monkeypatch, content)
    runs = {r.operation: r for r in db.query(AiRun).filter_by(evidence_id=evidence_id)
            if r.decision_hash}
    assert set(runs) == {"artefact_type_check", "quote_support_check"}

    # Anyone holding the document can rebuild what the model was shown, and the hash.
    typed = runs["artefact_type_check"]
    evidence = db.get(Evidence, evidence_id)
    text, _ = service.read_document(evidence.filename, content)
    state = service.classify_state(evidence.original_filename, text)
    assert typed.detail["state_sha256"] == decision.digest(state)
    assert "access control" not in str(typed.detail)  # digests, never document text
    assert typed.decision_hash == decision.decision_hash(
        "artefact_type_check", "artefact_type:v1", typed.model, typed.detail, TYPE_ANSWER)

    quote = runs["quote_support_check"]
    assert quote.detail["state_sha256"]["password_min_length"] == decision.digest(service.support_state(
        "password_min_length", 12, "Passwords must be at least 12 characters."))


def test_the_hashes_are_in_the_audit_chain(client, bootstrap, upload, monkeypatch, db):
    org_id, _, evidence_id = _process(client, bootstrap, upload, monkeypatch)
    event = db.query(AuditEvent).filter_by(action="EVIDENCE_PROCESSED", entity=evidence_id).one()
    hashes = {c["operation"]: c["decision_hash"] for c in event.detail["ai_checks"]}
    stored = {r.operation: r.decision_hash for r in db.query(AiRun).filter_by(evidence_id=evidence_id)
              if r.decision_hash}
    assert hashes == stored
    assert audit_log.verify(db, audit_log.chain_of(org_id)).ok


def test_the_same_question_and_answer_hash_the_same_and_another_model_does_not():
    args = ("artefact_type_check", "artefact_type:v1")
    inputs = {"state_sha256": decision.digest("s"), "options": ["A", "B"]}
    assert decision.decision_hash(*args, "m", inputs, {"A": 1.0}) == decision.decision_hash(*args, "m", inputs, {"A": 1.0})
    assert decision.decision_hash(*args, "m", inputs, {"A": 1.0}) != decision.decision_hash(*args, "n", inputs, {"A": 1.0})
    assert decision.decision_hash(*args, "m", inputs, {"A": 1.0}) != decision.decision_hash(*args, "m", inputs, {"A": 0.9})


def test_oscal_observations_carry_the_decision_hashes(client, bootstrap, upload, monkeypatch, db):
    from test_oscal_export import validator
    org_id, _, evidence_id = _process(client, bootstrap, upload, monkeypatch)
    response = client.get("/export/oscal/assessment-results.json", params={"framework": "ISO-27001"},
                          headers={"authorization": f"org:{org_id}"})
    document = response.json()
    observations = document["assessment-results"]["results"][0]["observations"]
    props = {p["name"]: p["value"] for p in observations[0]["props"]}
    stored = {r.operation: r for r in db.query(AiRun).filter_by(evidence_id=evidence_id) if r.decision_hash}
    assert props["ai-type-check-hash"] == stored["artefact_type_check"].decision_hash
    assert props["ai-quote-check-hash"] == stored["quote_support_check"].decision_hash
    assert props.get("ai-decision-model", "") == stored["artefact_type_check"].model  # empty: no prop
    assert not list(validator().iter_errors(document))
    second = client.get("/export/oscal/assessment-results.json", params={"framework": "ISO-27001"},
                        headers={"authorization": f"org:{org_id}"})
    assert second.content == response.content  # still deterministic


def _run(db, org_id, evidence_id, output, declared, created_at, model="decider"):
    db.add(AiRun(org_id=org_id, evidence_id=evidence_id, operation="artefact_type_check", model=model,
                 validated_output=output, decision_hash="h", detail={"declared": declared},
                 created_at=created_at))


def test_calibration_scores_settled_decisions_against_what_people_did(client, bootstrap, upload, db, capsys):
    org_id, _ = bootstrap(client)
    ids = [upload(client, org_id, content=f"document {i}".encode(), name=f"doc{i}.txt").json()["evidence_id"] for i in range(3)]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    old, recent = now - timedelta(days=10), now - timedelta(days=1)
    # 1: said SCAN_REPORT, and the document was re-uploaded as a SCAN_REPORT: right.
    _run(db, org_id, ids[0], {"SCAN_REPORT": 0.98, "POLICY": 0.02}, "POLICY", recent)
    db.add(Evidence(org_id=org_id, artefact_type="SCAN_REPORT", supersedes_id=ids[0], version=2))
    # 2: said POLICY, nobody changed it in ten days: right.
    _run(db, org_id, ids[1], {"POLICY": 0.8, "REPORT": 0.2}, "POLICY", old)
    # 3: too recent to have settled, and from another model.
    _run(db, org_id, ids[2], {"REPORT": 0.7, "POLICY": 0.3}, "POLICY", recent, model="other")
    db.commit()

    rows = {r["model"]: r for r in monitor.decision_calibration(db, [org_id], now=now)}
    decider = rows["decider"]
    assert (decider["asked"], decider["settled"], decider["accuracy"], decider["flagged"]) == (2, 2, 1.0, 1)
    assert decider["brier"] == (decision.brier({"SCAN_REPORT": 0.98, "POLICY": 0.02}, "SCAN_REPORT")
                                + decision.brier({"POLICY": 0.8, "REPORT": 0.2}, "POLICY")) / 2
    assert rows["other"]["settled"] == 0 and rows["other"]["accuracy"] is None

    monitor._report_decision_calibration(db, [db.get(Organization, org_id)])
    out = capsys.readouterr().out
    assert "artefact_type_check decider: 2 asked, 1 flagged, 2 settled, accuracy 100%" in out
    assert org_id not in out  # counts only, never which organisation
