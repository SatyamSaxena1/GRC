"""The OpenAI-compatible gateway (LM Studio etc.): every choice it makes was measured
against Gemma 4, so each is pinned here, plus the environment switch that selects it."""

from __future__ import annotations

import json

import pytest

from app.ai import openai_compat as oc
from app.ai import provider
from app.ai.decision import choose
from app.ai.extraction import extract_attributes
from app.ai.ollama import OllamaGateway


class _Resp:
    def __init__(self, body=None, lines=None):
        self._body, self._lines = body, lines or []

    def raise_for_status(self):
        pass

    def json(self):
        return self._body

    def iter_lines(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _completion(content, finish="stop", prompt_tokens=100, **extra):
    return {"choices": [{"message": {"content": content}, "finish_reason": finish, **extra}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": 7}}


@pytest.fixture()
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(oc.OpenAICompatGateway, "available", lambda self: True)  # conftest forces False
    return calls


def _gateway(monkeypatch, sent, response):
    def fake_post(url, json=None, **kw):
        sent.append({"url": url, "json": json, **kw})
        return response if not callable(response) else response()
    monkeypatch.setattr(oc.requests, "post", fake_post)
    return oc.OpenAICompatGateway(model="google/gemma-4-e4b")


def test_json_call_turns_thinking_off_and_asks_for_a_loose_json_schema(monkeypatch, sent):
    g = _gateway(monkeypatch, sent, _Resp(_completion('{"a": 1}')))
    assert g.complete_json("sys", "usr") == '{"a": 1}'
    p = sent[0]["json"]
    assert sent[0]["url"].endswith("/v1/chat/completions")
    # measured: without this a hard prompt starts hidden reasoning and the answer is empty
    assert p["reasoning_effort"] == "none"
    # measured: json_object is rejected (HTTP 400); a STRICT schema fabricates values (ADR-014)
    assert p["response_format"]["type"] == "json_schema"
    assert p["response_format"]["json_schema"]["schema"] == {"type": "object", "additionalProperties": True}
    assert p["temperature"] == 0 and p["seed"] == oc.SEED


def test_code_fences_around_json_are_stripped(monkeypatch, sent):
    g = _gateway(monkeypatch, sent, _Resp(_completion('```json\n{"a": 1}\n```')))
    assert g.complete_json("s", "u") == '{"a": 1}'
    assert oc.unfence('{"plain": true}') == '{"plain": true}'


def test_reasoning_effort_can_be_omitted_for_servers_that_reject_it(monkeypatch, sent):
    monkeypatch.setattr(oc, "REASONING_EFFORT", "")
    g = _gateway(monkeypatch, sent, _Resp(_completion("{}")))
    g.complete_json("s", "u")
    assert "reasoning_effort" not in sent[0]["json"]


def test_length_stop_is_flagged_truncated_and_routed_to_review(monkeypatch, sent):
    g = _gateway(monkeypatch, sent, _Resp(_completion('{"password_min_length": {"value": 8}}', finish="length")))
    run = extract_attributes(g, "some text", ["password_min_length"])
    assert g.last_truncated is True
    assert run.status == "INVALID_OUTPUT" and run.fields["password_min_length"].value is None


def test_full_context_window_is_flagged_when_the_window_is_known(monkeypatch, sent):
    monkeypatch.setattr(oc, "CONTEXT", 16384)
    g = _gateway(monkeypatch, sent, _Resp(_completion("{}", prompt_tokens=16384)))
    g.complete_json("s", "u")
    assert g.last_truncated is True
    g2 = _gateway(monkeypatch, sent, _Resp(_completion("{}", prompt_tokens=500)))
    g2.complete_json("s", "u")
    assert g2.last_truncated is False and g2.last_stats["prompt_tokens"] == 500


def test_vision_sends_images_as_data_uris_with_no_json_format(monkeypatch, sent):
    g = _gateway(monkeypatch, sent, _Resp(_completion("Transcribed text")))
    assert g.complete_vision("sys", "Transcribe this page.", [b"\x89PNG-bytes"]) == "Transcribed text"
    content = sent[0]["json"]["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "Transcribe this page."}
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "response_format" not in sent[0]["json"] and sent[0]["json"]["reasoning_effort"] == "none"


def test_streaming_yields_content_and_keeps_token_accounting(monkeypatch, sent):
    events = [{"choices": [{"delta": {"content": '{"a":'}}]},
              {"choices": [{"delta": {"content": ' 1}'}, "finish_reason": "stop"}]},
              {"choices": [], "usage": {"prompt_tokens": 321, "completion_tokens": 4}}]
    lines = [("data: " + json.dumps(e)).encode() for e in events] + [b"", b"data: [DONE]"]
    g = _gateway(monkeypatch, sent, _Resp(lines=lines))
    assert "".join(g.stream_json("s", "u")) == '{"a": 1}'
    assert sent[0]["json"]["stream"] is True and sent[0]["json"]["stream_options"] == {"include_usage": True}
    assert g.last_stats["prompt_tokens"] == 321 and g.last_truncated is False


def test_token_probabilities_feed_the_letter_choice_decision(monkeypatch, sent):
    body = {"choices": [{"logprobs": {"content": [{"token": "A", "logprob": -0.05, "top_logprobs": [
        {"token": "A", "logprob": -0.05}, {"token": "B", "logprob": -3.2}, {"token": "C", "logprob": -6.0}]}]}}]}
    g = _gateway(monkeypatch, sent, _Resp(body))
    probs = choose(g, "Which?", "state", {"x": "first", "y": "second", "z": "third"})
    assert probs["x"] > 0.9 and probs["x"] > probs["y"] > probs["z"]
    p = sent[0]["json"]
    assert p["max_tokens"] == 1 and p["logprobs"] is True and p["reasoning_effort"] == "none"


def test_no_probabilities_means_no_suggestion_not_a_crash(monkeypatch, sent):
    """What a model that started hidden reasoning looks like: logprobs null."""
    g = _gateway(monkeypatch, sent, _Resp({"choices": [{"message": {"content": ""}, "logprobs": None}]}))
    assert choose(g, "Which?", "state", {"x": "first", "y": "second"}) == {}


def test_a_failing_server_raises_a_clean_error_after_the_retry(monkeypatch, sent):
    def boom():
        raise oc.requests.ConnectionError("down")
    g = _gateway(monkeypatch, sent, boom)
    with pytest.raises(RuntimeError, match="LLM call failed"):
        g.complete_json("s", "u")
    assert len(sent) == oc.MAX_RETRIES + 1


def test_availability_means_loaded(monkeypatch):
    """LM Studio lists only loaded models: one that idled out reads as unavailable."""
    monkeypatch.undo()
    monkeypatch.setattr(oc.requests, "get",
                        lambda url, **kw: _Resp({"data": [{"id": "google/gemma-4-e4b"}]}))
    assert oc.OpenAICompatGateway(model="google/gemma-4-e4b").available() is True
    monkeypatch.setattr(oc.requests, "get", lambda url, **kw: _Resp({"data": []}))
    assert oc.OpenAICompatGateway(model="google/gemma-4-e4b").available() is False
    def down(url, **kw):
        raise oc.requests.ConnectionError("down")
    monkeypatch.setattr(oc.requests, "get", down)
    assert oc.OpenAICompatGateway(model="google/gemma-4-e4b").available() is False


# ------------------------------------------------------------------ the provider switch

def test_ollama_is_the_default_provider(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert isinstance(provider.make_gateway(), OllamaGateway)


def test_env_selects_the_openai_compatible_gateway_and_overrides_the_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    g = provider.make_gateway(model="other-model", vision_model="vis")
    assert isinstance(g, oc.OpenAICompatGateway) and g.model == "other-model" and g.vision_model == "vis"
    assert provider.make_gateway().model == oc.MODEL
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    assert isinstance(provider.make_gateway(), OllamaGateway)   # switching back is the rollback


def test_pipeline_entry_points_follow_the_switch(monkeypatch):
    from app import ingest
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    assert isinstance(ingest.gateway_for(None), oc.OpenAICompatGateway)
    assert isinstance(ingest._gateway(), oc.OpenAICompatGateway)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    assert isinstance(ingest.gateway_for(None), OllamaGateway)


def test_health_check_reports_the_configured_providers_model(client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setattr(oc, "MODEL", "google/gemma-4-e4b")
    monkeypatch.setattr(oc.OpenAICompatGateway, "available", lambda self: False)
    checks = client.get("/health/ready").json()["checks"]
    assert checks["model"] == "unavailable" and checks["model_name"] == "google/gemma-4-e4b"
