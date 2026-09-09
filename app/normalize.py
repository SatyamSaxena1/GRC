"""Deterministic normalization of extracted values.

A model reports what the document says ("12 March 2026", "quarterly", "Pass").
Turning those into comparable values is a fixed mapping, so it belongs in code —
never in the prompt, and never as a model judgement. Both the evaluator and the
evaluation harness use this module, so they agree on what "the same value" means.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

CADENCE_DAYS = {
    "daily": 1, "weekly": 7, "fortnightly": 14, "monthly": 30, "bimonthly": 60,
    "quarterly": 90, "semi-annually": 182, "semiannually": 182, "biannually": 182,
    "half-yearly": 182, "annually": 365, "annual": 365, "yearly": 365,
    "every 6 months": 182, "every six months": 182, "every 3 months": 90,
    "every three months": 90,
}

BOOL_WORDS = {
    "pass": True, "passing": True, "passed": True, "compliant": True, "true": True,
    "yes": True, "y": True, "required": True, "enabled": True,
    "fail": False, "failing": False, "failed": False, "non-compliant": False,
    "noncompliant": False, "false": False, "no": False, "n": False,
    "not required": False, "disabled": False,
}

_DATE_FORMATS = (
    "%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y",
    "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y",
)

# Checkbox/tick glyphs a real form-style report embeds right next to a value
# ("Compliance Status: ☒ Pass") — genuine, correctly-decoded Unicode, not
# an encoding bug (see the real Aurionpro ASV executive-summary report this
# was found against). They carry no information the word itself doesn't
# already state, but break an exact BOOL_WORDS match — stripped before lookup.
_MARKER_CHARS = "☐☑☒✓✔✗✘●•"
_MARKER_TABLE = {ord(c): None for c in _MARKER_CHARS}


def text(value: Any) -> Any:
    """Lowercase/strip strings, recursively for sequences. Other types untouched."""
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, (list, tuple)):
        return [text(v) for v in value]
    return value


def to_bool(value: Any) -> Any:
    """'Pass' -> True, 'Pass ☒' -> True. Returns the input unchanged when it is
    not a boolean word."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned in BOOL_WORDS:
            return BOOL_WORDS[cleaned]
        stripped = cleaned.translate(_MARKER_TABLE).strip()
        return BOOL_WORDS.get(stripped, value)
    return value


def to_days(value: Any) -> Any:
    """'quarterly' -> 90. Returns the input unchanged when it is not a cadence."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        key = value.strip().lower()
        if key in CADENCE_DAYS:
            return float(CADENCE_DAYS[key])
        match = re.fullmatch(r"(\d+)\s*(?:days?)?", key)
        if match:
            return float(match.group(1))
    return value


def to_date(value: Any) -> date | None:
    """Parse the date formats real documents use. None when it is not a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", value.strip(), flags=re.IGNORECASE)
    cleaned = cleaned.replace(",", "")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def to_number(value: Any) -> float | None:
    """A number, including one stated in prose ('8 characters' -> 8.0)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if match:
            return float(match.group())
    return None


def canonical(value: Any) -> Any:
    """Best comparable form: dates as ISO, cadences/numbers as floats, boolean
    words as bools, everything else lowercased text."""
    parsed_date = to_date(value)
    if parsed_date is not None:
        return parsed_date.isoformat()

    as_bool = to_bool(value)
    if isinstance(as_bool, bool):
        return as_bool

    as_days = to_days(value)
    if isinstance(as_days, float):
        return as_days

    return text(value)


def equivalent(expected: Any, actual: Any) -> bool:
    """True when two representations mean the same thing."""
    if canonical(expected) == canonical(actual):
        return True
    if isinstance(expected, (list, tuple)) and isinstance(actual, (list, tuple)):
        have = text(actual)
        return all(any(e in item for item in have) for e in text(expected))
    return False
