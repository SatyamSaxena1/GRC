"""Which model server the extraction/OCR pipeline talks to, chosen by environment.

    LLM_PROVIDER=ollama   (default)  OLLAMA_BASE_URL / OLLAMA_MODEL / OLLAMA_VISION_MODEL / OLLAMA_API_KEY
    LLM_PROVIDER=openai              LLM_BASE_URL / LLM_MODEL / LLM_VISION_MODEL / LLM_API_KEY
                                     (LM Studio, vLLM, llama.cpp server: anything OpenAI-compatible)

One place decides, so changing model server is an environment change with no code deploy,
and switching back is the rollback. Tool-calling features keep their own gateway
(app/ai/lmstudio.py); this is only the extraction/OCR/classification path.
"""

from __future__ import annotations

import os

from app.ai import ollama, openai_compat


def provider() -> str:
    # read at call time, not import time, so tests and a restarted service both see the env
    return os.environ.get("LLM_PROVIDER", "ollama").strip().lower()


def _openai() -> bool:
    return provider() in ("openai", "openai-compat", "lmstudio")


def default_model() -> str:
    return openai_compat.MODEL if _openai() else ollama.MODEL


def default_vision_model() -> str:
    return openai_compat.VISION_MODEL if _openai() else ollama.VISION_MODEL


def make_gateway(model: str | None = None, vision_model: str | None = None):
    """A gateway for the configured provider; `model`/`vision_model` override the env
    defaults (the per-evidence model choice)."""
    if _openai():
        return openai_compat.OpenAICompatGateway(model=model or openai_compat.MODEL, vision_model=vision_model)
    return ollama.OllamaGateway(model=model or ollama.MODEL, vision_model=vision_model)


def list_models() -> list[str]:
    return openai_compat.list_models() if _openai() else ollama.list_models(ollama.BASE_URL)
