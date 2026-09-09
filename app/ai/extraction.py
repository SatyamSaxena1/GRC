"""model output -> JSON -> Pydantic -> normalized ExtractedField per attribute.
Never hands a free-form model answer to the rest of the app.

Malformed JSON gets exactly one repair attempt, then the run is marked
INVALID_OUTPUT and every field comes back null — the caller routes that to
NEEDS_REVIEW rather than guessing.
"""

from __future__ import annotations

import logging

from app.ai.gateway import ModelGateway
from app.ai.prompts import (
    EXTRACTION_PROMPT_VERSION, MAX_DOCUMENT_CHARS, NUTSHELL_SYSTEM_PROMPT,
    REMEDIATION_SYSTEM_PROMPT, SYSTEM_PROMPT, build_nutshell_prompt,
    build_remediation_prompt, build_user_prompt,
)
from app.ai.schemas import ExtractedField, ExtractionRun
from app.ai.streaming import AttributeScanner
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


def extract_attributes_streaming(
    gateway: ModelGateway, text: str, attribute_names: list[str],
    extraction_method: str = "native_text", on_attribute=None,
) -> ExtractionRun:
    """extract_attributes, but reporting each attribute the moment the model
    finishes writing it (see app/ai/streaming.py).

    Returns exactly what the non-streaming path returns, so callers get the
    same contract; `on_attribute(name, ExtractedField)` is a *preview* hook for
    a watching UI, never the persistence path. Any streaming failure falls back
    to the ordinary blocking call rather than losing the extraction.
    """
    if not attribute_names or not gateway.available():
        return extract_attributes(gateway, text, attribute_names, extraction_method)

    stream = getattr(gateway, "stream_json", None)
    if stream is None:
        return extract_attributes(gateway, text, attribute_names, extraction_method)

    base = ExtractionRun(
        model=getattr(gateway, "model", ""),
        provider=getattr(gateway, "provider", "unknown"),
        prompt_template_version=EXTRACTION_PROMPT_VERSION,
    )
    requested = set(attribute_names)
    scanner = AttributeScanner()
    raw: dict = {}
    try:
        for chunk in stream(SYSTEM_PROMPT, build_user_prompt(text, attribute_names)):
            for name, payload in scanner.feed(chunk):
                if name not in requested or name in raw:
                    continue  # ignore keys the prompt never asked for
                raw[name] = payload
                if on_attribute is not None:
                    on_attribute(name, _field_from(payload, extraction_method))
    except Exception:  # noqa: BLE001 - streaming is an optimisation, never a dependency
        logger.exception("extraction_stream_failed model=%s — falling back", base.model)
        return extract_attributes(gateway, text, attribute_names, extraction_method)

    if not raw:
        logger.warning("extraction_stream_empty model=%s — falling back", base.model)
        return extract_attributes(gateway, text, attribute_names, extraction_method)

    fields = {name: _field_from(raw.get(name), extraction_method) for name in attribute_names}
    return base.model_copy(update={
        "fields": fields, "latency_ms": getattr(gateway, "last_latency_ms", 0),
    })


def _field_from(payload, extraction_method: str) -> ExtractedField:
    """One streamed/parsed attribute payload -> the same ExtractedField shape
    the blocking path produces, including its 'nothing found means method is
    none' rule."""
    try:
        field = ExtractedField(**payload) if isinstance(payload, dict) else ExtractedField(value=payload)
    except Exception:  # noqa: BLE001 - a malformed field is a null field, never a guess
        field = ExtractedField()
    return field.model_copy(update={
        "extraction_method": extraction_method if field.value is not None else "none"
    })


def generate_nutshell(
    gateway: ModelGateway, framework: str, clause: str, title: str, verdict: str,
    gaps: list[dict], fields: dict,
) -> str:
    """One short paragraph narrating a verdict Python already decided — never a
    second opinion (see docs/adr/012-auditor-only-ai-nutshell.md). A degraded
    nicety, not a pipeline dependency: any failure returns "" and the caller
    proceeds exactly as if this were never called."""
    if not gateway.available():
        return ""
    prompt = build_nutshell_prompt(framework, clause, title, verdict, gaps, fields)
    try:
        response = gateway.complete_json(NUTSHELL_SYSTEM_PROMPT, prompt)
    except RuntimeError:
        logger.warning("nutshell_generation_failed model=%s", getattr(gateway, "model", ""))
        return ""
    parsed = parse_json_object(response)
    text = parsed.get("nutshell") if parsed else None
    return text.strip() if isinstance(text, str) else ""


def draft_remediation(
    gateway: ModelGateway, framework: str, clause: str, title: str,
    requirement_text: str, gap: dict,
) -> dict:
    """Suggested wording that would close one gap, plus what an auditor would
    want as proof it actually operates.

    A drafting aid, never an assessment: it cannot change a verdict, close a
    gap, or write anything into the record (see ADR-004 — the model's outputs
    are facts and prose, the evaluator decides compliance). Returns
    {"draft": str, "evidence_needed": [str]}, empty when unavailable.
    """
    empty = {"draft": "", "evidence_needed": []}
    if not gateway.available():
        return empty
    prompt = build_remediation_prompt(framework, clause, title, requirement_text, gap)
    try:
        response = gateway.complete_json(REMEDIATION_SYSTEM_PROMPT, prompt)
    except RuntimeError:
        logger.warning("remediation_draft_failed model=%s", getattr(gateway, "model", ""))
        return empty
    parsed = parse_json_object(response) or {}
    draft = parsed.get("draft")
    needed = parsed.get("evidence_needed")
    return {
        "draft": draft.strip() if isinstance(draft, str) else "",
        "evidence_needed": [str(x) for x in needed][:6] if isinstance(needed, list) else [],
    }
