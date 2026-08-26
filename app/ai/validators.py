"""Model output is untrusted text until it parses and validates."""

from __future__ import annotations

import json
import re


def parse_json_object(text: str) -> dict | None:
    """Best-effort JSON parse: try straight, then strip ```fences``` some models add."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None
