"""The workspace assistant (app/routers/assistant.py): it reads only what the asker could
already see, can't write anything, records every question in the audit chain, and says so
plainly when its model is offline. The tool-calling gateway reuses the LLM_* connection."""

from __future__ import annotations

import importlib

from app import ingest
from app.routers import assistant


class ScriptedGateway:
    """Calls the given tools in order through the real executor, then answers."""

    def __init__(self, calls, answer="Here is what I found.", available=True):
        self.calls, self.answer, self._available = calls, answer, available
        self.model = "stub-gemma"
        self.results = []
        self.tools_offered = []

    def available(self):
        return self._available

    def complete_with_tools(self, system, user, tools, executor, max_rounds=4):
        self.tools_offered = [t["function"]["name"] for t in tools]
        self.results = [executor(name, args) for name, args in self.calls]
        return self.answer


def _use(monkeypatch, gateway):
    monkeypatch.setattr(ingest, "_tool_gateway", lambda: gateway)


def test_answers_with_the_askers_own_data_and_audits_the_question(client, bootstrap, upload, monkeypatch):
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    gateway = ScriptedGateway([("list_evidence", {}), ("get_evidence", {"evidence_id": evidence_id}),
                               ("list_gaps", {}), ("get_clause_text", {"framework": "ISO-27001", "clause": "A.5.15"})])
    _use(monkeypatch, gateway)

    res = client.post("/assistant/ask", headers={"authorization": f"org:{org_id}"},
                      json={"question": "What's wrong with my policy?", "page": f"/evidence/{evidence_id}"})
    assert res.status_code == 200, res.text
    assert res.json()["answer"] == "Here is what I found."
    listed, one, gaps, clause = gateway.results
    assert [e["id"] for e in listed["result"]] == [evidence_id]
    assert "verdicts" in one["result"] and "facts" in one["result"]
    assert "result" in gaps
    assert clause["title"]

    events = client.get("/activity", headers={"authorization": f"org:{org_id}"}).json()
    asked = [e for e in (events if isinstance(events, list) else events.get("events", []))
             if e.get("action") == "ASSISTANT_ASKED"]
    assert asked and asked[0]["detail"]["tools"] == ["list_evidence", "get_evidence", "list_gaps", "get_clause_text"]


def test_cannot_read_another_organisations_evidence(client, bootstrap, upload, monkeypatch):
    org_a, _ = bootstrap(client)
    org_b, _ = bootstrap(client)
    foreign = upload(client, org_b, content=b"org b secret policy").json()["evidence_id"]
    gateway = ScriptedGateway([("get_evidence", {"evidence_id": foreign})])
    _use(monkeypatch, gateway)

    res = client.post("/assistant/ask", headers={"authorization": f"org:{org_a}"}, json={"question": "show it"})
    assert res.status_code == 200
    assert "error" in gateway.results[0] and "result" not in gateway.results[0]


def test_the_model_is_offered_read_only_tools_only(client, bootstrap, monkeypatch):
    org_id, _ = bootstrap(client)
    gateway = ScriptedGateway([("upload_evidence", {}), ("close_gap", {"id": "x"})])
    _use(monkeypatch, gateway)

    client.post("/assistant/ask", headers={"authorization": f"org:{org_id}"}, json={"question": "fix it"})
    assert set(gateway.tools_offered) == {"list_evidence", "get_evidence", "list_gaps", "list_tasks",
                                          "get_clause_text", "search_glossary"}
    assert all("unknown tool" in r["error"] for r in gateway.results)
    assert "never suggest a verdict should be different" in assistant.SYSTEM_PROMPT


def test_offline_model_is_a_clear_503(client, bootstrap, monkeypatch):
    org_id, _ = bootstrap(client)
    _use(monkeypatch, ScriptedGateway([], available=False))
    res = client.post("/assistant/ask", headers={"authorization": f"org:{org_id}"}, json={"question": "hi"})
    assert res.status_code == 503 and "offline" in res.json()["detail"]


def test_tool_gateway_reuses_the_llm_connection_and_sends_the_token(monkeypatch):
    from app.ai import lmstudio

    for key in ("LMSTUDIO_BASE_URL", "LMSTUDIO_MODEL", "LMSTUDIO_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "https://tunnel.example/")
    monkeypatch.setenv("LLM_MODEL", "google/gemma-4-e4b")
    monkeypatch.setenv("LLM_API_KEY", "secret-token")
    try:
        mod = importlib.reload(lmstudio)
        assert mod.BASE_URL == "https://tunnel.example"
        assert mod.MODEL == "google/gemma-4-e4b"
        assert mod._headers() == {"Authorization": "Bearer secret-token"}
    finally:
        monkeypatch.undo()
        importlib.reload(lmstudio)
