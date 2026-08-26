"""Ollama-backed ModelGateway. Local inference — no document content leaves
the machine. Model name comes from env, never hard-coded (installs vary)."""

from __future__ import annotations

import logging
import os
import time

import requests

logger = logging.getLogger("app.ai.ollama")

BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
MODEL = os.environ.get("OLLAMA_MODEL", "")
VISION_MODEL = os.environ.get("OLLAMA_VISION_MODEL", MODEL)
TIMEOUT_S = float(os.environ.get("OLLAMA_TIMEOUT_S", "60"))
MAX_RETRIES = 1


class OllamaGateway:
    provider = "ollama"

    def __init__(self, model: str = MODEL, base_url: str = BASE_URL):
        self.model = model
        self.base_url = base_url
        self.last_latency_ms = 0

    def available(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            names = {m["name"] for m in resp.json().get("models", [])}
            return bool(self.model) and self.model in names
        except requests.RequestException:
            return False

    def complete_json(self, system: str, user: str) -> str:
        return self._chat({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": "json",
            "stream": False,
        })

    def complete_vision(self, system: str, user: str, images: list[bytes]) -> str:
        import base64

        return self._chat({
            "model": VISION_MODEL or self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user,
                 "images": [base64.b64encode(img).decode() for img in images]},
            ],
            "stream": False,
        })

    def _chat(self, payload: dict) -> str:
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            start = time.monotonic()
            try:
                resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=TIMEOUT_S)
                resp.raise_for_status()
                content = resp.json()["message"]["content"]
                self.last_latency_ms = int((time.monotonic() - start) * 1000)
                logger.info("ollama_call model=%s latency_ms=%d attempt=%d",
                            self.model, self.last_latency_ms, attempt)
                return content
            except (requests.RequestException, KeyError) as exc:
                last_error = exc
                logger.warning("ollama_call_failed model=%s attempt=%d error=%s",
                                self.model, attempt, exc)
        raise RuntimeError(f"Ollama call failed after {MAX_RETRIES + 1} attempt(s)") from last_error


def list_models(base_url: str = BASE_URL) -> list[str]:
    resp = requests.get(f"{base_url}/api/tags", timeout=5)
    resp.raise_for_status()
    return [m["name"] for m in resp.json().get("models", [])]
