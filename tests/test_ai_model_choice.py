"""Per-upload model choice: stored on Evidence, honoured by the pipeline,
falls back to the server default when unset. See app/ingest.py::gateway_for."""

from __future__ import annotations

from app import ingest
from app.ai.ollama import OllamaGateway


def test_gateway_for_uses_the_given_model_and_vision_model():
    gateway = ingest.gateway_for("llama3.2:3b", "qwen2.5vl:7b")
    assert isinstance(gateway, OllamaGateway)
    assert gateway.model == "llama3.2:3b"
    assert gateway.vision_model == "qwen2.5vl:7b"


def test_gateway_for_falls_back_to_server_default_when_unset(monkeypatch):
    monkeypatch.setattr("app.ai.ollama.MODEL", "server-default-model")
    gateway = ingest.gateway_for(None, None)
    assert gateway.model == "server-default-model"
    assert gateway.vision_model is None  # OllamaGateway itself falls back to module VISION_MODEL


def test_available_models_degrades_when_ollama_is_unreachable(monkeypatch):
    import requests

    def boom(base_url):
        raise requests.ConnectionError("no ollama here")

    monkeypatch.setattr("app.ai.ollama.list_models", boom)
    info = ingest.available_models()
    assert info["available"] is False
    assert info["models"] == []


def test_evidence_ai_models_endpoint(client, bootstrap):
    org_id, _ = bootstrap(client)
    response = client.get("/evidence/ai-models", headers={"authorization": f"org:{org_id}"})
    assert response.status_code == 200
    body = response.json()
    assert "available" in body and "models" in body


def test_upload_persists_chosen_model(client, bootstrap, upload):
    org_id, _ = bootstrap(client, frameworks=["ISO-27001"])
    response = client.post(
        "/evidence", headers={"authorization": f"org:{org_id}"},
        params={"artefact_type": "POLICY"},
        data={"ai_model": "llama3.2:3b", "ai_vision_model": "qwen2.5vl:7b"},
        files={"file": ("policy.txt", b"a policy", "text/plain")},
    )
    assert response.status_code == 202, response.text
    evidence_id = response.json()["evidence_id"]

    detail = client.get(f"/evidence/{evidence_id}", headers={"authorization": f"org:{org_id}"}).json()
    assert detail["ai_model"] == "llama3.2:3b"
    assert detail["ai_vision_model"] == "qwen2.5vl:7b"


def test_upload_without_a_choice_leaves_it_null(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    response = upload(client, org_id)
    evidence_id = response.json()["evidence_id"]
    detail = client.get(f"/evidence/{evidence_id}", headers={"authorization": f"org:{org_id}"}).json()
    assert detail["ai_model"] is None
    assert detail["ai_vision_model"] is None
