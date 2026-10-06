"""Failover between two model servers: an outage of the first must not strand an upload,
and must never blur which model produced a fact."""

from __future__ import annotations

import pytest

from app.ai import openai_compat, provider
from app.ai.extraction import extract_attributes, extract_attributes_streaming
from app.ai.failover import FailoverGateway
from app.ai.decision import choose
from app.ai.ollama import OllamaGateway


class Stub:
    """A scripted gateway: `up` for the availability probe, `fail` to make calls raise."""
    def __init__(self, name, up=True, fail=False, reply='{"password_min_length": {"value": 14, "confidence": 0.9, "sources": []}}'):
        self.model, self.provider, self.up, self.fail, self.reply = name, f"prov-{name}", up, fail, reply
        self.calls: list[str] = []
        self.last_latency_ms, self.last_stats, self.last_truncated = 7, {"who": name}, False

    def available(self):
        return self.up

    def _go(self, what):
        self.calls.append(what)
        if self.fail:
            raise RuntimeError(f"{self.model} down")

    def complete_json(self, system, user):
        self._go("json")
        return self.reply

    def complete_vision(self, system, user, images):
        self._go("vision")
        return f"text from {self.model}"

    def next_token_logprobs(self, system, user, top=20):
        self._go("logprobs")
        return {"A": -0.1, "B": -4.0}

    def stream_json(self, system, user):
        self._go("stream")
        for piece in (self.reply[:20], self.reply[20:]):
            yield piece


def test_the_primary_is_used_when_it_is_up():
    p, s = Stub("gemma"), Stub("qwen")
    g = FailoverGateway(p, s)
    assert g.available() and g.model == "gemma" and g.provider == "prov-gemma"
    assert g.complete_json("s", "u") and p.calls == ["json"] and s.calls == []
    assert g.failed_over is False


def test_an_unavailable_primary_hands_everything_to_the_secondary_and_says_so():
    p, s = Stub("gemma", up=False), Stub("qwen")
    g = FailoverGateway(p, s)
    assert g.available() is True
    assert g.model == "qwen" and g.provider == "prov-qwen"          # provenance is the one that will answer
    g.complete_json("s", "u")
    assert p.calls == [] and s.calls == ["json"] and g.failed_over is True


def test_a_call_that_fails_on_the_primary_is_retried_on_the_secondary_and_the_primary_is_benched():
    p, s = Stub("gemma", fail=True), Stub("qwen")
    g = FailoverGateway(p, s)
    assert g.model == "gemma"
    assert g.complete_json("s", "u") == s.reply
    assert g.model == "qwen" and g.failed_over is True
    g.complete_json("s", "u")
    g.complete_vision("s", "u", [b"x"])
    assert p.calls == ["json"]                  # one failed attempt, not one per call: a dead server costs one timeout
    assert s.calls == ["json", "json", "vision"]


def test_both_down_means_unavailable_and_a_clean_error():
    g = FailoverGateway(Stub("gemma", up=False), Stub("qwen", up=False))
    assert g.available() is False
    h = FailoverGateway(Stub("gemma", fail=True), Stub("qwen", fail=True))
    with pytest.raises(RuntimeError):
        h.complete_json("s", "u")


def test_call_state_describes_the_gateway_that_answered():
    p, s = Stub("gemma", fail=True), Stub("qwen")
    s.last_latency_ms, s.last_truncated = 4200, True
    g = FailoverGateway(p, s)
    g.complete_json("s", "u")
    assert g.last_latency_ms == 4200 and g.last_truncated is True and g.last_stats == {"who": "qwen"}


def test_extraction_records_the_model_that_actually_answered():
    p, s = Stub("gemma", fail=True), Stub("qwen")
    run = extract_attributes(FailoverGateway(p, s), "doc text", ["password_min_length"])
    assert run.status == "OK" and run.fields["password_min_length"].value == 14
    assert run.model == "qwen" and run.provider == "prov-qwen"      # not "gemma", which failed


def test_extraction_with_a_healthy_primary_records_the_primary():
    run = extract_attributes(FailoverGateway(Stub("gemma"), Stub("qwen")), "doc text", ["password_min_length"])
    assert run.model == "gemma"


def test_streaming_fails_over_when_the_primary_dies_before_any_output():
    class DeadStream(Stub):
        def stream_json(self, system, user):
            self._go("stream")
            yield from ()
    p, s = DeadStream("gemma", fail=True), Stub("qwen")
    g = FailoverGateway(p, s)
    assert "".join(g.stream_json("s", "u")) == s.reply
    assert g.model == "qwen"


def test_streaming_extraction_through_the_wrapper_records_the_answering_model():
    p, s = Stub("gemma", up=False), Stub("qwen")
    run = extract_attributes_streaming(FailoverGateway(p, s), "doc", ["password_min_length"])
    assert run.model == "qwen" and run.fields["password_min_length"].value == 14


def test_a_stream_that_breaks_midway_falls_back_to_a_blocking_call_on_the_other_server():
    class Breaks(Stub):
        def stream_json(self, system, user):
            yield self.reply[:10]
            raise OSError("link dropped")
    p, s = Breaks("gemma"), Stub("qwen")
    run = extract_attributes_streaming(FailoverGateway(p, s), "doc", ["password_min_length"])
    assert run.status == "OK" and run.model == "qwen" and run.fields["password_min_length"].value == 14


def test_letter_choice_decisions_survive_an_outage():
    g = FailoverGateway(Stub("gemma", fail=True), Stub("qwen"))
    probs = choose(g, "Which?", "state", {"x": "first", "y": "second"})
    assert probs["x"] > 0.9


# ------------------------------------------------------------------ configuration

def test_no_fallback_configured_means_a_plain_gateway(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_FALLBACK", raising=False)
    assert isinstance(provider.make_gateway(), openai_compat.OpenAICompatGateway)


def test_llm_fallback_wraps_the_primary_and_ignores_a_fallback_equal_to_it(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK", "ollama")
    g = provider.make_gateway()
    assert isinstance(g, FailoverGateway)
    assert isinstance(g.primary, openai_compat.OpenAICompatGateway) and isinstance(g.secondary, OllamaGateway)
    monkeypatch.setenv("LLM_FALLBACK", "openai")
    assert isinstance(provider.make_gateway(), openai_compat.OpenAICompatGateway)   # same as primary: no wrapper
    monkeypatch.setenv("LLM_FALLBACK", "none")
    assert isinstance(provider.make_gateway(), openai_compat.OpenAICompatGateway)


def test_a_per_evidence_model_choice_applies_to_the_primary_only(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK", "ollama")
    g = provider.make_gateway(model="chosen-on-primary")
    assert g.primary.model == "chosen-on-primary"
    assert g.secondary.model != "chosen-on-primary"    # a model name on one server means nothing on the other


def test_health_reports_when_it_is_running_on_the_fallback(client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK", "ollama")
    monkeypatch.setattr(openai_compat, "MODEL", "gemma")
    monkeypatch.setattr(openai_compat.OpenAICompatGateway, "available", lambda self: False)
    monkeypatch.setattr(OllamaGateway, "available", lambda self: True)
    checks = client.get("/health/ready").json()["checks"]
    assert checks["model"] == "ok" and "fallback" in checks["model_degraded"]
    monkeypatch.setattr(OllamaGateway, "available", lambda self: False)
    assert client.get("/health/ready").json()["checks"]["model"] == "unavailable"
