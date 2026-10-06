"""ModelGateway for any server speaking the OpenAI chat API: LM Studio (including
models it serves from another machine over LM Link), vLLM, llama.cpp's server.
Local inference like app/ai/ollama.py: no document content leaves the user's own
hardware, and the model name comes from env, never hard-coded.

Choices below were measured against Gemma 4 on LM Studio, not assumed (see
evaluation/results/README.md):

* reasoning_effort="none" on every call. Gemma is a reasoning model: left alone,
  a hard letter-choice prompt starts a hidden thinking block, the answer field
  comes back empty and no token probabilities exist, so the wrong-document guard
  silently returns nothing. With thinking off every decision answered with its
  letter (19 of 19 calls) and an extraction takes ~7 s instead of ~16.
* response_format json_schema with a permissive "any object" schema. LM Studio
  rejects json_object (HTTP 400) and, with no format at all, wraps every answer in
  ```json fences. A *strict* schema is what ADR-014 found fabricates values, so the
  schema stays loose and the fence-stripper stays as a fallback.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time

import requests

logger = logging.getLogger("app.ai.openai_compat")

BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:1234").rstrip("/")
MODEL = os.environ.get("LLM_MODEL", "")
VISION_MODEL = os.environ.get("LLM_VISION_MODEL", MODEL)
API_KEY = os.environ.get("LLM_API_KEY", "")
TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT_S", "120"))
SEED = int(os.environ.get("LLM_SEED", "42"))
# "none" (default) turns hidden reasoning off; set to "" to send nothing for servers that reject it.
REASONING_EFFORT = os.environ.get("LLM_REASONING_EFFORT", "none")
# The server's loaded context window, if known: lets a full window be recognised as truncation.
# Unset, only an explicit length stop is treated as truncated.
CONTEXT = int(os.environ.get("LLM_CONTEXT", "0"))
TRUNCATION_MARGIN = 32
MAX_RETRIES = 1

_JSON_FORMAT = {"type": "json_schema",
                "json_schema": {"name": "result", "schema": {"type": "object", "additionalProperties": True}}}
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.S)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}


def unfence(text: str) -> str:
    """Models sometimes wrap JSON in a markdown fence even when asked not to."""
    stripped = text.strip()
    return _FENCE.sub("", stripped) if stripped.startswith("```") else text


class OpenAICompatGateway:
    provider = "openai-compat"

    def __init__(self, model: str = MODEL, base_url: str = BASE_URL, vision_model: str | None = None):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.vision_model = vision_model
        self.last_latency_ms = 0
        self.last_stats: dict = {}
        self.last_truncated = False
        self._available: bool | None = None

    # ------------------------------------------------------------------ availability
    def available(self) -> bool:
        """Checked once per instance, like OllamaGateway. LM Studio lists only models
        that are *loaded*, so a model that idled out of memory reads as unavailable
        (uploads then land in review rather than failing mid-pipeline)."""
        if self._available is None:
            try:
                resp = requests.get(f"{self.base_url}/v1/models", headers=_headers(), timeout=5)
                resp.raise_for_status()
                self._available = bool(self.model) and self.model in {m["id"] for m in resp.json().get("data", [])}
            except (requests.RequestException, KeyError, ValueError):
                self._available = False
        return self._available

    # ------------------------------------------------------------------ requests
    def _payload(self, model: str, messages: list[dict], **extra) -> dict:
        payload = {"model": model, "messages": messages, "temperature": 0, "seed": SEED, **extra}
        if REASONING_EFFORT:
            payload["reasoning_effort"] = REASONING_EFFORT
        return payload

    def _record(self, usage: dict | None, finish_reason: str | None) -> None:
        """Keep the server's token accounting so a cut-off prompt or output is visible."""
        prompt_tokens = (usage or {}).get("prompt_tokens") or 0
        self.last_stats = {"prompt_tokens": prompt_tokens, "output_tokens": (usage or {}).get("completion_tokens") or 0,
                           "done_reason": finish_reason or "", "num_ctx": CONTEXT}
        self.last_truncated = finish_reason == "length" or bool(CONTEXT and prompt_tokens >= CONTEXT - TRUNCATION_MARGIN)
        if self.last_truncated:
            logger.error("llm_truncated model=%s %s", self.model, self.last_stats)

    def _post(self, payload: dict, stream: bool = False):
        return requests.post(f"{self.base_url}/v1/chat/completions", json=payload, headers=_headers(),
                             timeout=TIMEOUT_S, stream=stream)

    def _chat(self, payload: dict) -> dict:
        last_error: Exception | None = None
        self.last_truncated = False
        for attempt in range(MAX_RETRIES + 1):
            start = time.monotonic()
            try:
                resp = self._post(payload)
                resp.raise_for_status()
                body = resp.json()
                choice = body["choices"][0]
                self._record(body.get("usage"), choice.get("finish_reason"))
                self.last_latency_ms = int((time.monotonic() - start) * 1000)
                logger.info("llm_call model=%s latency_ms=%d attempt=%d", self.model, self.last_latency_ms, attempt)
                return body
            except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
                last_error = exc
                # the server's own message ("No models loaded...", "context overflow...") is the
                # useful part; a bare "400 Client Error" hides whether it was the document or the host
                detail = getattr(getattr(exc, "response", None), "text", "") or ""
                logger.warning("llm_call_failed model=%s attempt=%d error=%s %s", self.model, attempt, exc,
                               detail.strip().replace("\n", " ")[:240])
        raise RuntimeError(f"LLM call failed after {MAX_RETRIES + 1} attempt(s)") from last_error

    # ------------------------------------------------------------------ the gateway protocol
    def complete_json(self, system: str, user: str) -> str:
        body = self._chat(self._payload(
            self.model,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format=_JSON_FORMAT, stream=False))
        return unfence(body["choices"][0]["message"].get("content") or "")

    def stream_json(self, system: str, user: str):
        """complete_json, yielding content as produced (SSE). Any failure here makes the
        caller fall back to the blocking call, so a broken stream never fails an upload."""
        payload = self._payload(
            self.model, [{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format=_JSON_FORMAT, stream=True, stream_options={"include_usage": True})
        self.last_truncated = False
        start = time.monotonic()
        usage, reason = None, None
        with self._post(payload, stream=True) as resp:
            resp.raise_for_status()
            for raw in resp.iter_lines():
                line = raw.decode() if isinstance(raw, bytes) else raw
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                usage = event.get("usage") or usage
                for choice in event.get("choices", []):
                    piece = (choice.get("delta") or {}).get("content")
                    if piece:
                        yield piece
                    reason = choice.get("finish_reason") or reason
        self._record(usage, reason)
        self.last_latency_ms = int((time.monotonic() - start) * 1000)
        logger.info("llm_stream model=%s latency_ms=%d", self.model, self.last_latency_ms)

    def complete_vision(self, system: str, user: str, images: list[bytes]) -> str:
        parts = [{"type": "text", "text": user}] + [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(img).decode()}}
            for img in images]
        body = self._chat(self._payload(
            self.vision_model or VISION_MODEL or self.model,
            [{"role": "system", "content": system}, {"role": "user", "content": parts}], stream=False))
        return body["choices"][0]["message"].get("content") or ""

    def next_token_logprobs(self, system: str, user: str, top: int = 20) -> dict[str, float]:
        """{token: logprob} for the single next token (app/ai/decision.py). Raises if the
        server returned none, which is what a model that started a hidden reasoning block
        looks like; decision.py turns that into "no suggestion"."""
        start = time.monotonic()
        try:
            resp = self._post(self._payload(
                self.model, [{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_tokens=1, logprobs=True, top_logprobs=top, stream=False))
            resp.raise_for_status()
            first = resp.json()["choices"][0]["logprobs"]["content"][0]
            alternatives = first.get("top_logprobs") or [first]
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
            raise RuntimeError("LLM logprobs call failed") from exc
        self.last_latency_ms = int((time.monotonic() - start) * 1000)
        return {a["token"]: a["logprob"] for a in alternatives if "token" in a and "logprob" in a}


def list_models(base_url: str = BASE_URL) -> list[str]:
    resp = requests.get(f"{base_url.rstrip('/')}/v1/models", headers=_headers(), timeout=5)
    resp.raise_for_status()
    return [m["id"] for m in resp.json().get("data", [])]
