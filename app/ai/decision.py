"""Jev-style typed decisions from a local model: a probability per option,
read from one generated token rather than parsed from prose.

Each option gets a single-letter label; the model is asked for the letter
only, and the next-token log-probabilities of those letters become the
distribution. Suggestions only — nothing here decides a verdict (ADR-004).
Any failure returns {} and the caller behaves exactly as if this were never
called.
"""

from __future__ import annotations

import hashlib
import json
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
    calls; any failed pass returns {} rather than a partial average, and so does an
    answer whose top option changes with the order (see `stable`).
    """
    return combine(passes(gateway, question, state, options, orders))


def passes(gateway, question: str, state: str, options: dict[str, str],
           orders: int = 1) -> list[dict[str, float]]:
    """One distribution per ordering, keys in `options` order; [] on any failure.
    `choose` is `combine(passes(...))`; evaluation/decisions.py reads the passes themselves
    to measure how often a model's answer depends on the order."""
    keys = list(options)
    if not keys or len(keys) > len(string.ascii_uppercase):
        return []
    try:
        if not gateway.available():
            return []
    except Exception:  # noqa: BLE001 - a suggestion must never break its caller
        return []

    results, models = [], set()
    for ordering in _orderings(keys, max(1, min(orders, len(keys)))):
        probabilities = _one_pass(gateway, question, state, options, ordering)
        if not probabilities:
            return []
        results.append({k: probabilities[k] for k in keys})
        models.add(getattr(gateway, "model", ""))
    # A failover mid-way (app/ai/failover.py) would average two models' answers: no answer.
    return results if len(models) <= 1 else []


def stable(results: list[dict[str, float]]) -> bool:
    """Every ordering put the same option on top. A position-biased model asked in three
    orders can average to anything; an answer that changes with the listing is no answer."""
    return len({top(r) for r in results}) <= 1


def combine(results: list[dict[str, float]]) -> dict[str, float]:
    """The per-option mean of the passes, or {} when there are none or they disagree."""
    if not results:
        return {}
    if not stable(results):
        logger.info("decision_unstable tops=%s", [top(r) for r in results])
        return {}
    return {k: sum(r[k] for r in results) / len(results) for k in results[0]}


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


def digest(text: str) -> str:
    """sha256 of a prompt part. AiRun keeps no document text, only this: anyone holding the
    document can rebuild the state, hash it and check it is the one the model was shown."""
    return hashlib.sha256(text.encode()).hexdigest()


def decision_hash(operation: str, prompt_version: str, model: str, inputs: dict, output: dict) -> str:
    """ADR-025: what was asked of which model, and what it answered, as one hash. No ids and
    no timestamps, so the same question answered the same way hashes the same."""
    body = {"operation": operation, "prompt_version": prompt_version, "model": model,
            "inputs": inputs, "output": output}
    return digest(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str))


def brier(probabilities: dict[str, float], truth: str, options=None) -> float:
    """Multi-class Brier score halved to 0..1: 0 is certain and right, 1 certain and wrong.
    No answer counts as the uniform distribution over `options`: it said nothing."""
    keys = list(options if options is not None else probabilities)
    p = probabilities or {k: 1 / len(keys) for k in keys}
    return sum((p.get(k, 0.0) - (k == truth)) ** 2 for k in keys) / 2
