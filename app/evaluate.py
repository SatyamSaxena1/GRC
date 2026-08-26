"""Cross-framework evidence evaluation.

The LLM extracts facts from a document; this module decides compliance. Keeping
the decision here (deterministic, in Python) is what makes a verdict
reproducible and defensible rather than a chatbot opinion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app import normalize
from app.content.load import Content, DeltaCondition, Requirement

Verdict = str  # PASS | PARTIAL | FAIL


@dataclass(frozen=True)
class Gap:
    kind: str  # MISSING_ATTRIBUTE | DELTA | STALE
    attribute: str
    detail: str
    actual: Any = None
    required: Any = None


@dataclass(frozen=True)
class Link:
    framework: str
    clause: str
    verdict: Verdict
    ucos: tuple[str, ...]
    gaps: tuple[Gap, ...] = field(default=())


def _norm(v: Any) -> Any:
    """Kept as a thin alias: normalization lives in app/normalize.py so the
    evaluator and the evaluation harness cannot drift apart."""
    return normalize.text(v)


def check(condition: DeltaCondition, value: Any) -> bool:
    """Does one extracted value satisfy one delta condition?

    Values arrive as the document stated them ("12 March 2026", "quarterly",
    "Pass"); app/normalize.py converts those to comparable forms. An extraction
    that cannot be interpreted fails the condition — it never passes by accident.
    """
    op, expected = condition.operator, condition.value

    if op == "contains_all":
        # substring match, not exact item equality: real extractions return natural
        # phrases ("remote access through the corporate VPN"), not canonical tokens.
        have = normalize.text(value if isinstance(value, (list, tuple)) else [value])
        return all(any(x in item for item in have) for x in normalize.text(expected))

    if op == "one_of":
        options = [normalize.canonical(o) for o in expected]
        return normalize.canonical(value) in options

    if op in ("==", "!="):
        equal = normalize.canonical(value) == normalize.canonical(expected)
        return equal if op == "==" else not equal

    # Ordered comparison: dates against dates, otherwise numbers (cadence words
    # included). A value that is neither fails rather than raising.
    left_date, right_date = normalize.to_date(value), normalize.to_date(expected)
    if left_date is not None and right_date is not None:
        left, right = left_date.toordinal(), right_date.toordinal()
    else:
        left, right = normalize.to_days(value), normalize.to_days(expected)
        if not isinstance(left, float) or not isinstance(right, float):
            left, right = normalize.to_number(value), normalize.to_number(expected)
        if left is None or right is None:
            return False

    return {">=": left >= right, "<=": left <= right,
            ">": left > right, "<": left < right}[op]


def _required_attributes(req: Requirement, artefact_type: str) -> tuple[str, ...] | None:
    """Attributes this requirement needs from this artefact type, or None if the
    requirement cannot be evidenced by this artefact type at all."""
    matching = [e for e in req.evidence_requirements if e.artefact_type == artefact_type]
    if not matching:
        return None
    return tuple(dict.fromkeys(a for e in matching for a in e.required_attributes))


def _freshness_gaps(
    req: Requirement, attributes: dict[str, Any], as_of: date
) -> list[Gap]:
    """Is this evidence still valid at `as_of`?

    Evidence that was true once is not evidence that it is true now — an ASV scan
    that expired in 2023 does not demonstrate compliance for a 2026 audit. Returns
    a STALE gap when it has expired, and a MISSING_ATTRIBUTE gap when the document
    fails to state a date the requirement needs to judge that.
    """
    validity = req.evidence_validity
    if validity is None:
        return []

    expires_on: date | None = None
    basis = ""

    if validity.expiry_attribute:
        raw = attributes.get(validity.expiry_attribute)
        expires_on = normalize.to_date(raw)
        basis = validity.expiry_attribute
        if raw is not None and expires_on is None:
            return [Gap("STALE", validity.expiry_attribute,
                        f"{validity.expiry_attribute}={raw!r} is not a readable date, so "
                        f"the evidence cannot be shown to be current",
                        actual=raw, required=f"a date on or after {as_of.isoformat()}")]

    if expires_on is None and validity.issued_attribute and validity.max_age_days:
        issued = normalize.to_date(attributes.get(validity.issued_attribute))
        basis = validity.issued_attribute
        if issued is not None:
            expires_on = issued + timedelta(days=validity.max_age_days)

    if expires_on is None:
        if not validity.required:
            return []
        attribute = validity.expiry_attribute or validity.issued_attribute or "expiry_date"
        return [Gap("MISSING_ATTRIBUTE", attribute,
                    f"{attribute} not found in the evidence, so it cannot be shown to be "
                    f"current as at {as_of.isoformat()}")]

    if expires_on < as_of:
        age = (as_of - expires_on).days
        return [Gap("STALE", basis,
                    f"evidence expired {expires_on.isoformat()} ({age} days before "
                    f"{as_of.isoformat()}) and is no longer current",
                    actual=expires_on.isoformat(),
                    required=f"valid on or after {as_of.isoformat()}")]
    return []


def evaluate_requirement(
    req: Requirement, framework: str, attributes: dict[str, Any], artefact_type: str,
    as_of: date | None = None,
) -> Link | None:
    required = _required_attributes(req, artefact_type)
    if required is None:
        return None

    gaps = [
        Gap("MISSING_ATTRIBUTE", attr, f"{attr} not found in the evidence")
        for attr in required
        if attributes.get(attr) is None
    ]
    reported = {(g.kind, g.attribute) for g in gaps}
    gaps += [g for g in _freshness_gaps(req, attributes, as_of or date.today())
             if (g.kind, g.attribute) not in reported]
    for mapping in req.mappings:
        for cond in mapping.delta_conditions:
            value = attributes.get(cond.attribute)
            if value is None:
                continue  # already reported as missing, if it was required
            if not check(cond, value):
                gaps.append(Gap(
                    "DELTA", cond.attribute,
                    f"{cond.attribute}={value!r} fails "
                    f"{cond.attribute} {cond.operator} {cond.value!r}",
                    actual=value, required=cond.value,
                ))

    missing = {g.attribute for g in gaps if g.kind == "MISSING_ATTRIBUTE"}
    if not gaps:
        verdict = "PASS" if any(m.coverage == "FULL" for m in req.mappings) else "PARTIAL"
    elif any(g.kind == "STALE" for g in gaps):
        # Expired evidence is not partial compliance — it demonstrates nothing about
        # the period under audit, so it is rejected outright.
        verdict = "FAIL"
    elif required and missing.issuperset(required):
        verdict = "FAIL"  # nothing was extracted at all
    else:
        verdict = "PARTIAL"

    return Link(
        framework=framework,
        clause=req.clause,
        verdict=verdict,
        ucos=tuple(m.uco for m in req.mappings),
        gaps=tuple(gaps),
    )


def evaluate(
    attributes: dict[str, Any],
    artefact_type: str,
    frameworks: list[str],
    content: Content,
    as_of: date | None = None,
) -> list[Link]:
    """One evidence artefact, every subscribed framework. This is the product.

    `as_of` is the date freshness is judged against — pass the audit period end so
    a verdict means "current for this audit". Defaults to today.
    """
    links = []
    for code in frameworks:
        pack = content.framework(code)
        for req in pack.requirements:
            link = evaluate_requirement(req, code, attributes, artefact_type, as_of)
            if link is not None:
                links.append(link)
    return links
