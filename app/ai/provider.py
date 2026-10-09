"""Which model server the extraction/OCR pipeline talks to, chosen by environment.

    LLM_PROVIDER=ollama   (default)  OLLAMA_BASE_URL / OLLAMA_MODEL / OLLAMA_VISION_MODEL / OLLAMA_API_KEY
    LLM_PROVIDER=openai              LLM_BASE_URL / LLM_MODEL / LLM_VISION_MODEL / LLM_API_KEY
                                     (LM Studio, vLLM, llama.cpp server: anything OpenAI-compatible)
    LLM_FALLBACK=ollama|openai       (optional) a second provider used when the first is down
                                     (app/ai/failover.py), configured by its own variables above
    LLM_DECISION_MODEL               (optional) a Jev-class model for the typed decisions only
                                     (app/ai/decision.py; ADR-025), with LLM_DECISION_PROVIDER /
                                     LLM_DECISION_BASE_URL / LLM_DECISION_API_KEY when it runs on
                                     another server

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


def _build(kind: str, model: str | None, vision_model: str | None, base_url: str = "",
           api_key: str | None = None):
    if kind in ("openai", "openai-compat", "lmstudio"):
        return openai_compat.OpenAICompatGateway(model=model or openai_compat.MODEL, vision_model=vision_model,
                                                 base_url=base_url or openai_compat.BASE_URL, api_key=api_key)
    return ollama.OllamaGateway(model=model or ollama.MODEL, vision_model=vision_model,
                                base_url=base_url or ollama.BASE_URL, api_key=api_key)


def fallback() -> str:
    """The configured second provider, or "" (also "" if it names the same one as the primary)."""
    other = os.environ.get("LLM_FALLBACK", "").strip().lower()
    return "" if other in ("", "none", "off", provider()) else other


def make_gateway(model: str | None = None, vision_model: str | None = None):
    """A gateway for the configured provider; `model`/`vision_model` override the env
    defaults (the per-evidence model choice). With LLM_FALLBACK set it is wrapped so an
    outage of the primary server falls back to the second. A per-evidence model override
    names a model on the *primary* server only; the fallback always uses its own default."""
    primary = _build(provider(), model, vision_model)
    other = fallback()
    if not other:
        return primary
    from app.ai.failover import FailoverGateway

    return FailoverGateway(primary, _build(other, None, None))


def decision_model() -> str:
    return os.environ.get("LLM_DECISION_MODEL", "").strip()


def decision_only(model: str, kind: str = "", base_url: str = ""):
    """A gateway for `model` alone, on the decision server (or the primary one). The decision
    server keeps its own credentials when it has them (LLM_DECISION_API_KEY); unset, it uses
    the provider's own key, as a model on the same server would."""
    kind = kind or os.environ.get("LLM_DECISION_PROVIDER", "").strip().lower() or provider()
    api_key = os.environ.get("LLM_DECISION_API_KEY")
    return _build(kind, model, None, base_url or os.environ.get("LLM_DECISION_BASE_URL", "").strip(),
                  api_key.strip() if api_key is not None else None)


def decision_gateway(extraction=None):
    """The gateway the typed decisions ask (ADR-025). Without LLM_DECISION_MODEL it is the
    extraction gateway itself, exactly as before. With it, a Jev-class model answers, and the
    extraction gateway stands behind it: a decision server that is down costs one failed call,
    not the wrong-document guard. `model` on the result names whichever one answered."""
    extraction = extraction if extraction is not None else make_gateway()
    model = decision_model()
    if not model:
        return extraction
    from app.ai.failover import FailoverGateway
    return FailoverGateway(decision_only(model), extraction)


def list_models() -> list[str]:
    return openai_compat.list_models() if _openai() else ollama.list_models(ollama.BASE_URL)
