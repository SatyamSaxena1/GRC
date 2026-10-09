"""Jev-style decisions (app/ai/decision.py) and the two places they suggest
something: the upload form's artefact type and a new gap task's priority.
Suggestions only — the task queue order itself stays deterministic."""

from __future__ import annotations

import math

import pytest
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


class PositionBiasedGateway(FakeGateway):
    """Always answers "A" — whichever option is listed first — and records the
    listing it was shown, so the rotations can be checked."""
    def __init__(self):
        super().__init__({"A": math.log(0.9), "B": math.log(0.05), "C": math.log(0.05)})
        self.prompts = []

    def next_token_logprobs(self, system, user, top=20):
        self.prompts.append(user)
        return self.logprobs


def test_order_averaging_cancels_position_bias():
    one = decision.choose(PositionBiasedGateway(), "q", "s", OPTIONS)
    assert decision.top(one) == "POLICY" and one["POLICY"] > 0.8  # bias looks like confidence

    gateway = PositionBiasedGateway()
    averaged = decision.choose(gateway, "q", "s", OPTIONS, orders=3)
    assert len(gateway.prompts) == 3
    firsts = {p.split("Options:\n")[1].split("\n")[0].split(": ")[0][3:] for p in gateway.prompts}
    assert firsts == set(OPTIONS)  # every option led once
    assert averaged == {}  # each order put a different option on top: no answer at all

    tops = [decision.top(p) for p in decision.passes(PositionBiasedGateway(), "q", "s", OPTIONS, orders=3)]
    assert sorted(tops) == sorted(OPTIONS) and not decision.stable(
        decision.passes(PositionBiasedGateway(), "q", "s", OPTIONS, orders=3))


def test_an_answer_that_holds_in_every_order_is_averaged():
    """The measured PCI case: SCAN_REPORT on top in every order, at 0.98 and at 0.71."""
    class Steady(FakeGateway):
        def next_token_logprobs(self, system, user, top=20):
            listing = user.split("Options:\n")[1].splitlines()
            letter = next(line[0] for line in listing if ") SCAN_REPORT:" in line)
            self.calls = getattr(self, "calls", 0) + 1
            share = 0.98 if self.calls == 1 else 0.71
            rest = (1 - share) / 2
            return {l: math.log(share if l == letter else rest) for l in "ABC"}

    averaged = decision.choose(Steady(), "q", "s", OPTIONS, orders=3)
    assert decision.top(averaged) == "SCAN_REPORT"
    assert math.isclose(averaged["SCAN_REPORT"], (0.98 + 0.71 + 0.71) / 3)


def test_order_averaging_fails_whole_on_a_failed_pass():
    class FailsSecond(FakeGateway):
        calls = 0

        def next_token_logprobs(self, system, user, top=20):
            self.calls += 1
            return {} if self.calls == 2 else {"A": 0.0}

    assert decision.choose(FailsSecond(), "q", "s", OPTIONS, orders=3) == {}


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


def test_gap_tasks_are_medium_and_the_model_is_not_asked_for_priority(
        client, bootstrap, upload, monkeypatch):
    def fake_extract(text, names, method="native_text", gateway=None):
        # Nothing extracted -> every requirement opens gaps, and so gap tasks.
        return ExtractionRun(fields={n: ExtractedField() for n in names},
                             model="stub", provider="stub", status="OK")

    asked = []
    monkeypatch.setattr(service, "extract_attributes", fake_extract)
    monkeypatch.setattr(service, "generate_nutshell", lambda *a, **k: "")
    monkeypatch.setattr(decision, "choose", lambda g, q, s, options, **_: asked.append(set(options)) or {})
    org_id, _ = bootstrap(client)
    upload(client, org_id)
    tasks = [t for t in client.get("/tasks", headers={"authorization": f"org:{org_id}"}).json()
             if not t["is_manual"]]
    assert tasks and all(t["priority"] == "MEDIUM" for t in tasks)
    assert not any("CRITICAL" in options for options in asked)  # only the type check ran


def _status_after_upload(client, bootstrap, upload, monkeypatch, type_probs):
    """Upload a POLICY with extraction working; the type check sees `type_probs`,
    the (unrelated) gap-task priority check sees nothing."""
    def fake_extract(text, names, method="native_text", gateway=None):
        return ExtractionRun(fields={n: ExtractedField() for n in names},
                             model="stub", provider="stub", status="OK")

    def fake_choose(gateway, question, state, options, **_):
        return type_probs if "SCAN_REPORT" in options else {}

    monkeypatch.setattr(service, "extract_attributes", fake_extract)
    monkeypatch.setattr(service, "generate_nutshell", lambda *a, **k: "")
    monkeypatch.setattr(decision, "choose", fake_choose)
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    return client.get(f"/evidence/{evidence_id}/status",
                      headers={"authorization": f"org:{org_id}"}).json()


