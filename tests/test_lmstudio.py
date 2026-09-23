"""LMStudioGateway.complete_with_tools loop: executes tool calls, feeds
results back, terminates on plain content or the round cap. The HTTP layer
(`_chat_message`) is monkeypatched with scripted responses — same "stub the
model call, check what the code does with it" approach as test_extraction.py,
just at the loop level since this logic (unlike a single complete_json call)
has a branch and a cap worth testing directly."""

from __future__ import annotations

from app.ai.lmstudio import LMStudioGateway


def _script(responses):
    """Returns a callable that hands out one scripted message per call,
    shaped like the "message" object LMStudioGateway._chat_message returns."""
    calls = list(responses)

    def _chat_message(payload):
        return calls.pop(0)

    return _chat_message


def test_tool_call_then_final_content(monkeypatch):
    gateway = LMStudioGateway()
    seen_tool_calls = []

    def executor(name, args):
        seen_tool_calls.append((name, args))
        return {"title": "Password policy", "text": "Minimum 12 characters."}

    monkeypatch.setattr(gateway, "_chat_message", _script([
        {"content": "", "tool_calls": [
            {"id": "call_1", "function": {"name": "get_clause_text",
                                          "arguments": '{"framework": "PCI-DSS", "clause": "8.3.6"}'}},
        ]},
        {"content": '{"explanation": "done"}', "tool_calls": []},
    ]))

    result = gateway.complete_with_tools("system", "user", [{"type": "function"}], executor)

    assert result == '{"explanation": "done"}'
    assert seen_tool_calls == [("get_clause_text", {"framework": "PCI-DSS", "clause": "8.3.6"})]


def test_no_tool_calls_returns_first_content_immediately():
    gateway = LMStudioGateway()
    gateway._chat_message = _script([{"content": "plain answer", "tool_calls": []}])

    result = gateway.complete_with_tools("system", "user", [], lambda n, a: {})

    assert result == "plain answer"


def test_max_rounds_cap_stops_an_endless_tool_call_loop():
    gateway = LMStudioGateway()
    endless_tool_call = {"content": "", "tool_calls": [
        {"id": "call_1", "function": {"name": "get_clause_text", "arguments": "{}"}},
    ]}
    calls = {"n": 0}

    def _chat_message(payload):
        calls["n"] += 1
        return endless_tool_call

    gateway._chat_message = _chat_message

    result = gateway.complete_with_tools("system", "user", [], lambda n, a: {}, max_rounds=3)

    assert calls["n"] == 3
    assert result == ""  # never produced plain content, degrades to empty rather than hanging


def test_executor_exception_becomes_a_tool_error_not_a_crash():
    gateway = LMStudioGateway()

    def boom(name, args):
        raise ValueError("bad clause")

    gateway._chat_message = _script([
        {"content": "", "tool_calls": [
            {"id": "call_1", "function": {"name": "get_clause_text", "arguments": "{}"}},
        ]},
        {"content": "recovered", "tool_calls": []},
    ])

    result = gateway.complete_with_tools("system", "user", [], boom)

    assert result == "recovered"


def test_chat_failure_degrades_to_last_content_seen(monkeypatch):
    gateway = LMStudioGateway()

    def _chat_message(payload):
        raise RuntimeError("connection refused")

    gateway._chat_message = _chat_message

    result = gateway.complete_with_tools("system", "user", [], lambda n, a: {})

    assert result == ""


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
