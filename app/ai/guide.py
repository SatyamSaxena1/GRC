"""Keyed lookup into app/ai/attribute_guide.yaml: the meaning of each attribute
being asked for, rendered for the extraction prompt.

Deliberately not retrieval-by-similarity. The app knows exactly which attributes it
requests (app/service.py::required_attribute_names), so the right entries are a
dictionary lookup: deterministic, free, and identical on every run, which is the
property this exists to protect.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

GUIDE_PATH = Path(__file__).with_name("attribute_guide.yaml")


@lru_cache(maxsize=1)
def load_guide() -> dict[str, dict]:
    return yaml.safe_load(GUIDE_PATH.read_text(encoding="utf-8"))["attributes"]


def _example(pair) -> str:
    text, value = pair
    return f'"{text}" -> {value!r}' if not isinstance(value, str) or not value.startswith(("not ", "do not")) \
        else f'"{text}" -> {value}'


def render_guide(attribute_names: list[str]) -> str:
    """One compact block per requested attribute that has an entry, in the order
    asked (a stable order keeps the prompt, and so the model's behaviour, stable).
    Attributes without an entry are simply not described; they behave as before."""
    if os.environ.get("EXTRACTION_GUIDE", "1").strip().lower() in ("0", "off", "false", "no"):
        return ""  # kill switch: back to bare attribute names without a code deploy
    guide = load_guide()
    lines: list[str] = []
    for name in attribute_names:
        entry = guide.get(name)
        if not entry:
            continue
        parts = [f"- {name}: {entry['means'].strip()}"]
        if entry.get("report_as"):
            parts.append(f"Answer: {' '.join(entry['report_as'].split())}")
        if entry.get("not_this"):
            parts.append("NOT: " + "; ".join(entry["not_this"]))
        if entry.get("examples"):
            parts.append("e.g. " + " | ".join(_example(e) for e in entry["examples"]))
        lines.append(" ".join(parts))
    return "\n".join(lines)
