"""Evidence Quality Score — deterministic, weighted, and always explained.

Verdicts answer "does this evidence satisfy the requirement?". The quality score
answers a different question: "how good is this artefact as evidence at all?" A
policy can pass every delta condition and still be weak evidence — unsigned,
undated, or covering half the estate.

Every dimension is computed from facts already extracted, so the score is
reproducible and each point of it can be pointed at. The model is never asked for
a number: an LLM rating evidence 3.2/5 produces an unfalsifiable figure, which is
worse than no figure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app import normalize

MAX_SCORE = 5.0

# Weights per the specification. Must sum to 1.0 — asserted at import.
WEIGHTS = {
    "completeness": 0.25,
    "freshness": 0.20,
    "authenticity": 0.20,
    "scope_coverage": 0.15,
    "legibility": 0.10,
    "corroboration": 0.10,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "quality weights must sum to 1.0"

APPROVAL_ATTRIBUTES = ("approver_name", "approver_role", "approval_date", "signature_present")
SCOPE_ATTRIBUTES = ("systems_covered", "entities_covered", "locations_covered", "scope_statement")


@dataclass(frozen=True)
class Dimension:
    name: str
    score: float          # 0.0 - 1.0
    weight: float
    reason: str

    @property
    def contribution(self) -> float:
        return self.score * self.weight


@dataclass(frozen=True)
class QualityScore:
    score: float                       # 0.0 - 5.0
    dimensions: tuple[Dimension, ...] = field(default=())

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(d.reason for d in self.dimensions)

    def explain(self) -> str:
        lines = [f"{self.score} / {MAX_SCORE}", "", "Reason:"]
        lines += [f"- {d.reason}" for d in self.dimensions]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "max_score": MAX_SCORE,
            "dimensions": [
                {"name": d.name, "score": round(d.score, 3), "weight": d.weight,
                 "reason": d.reason}
                for d in self.dimensions
            ],
        }


def _completeness(attributes: dict, requested: list[str]) -> Dimension:
    if not requested:
        return Dimension("completeness", 1.0, WEIGHTS["completeness"],
                         "no attributes were required of this artefact")
    found = [n for n in requested if attributes.get(n) is not None]
    missing = [n for n in requested if attributes.get(n) is None]
    reason = (f"all {len(requested)} expected attributes were found" if not missing
              else f"{len(found)} of {len(requested)} expected attributes found; "
                   f"missing {', '.join(sorted(missing)[:4])}")
    return Dimension("completeness", len(found) / len(requested),
                     WEIGHTS["completeness"], reason)


def _freshness(attributes: dict, as_of: date) -> Dimension:
    """Graded, unlike the pass/fail staleness rule: evidence approaching expiry is
    worth flagging before it lapses."""
    expiry = normalize.to_date(attributes.get("next_review_date")
                               or attributes.get("scan_expiry_date")
                               or attributes.get("expiry_date"))
    issued = normalize.to_date(attributes.get("approval_date")
                               or attributes.get("effective_date")
                               or attributes.get("scan_completed_date"))

    if expiry is not None:
        days_left = (expiry - as_of).days
        if days_left < 0:
            return Dimension("freshness", 0.0, WEIGHTS["freshness"],
                             f"expired {abs(days_left)} days ago ({expiry.isoformat()})")
        if days_left < 30:
            return Dimension("freshness", 0.5, WEIGHTS["freshness"],
                             f"expires in {days_left} days ({expiry.isoformat()})")
        return Dimension("freshness", 1.0, WEIGHTS["freshness"],
                         f"current until {expiry.isoformat()}")

    if issued is not None:
        age = (as_of - issued).days
        if age > 365:
            return Dimension("freshness", 0.25, WEIGHTS["freshness"],
                             f"no expiry stated and the document is {age} days old")
        return Dimension("freshness", 0.75, WEIGHTS["freshness"],
                         f"no expiry stated; issued {age} days ago")

    return Dimension("freshness", 0.0, WEIGHTS["freshness"],
                     "no issue or expiry date found, so currency cannot be established")


def _authenticity(attributes: dict) -> Dimension:
    signed = bool(attributes.get("signature_present"))
    has_approver = any(attributes.get(a) for a in ("approver_name", "approver_role"))
    has_date = attributes.get("approval_date") is not None

    score, notes = 0.0, []
    if has_approver:
        score += 0.5
        notes.append("approver is identifiable")
    else:
        notes.append("no approver identified")
    if has_date:
        score += 0.3
        notes.append("approval date recorded")
    else:
        notes.append("no approval date")
    if signed:
        score += 0.2
        notes.append("signature present")
    else:
        notes.append("signature not found")

    return Dimension("authenticity", min(score, 1.0), WEIGHTS["authenticity"],
                     "; ".join(notes))


def _as_list(value) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _scope_coverage(attributes: dict, required_scope: list[str] | None) -> Dimension:
    stated = [a for a in SCOPE_ATTRIBUTES if attributes.get(a)]
    if not stated:
        return Dimension("scope_coverage", 0.0, WEIGHTS["scope_coverage"],
                         "the document does not state what it covers")

    if not required_scope:
        return Dimension("scope_coverage", 1.0, WEIGHTS["scope_coverage"],
                         f"scope stated ({', '.join(stated)})")

    covered = normalize.text(
        [v for a in SCOPE_ATTRIBUTES for v in _as_list(attributes.get(a))]
    )
    hits = [s for s in required_scope
            if any(normalize.text(s) in item for item in covered)]
    missing = [s for s in required_scope if s not in hits]
    reason = ("scope covers everything required" if not missing
              else f"scope does not include {', '.join(missing)}")
    return Dimension("scope_coverage", len(hits) / len(required_scope),
                     WEIGHTS["scope_coverage"], reason)


def _legibility(extraction_methods: dict[str, str], native_readable: bool = False) -> Dimension:
    """How reliably the document could be read. Native text is exact; OCR is not."""
    methods = [m for m in extraction_methods.values() if m and m != "none"]
    if not methods:
        if native_readable:
            # The document parsed to clean text — it *is* legible. That no
            # attribute values came back (the model found none, or was
            # unavailable) is a completeness / availability question, told by
            # the evidence status, not a reason to score a readable document as
            # unreadable.
            return Dimension("legibility", 1.0, WEIGHTS["legibility"],
                             "machine-readable text extracted directly")
        return Dimension("legibility", 0.0, WEIGHTS["legibility"],
                         "no text could be extracted from the document")
    vlm = sum(1 for m in methods if m == "vlm")
    if vlm == 0:
        return Dimension("legibility", 1.0, WEIGHTS["legibility"],
                         "machine-readable text extracted directly")
    return Dimension("legibility", 1.0 - (vlm / len(methods)) * 0.4, WEIGHTS["legibility"],
                     f"{vlm} of {len(methods)} values read via OCR rather than a text layer")


def _corroboration(attributes: dict, sources: dict[str, list]) -> Dimension:
    """Values that cite a source passage can be checked by a human; values that do
    not are assertions."""
    valued = [n for n, v in attributes.items() if v is not None]
    if not valued:
        return Dimension("corroboration", 0.0, WEIGHTS["corroboration"],
                         "nothing was extracted, so nothing is corroborated")
    cited = [n for n in valued if sources.get(n)]
    reason = (f"all {len(valued)} extracted values cite a supporting passage"
              if len(cited) == len(valued)
              else f"{len(cited)} of {len(valued)} extracted values cite a supporting passage")
    return Dimension("corroboration", len(cited) / len(valued),
                     WEIGHTS["corroboration"], reason)


def score_evidence(
    attributes: dict,
    requested_attributes: list[str],
    *,
    sources: dict[str, list] | None = None,
    extraction_methods: dict[str, str] | None = None,
    required_scope: list[str] | None = None,
    as_of: date | None = None,
    native_readable: bool = False,
) -> QualityScore:
    """Score one evidence artefact. Deterministic: same inputs, same score.

    `native_readable` says the document itself yielded readable text (see
    app/documents.py) even if the analysis model then extracted nothing — so a
    readable file is not scored as illegible just because the model was down.
    """
    as_of = as_of or date.today()
    dimensions = (
        _completeness(attributes, requested_attributes),
        _freshness(attributes, as_of),
        _authenticity(attributes),
        _scope_coverage(attributes, required_scope),
        _legibility(extraction_methods or {}, native_readable),
        _corroboration(attributes, sources or {}),
    )
    return QualityScore(
        score=round(sum(d.contribution for d in dimensions) * MAX_SCORE, 2),
        dimensions=dimensions,
    )
