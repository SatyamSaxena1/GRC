"""The assistant's optional fallback model (ADR-053): used only when the primary server is unreachable, with its own
address, model and key, and never the primary's key."""

from __future__ import annotations

import pytest

from app import ingest
from app.ai import lmstudio

PRIMARY_KEY, BACKUP_KEY = "PRIMARY-KEY-VALUE", "BACKUP-KEY-VALUE"


@pytest.fixture()
def servers(monkeypatch):
    """Two stand-in servers: which are reachable is settable, and every request is recorded."""
    state = {"up": {"http://primary.test": True, "https://backup.test/api": True}, "calls": []}

    class R:
        def __init__(self, body):
            self._b = body

        def raise_for_status(self):
            return None

        def json(self):
            return self._b

    def get(url, headers=None, timeout=None):
        base = url.rsplit("/v1/models", 1)[0]
        state["calls"].append(("GET", base, dict(headers or {})))
        if not state["up"].get(base):
            raise lmstudio.requests.ConnectionError("down")
        return R({"data": [{"id": "primary-model"}, {"id": "backup-model"}]})

    def post(url, json=None, headers=None, timeout=None):
        base = url.rsplit("/v1/chat/completions", 1)[0]
        state["calls"].append(("POST", base, dict(headers or {}), dict(json or {})))
        return R({"choices": [{"message": {"content": "an answer"}}]})

    # the constructor's defaults were bound when the module loaded, so patch those, not only the module constants
    monkeypatch.setattr(lmstudio.LMStudioGateway.__init__, "__defaults__", ("primary-model", "http://primary.test", None, None))
    monkeypatch.setattr(lmstudio, "BASE_URL", "http://primary.test")
    monkeypatch.setattr(lmstudio, "MODEL", "primary-model")
    monkeypatch.setattr(lmstudio, "API_KEY", PRIMARY_KEY)
    monkeypatch.setattr(lmstudio, "REASONING_EFFORT", "none")
    monkeypatch.setattr(lmstudio.requests, "get", get)
    monkeypatch.setattr(lmstudio.requests, "post", post)
    for k in ("LLM_FALLBACK_BASE_URL", "LLM_FALLBACK_MODEL", "LLM_FALLBACK_API_KEY", "LLM_FALLBACK_REASONING_EFFORT"):
        monkeypatch.delenv(k, raising=False)
    return state


def _configure(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://backup.test/api/")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "backup-model")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", BACKUP_KEY)


def test_without_a_fallback_the_primary_is_always_used(servers):
    servers["up"]["http://primary.test"] = False
    g = ingest._tool_gateway()
    assert g.model == "primary-model" and g.base_url == "http://primary.test" and not g.available()


def test_a_reachable_primary_is_used_and_the_fallback_is_never_contacted(servers, monkeypatch):
    _configure(monkeypatch)
    assert ingest._tool_gateway().model == "primary-model"
    assert all(c[1] == "http://primary.test" for c in servers["calls"])


def test_an_unreachable_primary_hands_over_to_the_fallback(servers, monkeypatch):
    _configure(monkeypatch)
    servers["up"]["http://primary.test"] = False
    g = ingest._tool_gateway()
    assert g.model == "backup-model" and g.base_url == "https://backup.test/api" and g.available()


def test_if_both_are_down_the_primary_is_returned_so_the_helper_says_offline(servers, monkeypatch):
    _configure(monkeypatch)
    servers["up"] = {"http://primary.test": False, "https://backup.test/api": False}
    g = ingest._tool_gateway()
    assert g.base_url == "http://primary.test" and not g.available()


def test_the_fallback_uses_its_own_key_and_never_receives_the_primarys(servers, monkeypatch):
    _configure(monkeypatch)
    servers["up"]["http://primary.test"] = False
    g = ingest._tool_gateway()
    g.complete_with_tools("sys", "question", [], lambda n, a: {})
    sent_to_backup = [c for c in servers["calls"] if c[1] == "https://backup.test/api"]
    assert sent_to_backup and all(c[2].get("Authorization") == f"Bearer {BACKUP_KEY}" for c in sent_to_backup)
    assert PRIMARY_KEY not in str(sent_to_backup)


def test_reasoning_effort_is_not_sent_to_the_fallback_unless_asked(servers, monkeypatch):
    _configure(monkeypatch)
    servers["up"]["http://primary.test"] = False
    ingest._tool_gateway().complete_with_tools("s", "q", [], lambda n, a: {})
    body = [c for c in servers["calls"] if c[0] == "POST"][-1][3]
    assert "reasoning_effort" not in body
    monkeypatch.setenv("LLM_FALLBACK_REASONING_EFFORT", "low")
    ingest._tool_gateway().complete_with_tools("s", "q", [], lambda n, a: {})
    assert [c for c in servers["calls"] if c[0] == "POST"][-1][3]["reasoning_effort"] == "low"


def test_the_primary_still_sends_its_reasoning_effort_and_key(servers):
    ingest._tool_gateway().complete_with_tools("s", "q", [], lambda n, a: {})
    post = [c for c in servers["calls"] if c[0] == "POST"][-1]
    assert post[3]["reasoning_effort"] == "none" and post[2]["Authorization"] == f"Bearer {PRIMARY_KEY}"
