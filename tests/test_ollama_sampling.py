"""The pinned sampling options go out on every call, and a prompt that filled the
context window is treated as truncated rather than trusted."""

from __future__ import annotations

from app.ai import ollama
from app.ai.extraction import extract_attributes


class _Resp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def _gateway(monkeypatch, body, sent):
    def fake_post(url, json=None, **kw):
        sent.append(json)
        return _Resp(body)

    monkeypatch.setattr(ollama.requests, "post", fake_post)
    # conftest's autouse fixture makes every gateway "unavailable"; this test is
    # about what happens once the model *is* reachable.
    monkeypatch.setattr(ollama.OllamaGateway, "available", lambda self: True)
    return ollama.OllamaGateway(model="m")


def test_every_json_call_pins_temperature_seed_and_context(monkeypatch):
    sent = []
    g = _gateway(monkeypatch, {"message": {"content": "{}"}, "prompt_eval_count": 100,
                               "done_reason": "stop"}, sent)
    g.complete_json("s", "u")
    opts = sent[0]["options"]
    assert opts == {"temperature": 0, "seed": ollama.SEED, "num_ctx": ollama.NUM_CTX}
    assert g.last_truncated is False and g.last_stats["prompt_tokens"] == 100


def test_full_context_window_is_flagged_and_routed_to_review(monkeypatch):
    sent = []
    full = ollama.NUM_CTX  # Ollama reports the truncated prompt, i.e. exactly the window
    g = _gateway(monkeypatch, {"message": {"content": '{"password_min_length": {"value": 8}}'},
                               "prompt_eval_count": full, "done_reason": "stop"}, sent)
    run = extract_attributes(g, "some text", ["password_min_length"])
    assert g.last_truncated is True
    assert run.status == "INVALID_OUTPUT"
    assert run.fields["password_min_length"].value is None  # not trusted


def test_length_stop_is_flagged(monkeypatch):
    sent = []
    g = _gateway(monkeypatch, {"message": {"content": "{}"}, "prompt_eval_count": 10,
                               "done_reason": "length"}, sent)
    g.complete_json("s", "u")
    assert g.last_truncated is True
