"""Jev-style typed decisions from a local model: a probability per option,
read from one generated token rather than parsed from prose.

Each option gets a single-letter label; the model is asked for the letter
only, and the next-token log-probabilities of those letters become the
distribution. Suggestions only — nothing here decides a verdict (ADR-004).
Any failure returns {} and the caller behaves exactly as if this were never
called.
"""

from __future__ import annotations

import logging
import math
import string

logger = logging.getLogger("app.ai.decision")

SYSTEM_PROMPT = "You classify compliance material. Answer with a single letter and nothing else."


def choose(gateway, question: str, state: str, options: dict[str, str]) -> dict[str, float]:
    """{option_key: probability} over `options` ({key: description}), or {}."""
    keys = list(options)
    if not keys or len(keys) > len(string.ascii_uppercase):
        return {}
    letters = string.ascii_uppercase[:len(keys)]
    # ponytail: no option-order debiasing — small models favour early letters.
    # Upgrade path: AnyJev-style cyclic shifts (K calls, average per key).
    listing = "\n".join(f"{l}) {k}: {options[k]}" for l, k in zip(letters, keys))
    user = f"{question}\n\n{state}\n\nOptions:\n{listing}\n\nAnswer with the letter only."

    try:
        if not gateway.available():
            return {}
        logprobs = gateway.next_token_logprobs(SYSTEM_PROMPT, user)
    except Exception:  # noqa: BLE001 - a suggestion must never break its caller
        logger.warning("decision_failed model=%s", getattr(gateway, "model", ""))
        return {}

    weights = dict.fromkeys(letters, 0.0)
    for token, logprob in logprobs.items():
        letter = token.strip().upper()
        if letter in weights:
            weights[letter] += math.exp(logprob)  # " A" and "A" are the same answer
    total = sum(weights.values())
    if total == 0:
        return {}
    return {k: weights[l] / total for l, k in zip(letters, keys)}


def top(probabilities: dict[str, float], threshold: float = 0.0) -> str | None:
    """The most likely key if it clears `threshold`, else None."""
    if not probabilities:
        return None
    key = max(probabilities, key=probabilities.get)
    return key if probabilities[key] >= threshold else None
