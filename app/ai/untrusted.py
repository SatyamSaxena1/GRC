"""Treating document text as untrusted data (ADR-068).

Three small, deterministic steps run before the model sees a document:
  normalise()          strip characters a human reader cannot see
  instruction_lines()  find lines that talk to the model instead of describing the org
  flag_fields()        attach those lines to the extracted facts as warnings

None of this decides a verdict. It makes a hidden instruction visible to the person who
signs; ADR-004's rules and the signer remain the defence.
"""

from __future__ import annotations

import re
import unicodedata

# ponytail: a phrase list, not a classifier — a determined attacker can paraphrase past it.
# That is why the warning is advisory and the source sentence is always shown to the signer.
_INSTRUCTION = re.compile(
    r"ignore (all |any )?(the )?(previous|prior|above|earlier)"
    r"|disregard (all |any )?(the )?(previous|prior|above|earlier)"
    r"|(report|state|record|answer|output|respond|reply|say|write)\s+(that|with|as)\b"
    r"|mark (this|it|the \w+)?\s*(as )?(compliant|passed?|pass|satisfied)"
    r"|set \w+ to \S+ regardless"
    r"|regardless of (the )?(text|document|above)"
    r"|(you|the model|assistant) (must|should|shall|will)\b"
    r"|system prompt|new instructions?",
    re.I,
)
WARNING = "instruction-like text in the document: "


def normalise(text: str) -> str:
    """Drop format/control characters (zero-width, bidi overrides, tags, soft hyphen) but
    keep ordinary whitespace, so quotes still match what a reader sees."""
    return "".join(
        c for c in text
        if c in "\n\t\r " or unicodedata.category(c) not in ("Cf", "Cc", "Co", "Cn")
    )


def instruction_lines(text: str) -> list[str]:
    return [ln.strip()[:200] for ln in text.splitlines() if _INSTRUCTION.search(ln)]


def flag_fields(fields: dict, flagged: list[str]) -> dict:
    """Every stated value gets the warnings: a hidden line may have steered a value without
    being quoted, so the signer is told even when the quote looks innocent."""
    if not flagged:
        return fields
    warnings = [WARNING + ln for ln in flagged[:5]]
    return {n: (f.model_copy(update={"warnings": warnings}) if f.value is not None else f)
            for n, f in fields.items()}
