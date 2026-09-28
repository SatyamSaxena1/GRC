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


def choose(gateway, question: str, state: str, options: dict[str, str],
           orders: int = 1) -> dict[str, float]:
    """{option_key: probability} over `options` ({key: description}), or {}.

    `orders` > 1 asks that many times with the options reordered (see
    _orderings) and averages per option (permutation averaging, as AnyJev/TypeLLM do): small
    models favour early letters, and a confidence that only holds in one order
    was never real. Measured 2026-09-24 (qwen2.5vl:7b): one PCI attestation
    read SCAN_REPORT at 0.98 in one order and 0.71 reversed. Costs `orders`
    calls; any failed pass returns {} rather than a partial average.
    """
    keys = list(options)
    if not keys or len(keys) > len(string.ascii_uppercase):
        return {}
    try:
        if not gateway.available():
            return {}
    except Exception:  # noqa: BLE001 - a suggestion must never break its caller
        return {}

    passes = max(1, min(orders, len(keys)))
    totals = dict.fromkeys(keys, 0.0)
    for ordering in _orderings(keys, passes):
        probabilities = _one_pass(gateway, question, state, options, ordering)
        if not probabilities:
            return {}
        for k, p in probabilities.items():
            totals[k] += p
    return {k: totals[k] / passes for k in keys}


def _orderings(keys: list[str], passes: int) -> list[list[str]]:
    """Listed order first, then reversed, then cyclic rotations. Reversal is
    second because it is what exposed the bias live: 3 rotations of the PCI
    attestation all read SCAN_REPORT 0.98, only the reversed order read 0.73."""
    orderings = [keys, keys[::-1]]
    shift = 1
    while len(orderings) < passes:
        orderings.append(keys[shift * len(keys) // passes:] + keys[:shift * len(keys) // passes])
        shift += 1
    return orderings[:passes]


def _one_pass(gateway, question: str, state: str, options: dict[str, str],
              keys: list[str]) -> dict[str, float]:
    """One letter-labelled ask with `keys` in this order; {} on any failure."""
    letters = string.ascii_uppercase[:len(keys)]
    listing = "\n".join(f"{l}) {k}: {options[k]}" for l, k in zip(letters, keys))
    user = f"{question}\n\n{state}\n\nOptions:\n{listing}\n\nAnswer with the letter only."
    try:
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