def test_confident_type_mismatch_needs_review(client, bootstrap, upload, monkeypatch):
    status = _status_after_upload(client, bootstrap, upload, monkeypatch,
                                  {"SCAN_REPORT": 0.95, "POLICY": 0.01, "REPORT": 0.04})
    assert status["status"] == "NEEDS_REVIEW"
    assert "uploaded as POLICY" in status["detail"] and "SCAN_REPORT" in status["detail"]


def test_a_scan_that_partly_reads_like_a_certificate_is_still_caught(client, bootstrap, upload, monkeypatch):
    """The measured qwen2.5vl:7b distribution for a vendor scan attestation filed as a policy:
    SCAN_REPORT 0.69, CERTIFICATE 0.31, POLICY ~0. The old 0.8 threshold waved it through."""
    status = _status_after_upload(client, bootstrap, upload, monkeypatch,
                                  {"SCAN_REPORT": 0.685, "CERTIFICATE": 0.313, "POLICY": 0.0001, "REPORT": 0.0019})
    assert status["status"] == "NEEDS_REVIEW"
    assert "uploaded as POLICY" in status["detail"] and "SCAN_REPORT" in status["detail"]


def test_a_document_that_fits_no_type_is_not_flagged(client, bootstrap, upload, monkeypatch):
    """Measured: an invoice (no such artefact type) tops out at REPORT 0.43. Unsure is not 'wrong'."""
    status = _status_after_upload(client, bootstrap, upload, monkeypatch,
                                  {"REPORT": 0.431, "SCREENSHOT": 0.277, "POLICY": 0.03, "CERTIFICATE": 0.2})
    assert status["status"] != "NEEDS_REVIEW" or "uploaded as" not in status["detail"]


def test_near_neighbour_or_plausible_type_is_not_flagged(client, bootstrap, upload, monkeypatch):
    # AI_POLICY vs POLICY: confident top, but the declared type keeps real weight.
    status = _status_after_upload(client, bootstrap, upload, monkeypatch,
                                  {"AI_POLICY": 0.85, "POLICY": 0.15})
    assert status["status"] == "READY"
    status = _status_after_upload(client, bootstrap, upload, monkeypatch, {})  # no model
    assert status["status"] == "READY"


def _status_with_quote_check(client, bootstrap, upload, monkeypatch, support):
    """password_min_length=8 with a cited quote; the yes/no check answers `support`."""
    from app.ai.schemas import Source
    asked = []

    def fake_extract(text, names, method="native_text", gateway=None):
        fields = {n: ExtractedField() for n in names}
        fields["password_min_length"] = ExtractedField(
            value=8, confidence=0.9, sources=[Source(quote="Passwords must be at least 12 characters.")])
        return ExtractionRun(fields=fields, model="stub", provider="stub", status="OK")

    def fake_choose(gateway, question, state, options, **_):
        if "YES" in options:
            asked.append(state)
            return support
        return {}

    monkeypatch.setattr(service, "extract_attributes", fake_extract)
    monkeypatch.setattr(service, "generate_nutshell", lambda *a, **k: "")
    monkeypatch.setattr(decision, "choose", fake_choose)
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    status = client.get(f"/evidence/{evidence_id}/status",
                        headers={"authorization": f"org:{org_id}"}).json()
    return status, asked


def test_value_its_quote_does_not_state_needs_review(client, bootstrap, upload, monkeypatch):
    status, asked = _status_with_quote_check(client, bootstrap, upload, monkeypatch,
                                             {"YES": 0.05, "NO": 0.95})
    assert len(asked) == 1  # only the one field that has both a value and a quote
    assert "Value: 8" in asked[0] and "at least 12 characters" in asked[0]
    assert status["status"] == "NEEDS_REVIEW" and "password_min_length" in status["detail"]


def test_supported_value_is_not_flagged(client, bootstrap, upload, monkeypatch):
    status, _ = _status_with_quote_check(client, bootstrap, upload, monkeypatch,
                                         {"YES": 0.97, "NO": 0.03})
    assert status["status"] == "READY"


def test_suggest_rights_request_kind(client, bootstrap, monkeypatch):
    org_id, engagement_id = bootstrap(client)
    headers = {"authorization": f"org:{org_id}"}
    say = lambda details, h=headers: client.post("/rights-requests/suggest-kind",
                                                 headers=h, json={"details": details})

    monkeypatch.setattr(decision, "choose", lambda *a, **k: {"ERASURE": 0.9, "ACCESS": 0.1})
    assert say("please delete my account and all my data").json()["suggested"] == "ERASURE"
    monkeypatch.setattr(decision, "choose", lambda *a, **k: {"ERASURE": 0.5, "GRIEVANCE": 0.5})
    assert say("unhappy").json()["suggested"] is None
    assert say("   ").json() == {"probabilities": {}, "suggested": None}
    monkeypatch.setattr(decision, "choose", lambda *a, **k: {"NOT_A_REQUEST": 0.95, "GRIEVANCE": 0.05})
    body = say("hello, is this the right email?").json()
    assert body["suggested"] is None and "NOT_A_REQUEST" not in body["probabilities"]
    assert say("x", {"authorization": f"auditor:{engagement_id}"}).status_code == 403


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


