"""Document -> text (native first, VLM only where needed) -> structured attributes.

The model extracts facts; app/evaluate.py decides compliance. Never conflate
the two.
"""

from __future__ import annotations

import logging

from app.ai.explain import explain_cross_framework_gap as _explain_cross_framework_gap
from app.ai.extraction import extract_attributes as _extract_attributes
from app.ai.extraction import extract_attributes_streaming as _extract_attributes_streaming
from app.ai.extraction import draft_remediation as _draft_remediation
from app.ai.extraction import generate_nutshell as _generate_nutshell
from app.ai.lmstudio import LMStudioGateway
from app.ai.ollama import OllamaGateway
from app.ai.prompts import EXTRACTION_PROMPT_VERSION
from app.ai.schemas import ExtractionRun
from app.ai.vision import read_page_image
from app import documents

logger = logging.getLogger("app.ingest")

PROMPT_VERSION = EXTRACTION_PROMPT_VERSION


def _gateway() -> OllamaGateway:
    return OllamaGateway()


def _tool_gateway() -> LMStudioGateway:
    """Separate from _gateway(): extraction/OCR stay on Ollama, tool-calling
    features (only explain_cross_framework_gap today) go through LM Studio's
    qwen3.8-27b, the model actually trained for tool use."""
    return LMStudioGateway()


def current_model_name() -> str:
    return _gateway().model or "ollama:unconfigured"


def gateway_for(model: str | None, vision_model: str | None = None) -> OllamaGateway:
    """The per-evidence model choice (Evidence.ai_model/ai_vision_model),
    falling back to the server's env-configured default for whichever half
    is unset — the same OllamaGateway the rest of the pipeline already uses,
    just pointed at a different model name."""
    from app.ai.ollama import MODEL as _DEFAULT_MODEL

    return OllamaGateway(model=model or _DEFAULT_MODEL, vision_model=vision_model)


def available_models() -> dict:
    """What this server can actually offer a model picker: the Ollama models
    currently pulled, or an empty list with available=False if Ollama isn't
    reachable — a picker with nothing in it degrades to "use default", it
    never blocks the upload."""
    import requests

    from app.ai.ollama import BASE_URL, MODEL, VISION_MODEL, list_models

    try:
        models = list_models(BASE_URL)
        return {"available": True, "models": models, "default_model": MODEL,
                "default_vision_model": VISION_MODEL}
    except requests.RequestException:
        return {"available": False, "models": [], "default_model": MODEL,
                "default_vision_model": VISION_MODEL}


def extract_text(filename: str, content: bytes) -> str:
    """Native text only. Kept as the simple path used by tests and tooling."""
    return documents.to_text(documents.parse(filename, content))


def read_document(filename: str, content: bytes, gateway=None) -> tuple[str, str]:
    """Return (text, method). Native parse first; VLM only for the pages that
    native parsing could not read, and only when a renderer is available."""
    gateway = gateway or _gateway()
    pages = documents.parse(filename, content)

    if not documents.needs_vision(filename, pages):
        return documents.to_text(pages), "native_text"

    # image evidence: the whole artefact is one image
    extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension in documents.IMAGE_EXTENSIONS:
        text = read_page_image(gateway, content)
        return (f"[page 1]\n{text}", "vlm") if text else ("", "none")

    unreadable = set(documents.pages_needing_vision(pages))
    recovered = 0
    merged: list[documents.DocumentPage] = []
    for page in pages:
        if page.page_number in unreadable:
            image = documents.render_pdf_page(content, page.page_number) if extension == ".pdf" else None
            if image:
                text = read_page_image(gateway, image)
                if text:
                    merged.append(documents.DocumentPage(
                        page_number=page.page_number, text=text, source_type="vlm",
                    ))
                    recovered += 1
                    continue
        merged.append(page)

    logger.info("vision_fallback file=%s pages_needing=%d recovered=%d",
                filename, len(unreadable), recovered)
    return documents.to_text(merged), ("vlm" if recovered else "native_text")


def extract_attributes(
    text: str, attribute_names: list[str], method: str = "native_text", gateway=None
) -> ExtractionRun:
    return _extract_attributes(gateway or _gateway(), text, attribute_names, method)


def extract_attributes_streaming(
    text: str, attribute_names: list[str], method: str = "native_text",
    on_attribute=None, gateway=None,
) -> ExtractionRun:
    return _extract_attributes_streaming(
        gateway or _gateway(), text, attribute_names, method, on_attribute
    )


def generate_nutshell(
    framework: str, clause: str, title: str, verdict: str, gaps: list[dict], fields: dict,
    gateway=None,
) -> str:
    return _generate_nutshell(gateway or _gateway(), framework, clause, title, verdict, gaps, fields)


def draft_remediation(
    framework: str, clause: str, title: str, requirement_text: str, gap: dict, gateway=None
) -> dict:
    return _draft_remediation(
        gateway or _gateway(), framework, clause, title, requirement_text, gap
    )


def explain_cross_framework_gap(links: list[dict], get_clause_text, gateway=None) -> str:
    return _explain_cross_framework_gap(gateway or _tool_gateway(), links, get_clause_text)
