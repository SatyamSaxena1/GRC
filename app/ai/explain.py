"""Cross-framework gap explanations: why the same evidence got a different
verdict under two frameworks. A drafting/narration aid, same boundary as
draft_remediation/generate_nutshell (app/ai/extraction.py) — it explains a
verdict Python already decided (ADR-004), it never states a different one.

Uses tool-calling (app/ai/lmstudio.py's complete_with_tools) so the model
pulls in a clause's full text only when it actually needs it, instead of
every framework's text being stuffed into the prompt up front."""

from __future__ import annotations

import logging
from typing import Callable, Protocol

from app.ai.prompts import (
    EXPLAIN_SYSTEM_PROMPT, GET_CLAUSE_TEXT_TOOL, build_explain_prompt,
)
from app.ai.validators import parse_json_object

logger = logging.getLogger("app.ai.explain")


class ToolCallingGateway(Protocol):
    def available(self) -> bool: ...
    def complete_with_tools(
        self, system: str, user: str, tools: list[dict],
        executor: Callable[[str, dict], dict], max_rounds: int = 4,
    ) -> str: ...


def explain_cross_framework_gap(
    gateway: ToolCallingGateway, links: list[dict], get_clause_text: Callable[[str, str], tuple[str, str]],
) -> str:
    """`links` is [{"framework", "clause", "verdict"}, ...] for one evidence
    item. `get_clause_text(framework, clause) -> (title, text)` is the same
    lookup app/routers/controls.py's _requirement_text uses.

    Degrades to "" on any failure — never raises into the caller, same
    contract as every other AI call in this codebase."""
    if not gateway.available() or len(links) < 2:
        return ""

    allowed = {(l["framework"], l["clause"]) for l in links}

    def executor(name: str, args: dict) -> dict:
        if name != "get_clause_text":
            return {"error": f"unknown tool {name}"}
        framework, clause = args.get("framework"), args.get("clause")
        # Only let the model look up clauses that are actually part of this
        # explanation — never an arbitrary framework/clause it names.
        if (framework, clause) not in allowed:
            return {"error": "clause not part of this evidence item's evaluations"}
        title, text = get_clause_text(framework, clause)
        return {"title": title, "text": text or "(not available)"}

    prompt = build_explain_prompt(links)
    try:
        response = gateway.complete_with_tools(
            EXPLAIN_SYSTEM_PROMPT, prompt, [GET_CLAUSE_TEXT_TOOL], executor,
        )
    except Exception:  # noqa: BLE001 - a narration aid must never break the request it's on
        logger.exception("cross_framework_explain_failed model=%s", getattr(gateway, "model", ""))
        return ""

    parsed = parse_json_object(response)
    text = parsed.get("explanation") if parsed else None
    return text.strip() if isinstance(text, str) else ""
