"""Metrics for the golden evaluation corpus.

Auto-accept precision is the number that gates automation: of the links the
system would accept without a human, how many were actually correct. It matters
more than recall here — a missed pass costs review time, a wrong pass costs an
audit finding.
"""

from __future__ import annotations

from dataclasses import dataclass, field


from app import normalize


def values_match(expected, actual) -> bool:
    """Do the label and the extraction mean the same thing?

    Uses the same normalization the evaluator uses (app/normalize.py), so
    "12 March 2026" counts as 2026-03-12 and "Pass" counts as true. Scoring
    equivalent representations as errors would report discrepancies the system
    does not actually have — and scoring them loosely would hide real ones, so
    the rule is exactly the evaluator's rule, no more and no less.
    """
    return normalize.equivalent(expected, actual)


@dataclass
class Counter:
    hits: int = 0
    total: int = 0

    def add(self, ok: bool) -> None:
        self.hits += 1 if ok else 0
        self.total += 1

    @property
    def score(self) -> float:
        return self.hits / self.total if self.total else 0.0


@dataclass
class Report:
    attribute: Counter = field(default_factory=Counter)
    critical_attribute: Counter = field(default_factory=Counter)
    dates: Counter = field(default_factory=Counter)
    verdicts: Counter = field(default_factory=Counter)
    gap_reasons: Counter = field(default_factory=Counter)
    auto_accept: Counter = field(default_factory=Counter)
    stale_detection: Counter = field(default_factory=Counter)
    documents: int = 0
    failures: list[str] = field(default_factory=list)

    GATES = {
        "auto_accept_precision": 0.95,
        "critical_attribute_accuracy": 0.95,
        "stale_detection_recall": 0.98,
    }

    def summary(self) -> dict:
        return {
            "documents": self.documents,
            "attribute_accuracy": round(self.attribute.score, 4),
            "critical_attribute_accuracy": round(self.critical_attribute.score, 4),
            "date_accuracy": round(self.dates.score, 4),
            "verdict_accuracy": round(self.verdicts.score, 4),
            "gap_reason_accuracy": round(self.gap_reasons.score, 4),
            "auto_accept_precision": round(self.auto_accept.score, 4),
            "stale_detection_recall": round(self.stale_detection.score, 4),
        }

    def gate_results(self) -> dict[str, bool]:
        summary = self.summary()
        return {
            name: summary[name] >= threshold
            for name, threshold in self.GATES.items()
            if getattr(self, _counter_for(name)).total > 0
        }

    def passed(self) -> bool:
        results = self.gate_results()
        return bool(results) and all(results.values())


def _counter_for(gate: str) -> str:
    return {
        "auto_accept_precision": "auto_accept",
        "critical_attribute_accuracy": "critical_attribute",
        "stale_detection_recall": "stale_detection",
    }[gate]
