"""Draft wording for a risk (ADR-057): a description and a treatment plan, as plain text for a person to edit.

A drafting aid, never an assessment (ADR-004). The function can return only two strings. It has no way to set
a likelihood, an impact, a score, a band, a treatment or a status, and the router that calls it stores nothing.
"""

from __future__ import annotations

import logging

from app.ai.validators import parse_json_object

logger = logging.getLogger("app.ai.risk_draft")

MAX_CHARS = 2000

SYSTEM_PROMPT = (
    "You help a small company write its risk register in plain words. Given a short risk title and optional "
    "context, write (1) a description: what could go wrong and what it would cost the business, in two or three "
    "sentences, and (2) a treatment plan: three to five concrete steps the company could take to reduce the "
    "risk, one per line. Do not give or imply a score, rating, likelihood, impact, severity or probability, and "
    "do not claim any control already exists. Respond with ONLY a JSON object: "
    '{"description": "...", "treatment_plan": "..."}'
)


def draft_risk(gateway, title: str, context: str = "") -> dict:
    """{"description": str, "treatment_plan": str}; both empty when the model is unavailable or unusable."""
    empty = {"description": "", "treatment_plan": ""}
    if not gateway.available():
        return empty
    prompt = f"Risk title: {title}\n" + (f"Context: {context}\n" if context.strip() else "")
    try:
        response = gateway.complete_json(SYSTEM_PROMPT, prompt)
    except RuntimeError:
        logger.warning("risk_draft_failed model=%s", getattr(gateway, "model", ""))
        return empty
    parsed = parse_json_object(response)
    if not isinstance(parsed, dict):
        return empty
    return {key: (parsed[key].strip()[:MAX_CHARS] if isinstance(parsed.get(key), str) else "") for key in empty}
