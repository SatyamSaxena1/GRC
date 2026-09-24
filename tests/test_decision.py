"""Jev-style decisions (app/ai/decision.py) and the two places they suggest
something: the upload form's artefact type and a new gap task's priority.
Suggestions only — the task queue order itself stays deterministic."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from app import service
from app.ai import decision
from app.ai.schemas import ExtractedField, ExtractionRun

OPTIONS = {"POLICY": "a policy", "SCAN_REPORT": "a scan", "REPORT": "a report"}


class FakeGateway:
    model = "fake"
    provider = "fake"

    def __init__(self, logprobs=None, up=True, boom=False):
        self.logprobs, self.up, self.boom = logprobs or {}, up, boom

    def available(self):
        return self.up

    def next_token_logprobs(self, system, user, top=20):
        if self.boom:
            raise RuntimeError("down")
        return self.logprobs


def test_choose_normalises_letter_probabilities_and_ignores_other_tokens():
    gateway = FakeGateway({"B": math.log(0.6), " b": math.log(0.1), "A": math.log(0.2),
                           "The": math.log(0.1)})
    probs = decision.choose(gateway, "q", "state", OPTIONS)
    assert set(probs) == set(OPTIONS)
    assert math.isclose(sum(probs.values()), 1.0)
    assert math.isclose(probs["SCAN_REPORT"], 0.7 / 0.9)  # "B" and " b" are one answer
    assert probs["REPORT"] == 0.0
    assert decision.top(probs) == "SCAN_REPORT"
    assert decision.top(probs, threshold=0.9) is None


def test_choose_degrades_to_empty():
    assert decision.choose(FakeGateway(up=False), "q", "s", OPTIONS) == {}
    assert decision.choose(FakeGateway(boom=True), "q", "s", OPTIONS) == {}
    assert decision.choose(FakeGateway({"Hello": -0.1}), "q", "s", OPTIONS) == {}
    assert decision.top({}) is None


def _suggest(client, headers, content=b"Access control policy. Approved by the CISO."):
    return client.post("/evidence/suggest-type", headers=headers,
                       files={"file": ("policy.txt", content, "text/plain")})


def test_suggest_type_respects_threshold(client, bootstrap, monkeypatch):
    org_id, _ = bootstrap(client)
    headers = {"authorization": f"org:{org_id}"}

    monkeypatch.setattr(decision, "choose", lambda *a, **k: {"POLICY": 0.9, "REPORT": 0.1})
    body = _suggest(client, headers).json()
    assert body["suggested"] == "POLICY"
    assert body["probabilities"]["POLICY"] == 0.9

    monkeypatch.setattr(decision, "choose", lambda *a, **k: {"POLICY": 0.5, "REPORT": 0.5})
    assert _suggest(client, headers).json()["suggested"] is None


def test_suggest_type_stores_nothing_and_rejects_read_only(client, bootstrap, monkeypatch):
    org_id, engagement_id = bootstrap(client)
    monkeypatch.setattr(decision, "choose", lambda *a, **k: {"POLICY": 1.0})

    assert _suggest(client, {"authorization": f"auditor:{engagement_id}"}).status_code == 403
    assert _suggest(client, {"authorization": f"org:{org_id}"}).status_code == 200
    assert client.get("/evidence", headers={"authorization": f"org:{org_id}"}).json() == []


def _run_gap_pipeline(client, bootstrap, upload, monkeypatch, choose):
    def fake_extract(text, names, method="native_text", gateway=None):
        # Nothing extracted -> every requirement opens gaps, and so gap tasks.
        return ExtractionRun(fields={n: ExtractedField() for n in names},
                             model="stub", provider="stub", status="OK")

    monkeypatch.setattr(service, "extract_attributes", fake_extract)
    monkeypatch.setattr(service, "generate_nutshell", lambda *a, **k: "")
    monkeypatch.setattr(decision, "choose", choose)
    org_id, _ = bootstrap(client)
    upload(client, org_id)
    tasks = client.get("/tasks", headers={"authorization": f"org:{org_id}"}).json()
    return [t for t in tasks if not t["is_manual"]]


def test_gap_task_takes_a_confident_suggested_priority(client, bootstrap, upload, monkeypatch):
    tasks = _run_gap_pipeline(client, bootstrap, upload, monkeypatch,
                              lambda *a, **k: {"LOW": 0.0, "MEDIUM": 0.05, "HIGH": 0.9, "CRITICAL": 0.05})
    assert tasks and all(t["priority"] == "HIGH" for t in tasks)


def test_gap_task_ignores_an_unconfident_suggestion(client, bootstrap, upload, monkeypatch):
    # What the real 7B model returned for every gap tried: HIGH, but only ~0.6.
    tasks = _run_gap_pipeline(client, bootstrap, upload, monkeypatch,
                              lambda *a, **k: {"LOW": 0.02, "MEDIUM": 0.08, "HIGH": 0.6, "CRITICAL": 0.3})
    assert tasks and all(t["priority"] == "MEDIUM" for t in tasks)


def test_gap_task_stays_medium_without_a_suggestion(client, bootstrap, upload, monkeypatch):
    tasks = _run_gap_pipeline(client, bootstrap, upload, monkeypatch, lambda *a, **k: {})
    assert tasks and all(t["priority"] == "MEDIUM" for t in tasks)


def test_task_queue_puts_deadlines_before_priority(client, bootstrap):
    org_id, _ = bootstrap(client)
    headers = {"authorization": f"org:{org_id}"}
    now = datetime.now(timezone.utc)

    def make(title, priority, due=None):
        client.post("/tasks", headers=headers, json={
            "title": title, "priority": priority,
            "due_at": due.isoformat() if due else None,
        })

    make("critical, no deadline", "CRITICAL")
    make("low, no deadline", "LOW")
    make("low, due next week", "LOW", now + timedelta(days=7))
    make("low, due tomorrow", "LOW", now + timedelta(days=1))
    make("low, overdue", "LOW", now - timedelta(days=1))

    titles = [t["title"] for t in client.get("/tasks", headers=headers).json()]
    assert titles == ["low, overdue", "low, due tomorrow", "low, due next week",
                      "critical, no deadline", "low, no deadline"]