def test_the_quote_check_tells_the_model_a_normalised_value_counts_as_stated():
    """Pass -> true is a *normalisation*, not a disagreement. qwen2.5vl:7b answered NO at 0.95+ without
    this sentence, sending every scan report with a pass/fail status to review on a correct fact."""
    from app.service import SUPPORT_QUESTION
    for needle in ("normalised", "'Pass'", "2026-06-18", "different, or says nothing"):
        assert needle in SUPPORT_QUESTION


def test_without_a_decision_model_the_extraction_gateway_decides(monkeypatch):
    from app.ai import provider
    monkeypatch.delenv("LLM_DECISION_MODEL", raising=False)
    extraction = FakeGateway()
    assert provider.decision_gateway(extraction) is extraction


def test_a_decision_model_answers_with_the_extraction_model_behind_it(monkeypatch):
    """ADR-025: a Jev-class model for the typed decisions; the extraction gateway stays
    behind it so a down decision server does not switch the wrong-document guard off."""
    from app.ai import provider
    from app.ai.failover import FailoverGateway
    monkeypatch.setenv("LLM_DECISION_MODEL", "h2o-lightning-4b")
    monkeypatch.setenv("LLM_DECISION_PROVIDER", "openai")
    monkeypatch.setenv("LLM_DECISION_BASE_URL", "http://decider:8000")
    extraction = FakeGateway()
    gateway = provider.decision_gateway(extraction)
    assert isinstance(gateway, FailoverGateway) and gateway.secondary is extraction
    assert gateway.primary.model == "h2o-lightning-4b" and gateway.primary.base_url == "http://decider:8000"

    extraction.up = True
    gateway.primary.available = lambda: False  # decision server down: the extraction model answers
    assert gateway.model == "fake"


def test_the_pipeline_asks_the_decision_model_not_the_extraction_one(client, bootstrap, upload, monkeypatch):
    from app.ai.failover import FailoverGateway
    monkeypatch.setenv("LLM_DECISION_MODEL", "h2o-lightning-4b")
    seen = []

    def fake_extract(text, names, method="native_text", gateway=None):
        return ExtractionRun(fields={n: ExtractedField() for n in names},
                             model="stub", provider="stub", status="OK")

    def fake_choose(gateway, question, state, options, **_):
        seen.append(gateway)
        return {}

    monkeypatch.setattr(service, "extract_attributes", fake_extract)
    monkeypatch.setattr(service, "generate_nutshell", lambda *a, **k: "")
    monkeypatch.setattr(decision, "choose", fake_choose)
    org_id, _ = bootstrap(client)
    upload(client, org_id)
    assert seen and all(isinstance(g, FailoverGateway) and g.primary.model == "h2o-lightning-4b" for g in seen)
    _suggest(client, {"authorization": f"org:{org_id}"})
    assert seen[-1].primary.model == "h2o-lightning-4b"


def _answers_policy(user):
    listing = user.split("Options:\n")[1].splitlines()
    return {next(line[0] for line in listing if ") POLICY:" in line): 0.0}


def test_passes_from_two_models_are_never_averaged():
    """The decision server failing over to the extraction model between passes would mix
    two models' answers into one number."""
    class OneModel(FakeGateway):
        def next_token_logprobs(self, system, user, top=20):
            return _answers_policy(user)  # the same answer in every order

    class Switches(OneModel):
        calls = 0

        def next_token_logprobs(self, system, user, top=20):
            self.calls += 1
            self.model = "decider" if self.calls == 1 else "extractor"
            return super().next_token_logprobs(system, user, top)

    assert decision.top(decision.choose(OneModel(), "q", "s", OPTIONS, orders=3)) == "POLICY"
    assert decision.choose(Switches(), "q", "s", OPTIONS, orders=3) == {}


@pytest.mark.parametrize("kind", ["ollama", "openai"])
def test_a_decision_server_keeps_its_own_credentials(monkeypatch, kind):
    """Review fix: a separately secured decision server must not be sent the extraction
    server's key, or its availability check fails and the switch silently never happens."""
    from app.ai import ollama, openai_compat, provider
    monkeypatch.setattr(ollama, "API_KEY", "extraction-key")
    monkeypatch.setattr(openai_compat, "API_KEY", "extraction-key")
    monkeypatch.setenv("LLM_DECISION_PROVIDER", kind)
    monkeypatch.setenv("LLM_DECISION_API_KEY", "decision-key")
    module = ollama if kind == "ollama" else openai_compat
    gateway = provider.decision_only("decider")
    assert module._headers(gateway.api_key) == {"Authorization": "Bearer decision-key"}

    monkeypatch.delenv("LLM_DECISION_API_KEY")  # unset: the provider's own key, as on one server
    gateway = provider.decision_only("decider")
    assert module._headers(gateway.api_key) == {"Authorization": "Bearer extraction-key"}
    assert provider.make_gateway().api_key is None  # extraction gateways are unchanged
