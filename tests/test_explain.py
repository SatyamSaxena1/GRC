"""explain_cross_framework_gap: narration only, same contract as
draft_remediation/generate_nutshell (test_extraction.py) — never raises,
degrades to "" when there's nothing to explain or the model is unavailable,
and the tool executor never looks up a clause outside the links it was given."""

from __future__ import annotations

from app.ai.explain import explain_cross_framework_gap

LINKS = [
    {"framework": "ISO-27001", "clause": "9.2.3", "verdict": "PASS"},
    {"framework": "PCI-DSS", "clause": "8.3.6", "verdict": "FAIL"},
]


class StubToolGateway:
    """Scripts complete_with_tools directly — explain_cross_framework_gap
    doesn't care how the loop works internally (that's tests/test_lmstudio.py),
    only that it calls the executor it's given and returns the model's text."""

    def __init__(self, response='{"explanation": "clear reason"}', available=True):
        self.response = response
        self._available = available
        self.model = "stub-tool-model"
        self.seen_executor_calls = []

    def available(self):
        return self._available

    def complete_with_tools(self, system, user, tools, executor, max_rounds=4):
        # Exercise the executor once, the way a real tool-calling round would,
        # so tests can assert on what it does with an in-scope/out-of-scope call.
        self.seen_executor_calls.append(executor("get_clause_text", {"framework": "PCI-DSS", "clause": "8.3.6"}))
        self.seen_executor_calls.append(executor("get_clause_text", {"framework": "SOC-2", "clause": "CC6.1"}))
        return self.response


def _clause_text(framework, clause):
    return (f"{framework} {clause} title", f"{framework} {clause} full text")


def test_returns_explanation_from_the_model():
    gateway = StubToolGateway()
    result = explain_cross_framework_gap(gateway, LINKS, _clause_text)
    assert result == "clear reason"


def test_returns_empty_when_gateway_unavailable():
    gateway = StubToolGateway(available=False)
    result = explain_cross_framework_gap(gateway, LINKS, _clause_text)
    assert result == ""


def test_returns_empty_with_fewer_than_two_links():
    gateway = StubToolGateway()
    result = explain_cross_framework_gap(gateway, LINKS[:1], _clause_text)
    assert result == ""


def test_executor_only_resolves_clauses_that_are_part_of_this_evidence_item():
    gateway = StubToolGateway()
    explain_cross_framework_gap(gateway, LINKS, _clause_text)

    in_scope, out_of_scope = gateway.seen_executor_calls
    assert in_scope == {"title": "PCI-DSS 8.3.6 title", "text": "PCI-DSS 8.3.6 full text"}
    assert "error" in out_of_scope  # SOC-2 CC6.1 was never part of `links`


def test_malformed_model_output_is_a_null_explanation_not_a_crash():
    gateway = StubToolGateway(response="not json")
    result = explain_cross_framework_gap(gateway, LINKS, _clause_text)
    assert result == ""


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
