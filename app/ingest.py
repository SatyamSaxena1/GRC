"""Document -> text (native first, VLM only where needed) -> structured attributes.

The model extracts facts; app/evaluate.py decides compliance. Never conflate
the two.
"""

from __future__ import annotations

import logging

from app.ai.extraction import extract_attributes as _extract_attributes
from app.ai.ollama import OllamaGateway
from app.ai.prompts import EXTRACTION_PROMPT_VERSION
from app.ai.schemas import ExtractionRun
from app.ai.vision import read_page_image
from app import documents

logger = logging.getLogger("app.ingest")

PROMPT_VERSION = EXTRACTION_PROMPT_VERSION


def _gateway() -> OllamaGateway:
    return OllamaGateway()


def current_model_name() -> str:
    return _gateway().model or "ollama:unconfigured"


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
