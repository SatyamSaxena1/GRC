"""LM Studio-backed gateway, used only for tool-calling features. The
extraction/OCR pipeline stays on OllamaGateway (app/ai/ollama.py) — this
gateway exists because that model isn't trained for tool use and LM Studio's
qwen3.8-27b is (confirmed against LM Studio's own model metadata, not just
name-based guessing).

Same shape as app/ai/ollama.py: raw `requests` against a local HTTP server,
model name from env, never hard-coded."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Callable

import requests

logger = logging.getLogger("app.ai.lmstudio")

BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234")
MODEL = os.environ.get("LMSTUDIO_MODEL", "qwen/qwen3.8-27b")
TIMEOUT_S = float(os.environ.get("LMSTUDIO_TIMEOUT_S", "120"))
MAX_RETRIES = 1


class LMStudioGateway:
    """Implements the ModelGateway protocol (app/ai/gateway.py) plus
    complete_with_tools, the same way OllamaGateway carries stream_json
    beyond the base protocol — callers check for it with getattr(...)."""

    provider = "lmstudio"

    def __init__(self, model: str = MODEL, base_url: str = BASE_URL):
        self.model = model
        self.base_url = base_url
        self.last_latency_ms = 0

    def available(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/v1/models", timeout=5)
            resp.raise_for_status()
            names = {m["id"] for m in resp.json().get("data", [])}
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
            "response_format": {"type": "json_object"},
        })

    def complete_vision(self, system: str, user: str, images: list[bytes]) -> str:
        # Never called: LMStudioGateway backs only tool-calling features, not
        # the extraction/OCR pipeline (app/ai/ollama.py's VISION_MODEL still
        # handles that). A protocol stub, not a real path.
        raise NotImplementedError("LMStudioGateway does not do vision extraction")

    def complete_with_tools(
        self, system: str, user: str, tools: list[dict],
        executor: Callable[[str, dict], dict], max_rounds: int = 4,
    ) -> str:
        """Runs the standard tool-call loop: send messages + tools, execute
        any tool_calls the model asks for via `executor(name, args)`, feed
        the results back, repeat until the model answers in plain content or
        max_rounds is hit. Never raises — degrades to the last content seen,
        same as every other AI call in this codebase (a broken model call
        must never fail the request it's narrating)."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        last_content = ""
        for _ in range(max_rounds):
            try:
                message = self._chat_message({
                    "model": self.model, "messages": messages, "tools": tools,
                })
            except RuntimeError:
                logger.warning("lmstudio_tool_call_failed model=%s", self.model)
                return last_content

            content = message.get("content") or ""
            if content:
                last_content = content
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                return last_content

            messages.append(message)
            for call in tool_calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                try:
                    args = _parse_args(fn.get("arguments"))
                    result = executor(name, args)
                except Exception as exc:  # noqa: BLE001 - a bad tool call must not crash the loop
                    result = {"error": str(exc)}
                messages.append({
                    "role": "tool", "tool_call_id": call.get("id", ""), "content": _dumps(result),
                })
        return last_content

    def _chat_message(self, payload: dict) -> dict:
        start = time.monotonic()
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = requests.post(f"{self.base_url}/v1/chat/completions", json=payload, timeout=TIMEOUT_S)
                resp.raise_for_status()
                message = resp.json()["choices"][0]["message"]
                self.last_latency_ms = int((time.monotonic() - start) * 1000)
                logger.info("lmstudio_call model=%s latency_ms=%d attempt=%d",
                            self.model, self.last_latency_ms, attempt)
                return message
            except (requests.RequestException, KeyError, IndexError) as exc:
                last_error = exc
                logger.warning("lmstudio_call_failed model=%s attempt=%d error=%s",
                                self.model, attempt, exc)
        raise RuntimeError(f"LM Studio call failed after {MAX_RETRIES + 1} attempt(s)") from last_error

    def _chat(self, payload: dict) -> str:
        return self._chat_message(payload).get("content") or ""


def _parse_args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw) if raw else {}
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _dumps(result) -> str:
    try:
        return json.dumps(result)
    except TypeError:
        return json.dumps({"error": "unserializable tool result"})
