"""Questionnaire answers (ADR-040): the status comes from verdicts, the model only words it."""

from __future__ import annotations

import json

import pytest

from app import ingest
from app.routers import questionnaire as q
from test_demo_collectors import _sync

AUTH = lambda org: {"authorization": f"org:{org}"}  # noqa: E731


class Gateway:
    model = "stub"

    def __init__(self, reply=None, available=True):
        self.reply, self._available = reply, available

    def available(self):
        return self._available

    def complete_json(self, system, user):
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def _first_org(client):
    from sqlalchemy.orm import Session
    from app import db as db_module
    from app.models import Organization

    with Session(db_module.engine) as s:
        return s.query(Organization).first().id


def _ask(client, org, text):
    return client.post("/questionnaire/answer", json={"question": text}, headers=AUTH(org))


def test_status_is_decided_from_verdicts_alone():
    assert q.status_of([]) == "NOT_EVIDENCED"
    assert q.status_of(["PASS", "PASS"]) == "YES"
    assert q.status_of(["PASS", "PARTIAL"]) == "PARTIAL"
    assert q.status_of(["PARTIAL"]) == "PARTIAL"
    assert q.status_of(["PASS", "FAIL"]) == "NO"
    assert q.status_of(["NO_EVIDENCE"]) == "NOT_EVIDENCED"


def test_matching_uses_the_controls_own_words_and_a_few_synonyms():
    controls = [
        {"framework": "PCI-DSS", "clause": "8.4.3", "title": "MFA for remote network access", "text": "Multi-factor authentication is implemented for remote access."},
        {"framework": "ISO-27001", "clause": "A.8.15", "title": "Logging", "text": "Logs that record activities are produced and stored."},
        {"framework": "SOC-2", "clause": "CC6.7", "title": "Encryption", "text": "Data is encrypted at rest and in transit."},
    ]
    assert [c["clause"] for c in q.match("Do you enforce MFA for remote access?", controls)][0] == "8.4.3"
    assert [c["clause"] for c in q.match("Do you keep audit logs?", controls)] == ["A.8.15"]
    assert q.match("Do you have a pet policy for the office dog?", controls) == []
    assert q.match("Is the weather nice?", controls) == []


@pytest.fixture()
def synced(client, bootstrap, monkeypatch):
    _sync(client, bootstrap, monkeypatch, "m365")   # passing: MFA
    org = _first_org(client)
    return org


def test_a_passing_control_answers_yes_with_the_rules_sentence_when_no_model(client, synced, monkeypatch):
    monkeypatch.setattr(ingest, "_tool_gateway", lambda: Gateway(available=False))
    body = _ask(client, synced, "Do you require multi-factor authentication for remote access?").json()
    assert body["status"] == "YES" and body["wording"] == "rules"
    assert {(c["framework"], c["clause"]) for c in body["controls"]} >= {("PCI-DSS", "8.4.3")}
    assert body["answer"].startswith("Yes.") and "PCI-DSS 8.4.3" in body["answer"]


def test_an_unrelated_question_is_not_evidenced_and_cites_nothing(client, synced, monkeypatch):
    monkeypatch.setattr(ingest, "_tool_gateway", lambda: Gateway(json.dumps({"answer": "Yes, absolutely."})))
    body = _ask(client, synced, "Do you allow pets in the office?").json()
    assert body["status"] == "NOT_EVIDENCED" and body["controls"] == [] and body["wording"] == "rules"
    assert not body["answer"].lower().startswith("yes")  # the model was never asked, so it could not overclaim


def test_the_model_may_word_a_supported_answer(client, synced, monkeypatch):
    reply = json.dumps({"answer": "Yes. Multi-factor authentication is required for remote access."})
    monkeypatch.setattr(ingest, "_tool_gateway", lambda: Gateway(reply))
    body = _ask(client, synced, "Do you require multi-factor authentication for remote access?").json()
    assert body["wording"] == "model" and body["answer"].startswith("Yes. Multi-factor")


@pytest.mark.parametrize("reply", ["not json at all", json.dumps({"answer": ""}), RuntimeError("model down")])
def test_a_broken_model_falls_back_to_the_rules_sentence(client, synced, monkeypatch, reply):
    monkeypatch.setattr(ingest, "_tool_gateway", lambda: Gateway(reply))
    body = _ask(client, synced, "Do you require multi-factor authentication for remote access?").json()
    assert body["wording"] == "rules" and body["status"] == "YES"


def test_a_model_that_contradicts_the_status_is_discarded(client, bootstrap, monkeypatch):
    _sync(client, bootstrap, monkeypatch, "aws")  # access logging is a gap: PARTIAL, never YES
    org = _first_org(client)
    reply = json.dumps({"answer": "Yes, we log everything perfectly."})
    monkeypatch.setattr(ingest, "_tool_gateway", lambda: Gateway(reply))
    body = _ask(client, org, "Do you keep audit logs?").json()
    assert body["status"] == "PARTIAL" and body["wording"] == "rules" and not body["answer"].lower().startswith("yes")


def test_it_needs_a_signed_in_caller_and_audits_only_counts(client, synced, monkeypatch, db):
    from app.models import AuditEvent

    monkeypatch.setattr(ingest, "_tool_gateway", lambda: Gateway(available=False))
    assert client.post("/questionnaire/answer", json={"question": "Do you use MFA?"}).status_code in (401, 422)
    _ask(client, synced, "Do you require multi-factor authentication for our confidential customer Initech?")
    event = db.query(AuditEvent).filter_by(action="QUESTIONNAIRE_ANSWERED").one()
    assert "Initech" not in json.dumps(event.detail) and event.detail["status"] == "YES"
