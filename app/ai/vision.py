"""VLM fallback: read text off pages native parsing could not.

Only pages that failed the deterministic readability check are sent — the whole
document is never rasterized by default.
"""

from __future__ import annotations

import logging

from app.ai.prompts import OCR_PROMPT_VERSION, OCR_SYSTEM_PROMPT

logger = logging.getLogger("app.ai.vision")


def read_page_image(gateway, image_png: bytes) -> str:
    """Transcribe one page image. Returns '' when the model is unavailable."""
    if not gateway.available():
        logger.warning("vision_unavailable model=%s", gateway.model)
        return ""
    try:
        return gateway.complete_vision(OCR_SYSTEM_PROMPT, "Transcribe this page.", [image_png])
    except RuntimeError as exc:
        logger.error("vision_failed model=%s error=%s", gateway.model, exc)
        return ""


__all__ = ["read_page_image", "OCR_PROMPT_VERSION"]
