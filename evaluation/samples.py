"""The demo sample library as an evaluation corpus.

frontend/src/demo/samples.json is the single source of truth for the demo
documents: the UI renders them for a presenter, and this module renders the very
same text (same tokens, same date format) as labelled cases, so every demo
document is also a measurement of how reliably the model reads it. The TS
renderer is frontend/src/demo/samples.ts; samples.json's `golden` block pins
both to the same output.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

SAMPLES_JSON = Path(__file__).resolve().parent.parent / "frontend" / "src" / "demo" / "samples.json"
# Hard-coded names: strftime/locale output would differ between this and the browser.
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
_TOKEN = re.compile(r"\{\{([a-z]+(?::[+-]?\d+)?)\}\}")


def load() -> dict:
    return json.loads(SAMPLES_JSON.read_text(encoding="utf-8"))


def render(value, today: date, runid: str):
    """Replace {{date:±N}} (12 March 2026), {{iso:±N}} (2026-03-12) and {{runid}}."""
    if isinstance(value, str):
        def token(m: re.Match) -> str:
            kind, _, offset = m.group(1).partition(":")
            if kind == "runid":
                return runid
            day = today + timedelta(days=int(offset))
            return f"{day.day} {MONTHS[day.month - 1]} {day.year}" if kind == "date" else day.isoformat()
        return _TOKEN.sub(token, value)
    if isinstance(value, list):
        return [render(v, today, runid) for v in value]
    if isinstance(value, dict):
        return {k: render(v, today, runid) for k, v in value.items()}
    return value


def rendered(today: date | None = None, runid: str = "eval") -> list[dict]:
    """Every sample with tokens resolved and `text` (the document) added."""
    today = today or date.today()
    out = []
    for sample in load()["samples"]:
        r = render(sample, today, runid)
        r["text"] = "\n".join(r["body"]) + "\n"
        out.append(r)
    return out
