"""model output -> JSON -> Pydantic -> normalized ExtractedField per attribute.
Never hands a free-form model answer to the rest of the app.

Malformed JSON gets exactly one repair attempt, then the run is marked
INVALID_OUTPUT and every field comes back null — the caller routes that to
NEEDS_REVIEW rather than guessing.
"""

from __future__ import annotations

import logging

from app.ai.gateway import ModelGateway
from app.ai.prompts import EXTRACTION_PROMPT_VERSION, MAX_DOCUMENT_CHARS, SYSTEM_PROMPT, build_user_prompt
from app.ai.schemas import ExtractedField, ExtractionRun
from app.ai.validators import parse_json_object

logger = logging.getLogger("app.ai.extraction")

REPAIR_SUFFIX = (
    "\n\nYour previous response was not valid JSON. Respond with ONLY the JSON object, "
    "no other text."
)


def _empty(attribute_names: list[str], method: str = "none") -> dict[str, ExtractedField]:
    return {name: ExtractedField(extraction_method=method) for name in attribute_names}


def extract_attributes(
    gateway: ModelGateway,
    text: str,
    attribute_names: list[str],
    extraction_method: str = "native_text",
) -> ExtractionRun:
    provider = getattr(gateway, "provider", "unknown")
    base = ExtractionRun(
        model=getattr(gateway, "model", ""),
        provider=provider,
        prompt_template_version=EXTRACTION_PROMPT_VERSION,
    )
    if not attribute_names:
        return base

    if not gateway.available():
        logger.warning("model_unavailable model=%s — returning null fields", base.model)
        return base.model_copy(update={"fields": _empty(attribute_names), "status": "UNAVAILABLE"})

    if len(text) > MAX_DOCUMENT_CHARS:
        logger.warning("document_truncated chars=%d limit=%d dropped=%d",
                       len(text), MAX_DOCUMENT_CHARS, len(text) - MAX_DOCUMENT_CHARS)

    user_prompt = build_user_prompt(text, attribute_names)
    raw = None
    for attempt in range(2):
        prompt = user_prompt if attempt == 0 else user_prompt + REPAIR_SUFFIX
        try:
            response = gateway.complete_json(SYSTEM_PROMPT, prompt)
        except RuntimeError:
            logger.error("extraction_failed model=%s — returning null fields", base.model)
            return base.model_copy(update={"fields": _empty(attribute_names), "status": "ERROR"})
        raw = parse_json_object(response)
        if raw is not None:
            break

    latency_ms = getattr(gateway, "last_latency_ms", 0)
    if raw is None:
        logger.error("extraction_unparseable model=%s — needs review", base.model)
        return base.model_copy(update={
            "fields": _empty(attribute_names), "status": "INVALID_OUTPUT", "latency_ms": latency_ms,
        })

    fields: dict[str, ExtractedField] = {}
    for name in attribute_names:
        payload = raw.get(name)
        try:
            field = ExtractedField(**payload) if isinstance(payload, dict) else ExtractedField(value=payload)
        except Exception as exc:
            # Present-but-malformed is worth a log line; "not mentioned at all"
            # (payload is None, the common case) is not — same null-field
            # result either way, this only affects what's visible in logs.
            if payload is not None:
                logger.warning("attribute_malformed name=%s payload=%r error=%s", name, payload, exc)
            field = ExtractedField()
        fields[name] = field.model_copy(update={
            "extraction_method": extraction_method if field.value is not None else "none"
        })
    return base.model_copy(update={"fields": fields, "latency_ms": latency_ms})
