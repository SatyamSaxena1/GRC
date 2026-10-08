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
from app.content.load import Content, DeltaCondition, EvidenceRequirement, EvidenceValidity, Requirement

Verdict = str  # PASS | PARTIAL | FAIL

# Bump whenever this module's logic changes what a verdict or gap would be. Stamped on
# every verdict (ADR-022) and pinned by tests/test_verdict_provenance.py's engine
# fingerprint, which fails until the bump and the new fingerprint land together.
ENGINE_VERSION = "1"


@dataclass(frozen=True)
class Gap:
    kind: str  # MISSING_ATTRIBUTE | DELTA | STALE
    attribute: str
    detail: str
    actual: Any = None
    required: Any = None


@dataclass(frozen=True)
class Check:
    """One thing a requirement was judged against, and what the document gave.

    `operator` is "present" for a plain does-the-document-state-it check, else the
    DeltaCondition operator with its bound in `expected`. This is what lets a PASS
    say *what* it passed on, not just that nothing was wrong."""
    attribute: str
    operator: str
    expected: Any
    actual: Any
    met: bool


@dataclass(frozen=True)
class Link:
    framework: str
    clause: str
    verdict: Verdict
    ucos: tuple[str, ...]
    gaps: tuple[Gap, ...] = field(default=())
    checked: tuple[Check, ...] = field(default=())


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


def _matching_evidence_requirements(
    req: Requirement, artefact_type: str
) -> list[EvidenceRequirement]:
    return [e for e in req.evidence_requirements if e.artefact_type == artefact_type]


def _required_attributes(matching: list[EvidenceRequirement]) -> tuple[str, ...] | None:
    """Attributes this requirement needs from this artefact type, or None if the
    requirement cannot be evidenced by this artefact type at all."""
    if not matching:
        return None
    return tuple(dict.fromkeys(a for e in matching for a in e.required_attributes))


def _validity_for(matching: list[EvidenceRequirement]) -> EvidenceValidity | None:
    """A clause can list more than one entry for the same artefact type (see
    nist-csf-2.0's IAM policy clause); evidence_validity lives on whichever one
    declares it — first match, same as the union `_required_attributes` already
    takes across all of them."""
    return next((e.evidence_validity for e in matching if e.evidence_validity is not None), None)


def _freshness_gaps(
    validity: EvidenceValidity | None, attributes: dict[str, Any], as_of: date,
    org_commitments: dict[str, Any],
) -> list[Gap]:
    """Is this evidence still valid at `as_of`?

    Evidence that was true once is not evidence that it is true now — an ASV scan
    that expired in 2023 does not demonstrate compliance for a 2026 audit. Returns
    a STALE gap when it has expired, and a MISSING_ATTRIBUTE gap when the document
    fails to state a date the requirement needs to judge that.

    When `org_defined_max_age_attribute` is set, the ceiling is not a framework
    constant but this org's own stated commitment (an "organization-defined
    parameter" — see docs/adr/013-organization-defined-commitments.md): a missing
    or unusable commitment is its own gap, NO_ORG_COMMITMENT, rather than a silent
    pass or a confusing generic MISSING_ATTRIBUTE.
    """
    if validity is None:
        return []

    max_age_days = validity.max_age_days
    commitment_note = ""
    if validity.org_defined_max_age_attribute:
        attr = validity.org_defined_max_age_attribute
        commitment = org_commitments.get(attr)
        if commitment is None:
            return [Gap("NO_ORG_COMMITMENT", attr,
                        f"the organisation's policy does not yet state a required "
                        f"{attr.replace('_', ' ')}; this control cannot be evaluated "
                        f"against a commitment that has not been made")]
        # to_days first: a policy commitment is as likely to say "quarterly" as
        # "90 days" (same words check() already accepts for DeltaConditions).
        resolved = normalize.to_days(commitment)
        if not isinstance(resolved, float):
            resolved = normalize.to_number(commitment)
        if resolved is None:
            return [Gap("NO_ORG_COMMITMENT", attr,
                        f"the organisation's policy states {attr}={commitment!r}, which "
                        f"is not a usable number of days")]
        max_age_days = int(resolved)
        commitment_note = f" (per the organisation's own policy commitment of {max_age_days} days)"

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

    if expires_on is None and validity.issued_attribute and max_age_days:
        issued = normalize.to_date(attributes.get(validity.issued_attribute))
        basis = validity.issued_attribute
        if issued is not None:
            expires_on = issued + timedelta(days=max_age_days)

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
                    required=f"valid on or after {as_of.isoformat()}{commitment_note}")]
    return []


def consulted_attributes(req: Requirement, artefact_type: str) -> tuple[set[str], set[str]]:
    """Every evidence attribute and every org commitment `evaluate_requirement` can read
    for this requirement and artefact type. Recording just these makes a verdict
    replayable without copying the whole document's extraction (ADR-022)."""
    matching = _matching_evidence_requirements(req, artefact_type)
    attrs = set(_required_attributes(matching) or ())
    attrs |= {c.attribute for m in req.mappings for c in m.delta_conditions}
    commitments: set[str] = set()
    validity = _validity_for(matching)
    if validity is not None:
        attrs |= {a for a in (validity.expiry_attribute, validity.issued_attribute) if a}
        if validity.org_defined_max_age_attribute:
            commitments.add(validity.org_defined_max_age_attribute)
    return attrs, commitments


def checks_for(req: Requirement, attributes: dict[str, Any], artefact_type: str) -> tuple[Check, ...]:
    """Every attribute presence and delta condition this requirement is judged on.

    Pure and independent of `as_of`/commitments (freshness is not an attribute
    check), so the API can rebuild it at read time from an evidence row's stored
    attributes — they are never edited in place, a correction is a new version.
    A delta check subsumes the bare presence check for the same attribute.
    """
    required = _required_attributes(_matching_evidence_requirements(req, artefact_type)) or ()
    deltas: dict[tuple, Check] = {}
    for mapping in req.mappings:
        for cond in mapping.delta_conditions:
            value = attributes.get(cond.attribute)
            if value is not None:
                deltas.setdefault(
                    (cond.attribute, cond.operator, repr(cond.value)),
                    Check(cond.attribute, cond.operator, cond.value, value, check(cond, value)),
                )
    judged = {c.attribute for c in deltas.values()}
    stated = [Check(a, "present", None, attributes.get(a), attributes.get(a) is not None)
              for a in required if a not in judged]
    return tuple(stated) + tuple(deltas.values())


def evaluate_requirement(
    req: Requirement, framework: str, attributes: dict[str, Any], artefact_type: str,
    as_of: date | None = None, org_commitments: dict[str, Any] | None = None,
) -> Link | None:
    matching = _matching_evidence_requirements(req, artefact_type)
    required = _required_attributes(matching)
    if required is None:
        return None

    gaps = [
        Gap("MISSING_ATTRIBUTE", attr, f"{attr} not found in the evidence")
        for attr in required
        if attributes.get(attr) is None
    ]
    reported = {(g.kind, g.attribute) for g in gaps}
    gaps += [g for g in _freshness_gaps(_validity_for(matching), attributes,
                                        as_of or date.today(), org_commitments or {})
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
        checked=checks_for(req, attributes, artefact_type),
    )


def org_defined_attributes(content: Content, framework: str, clause: str) -> set[str]:
    """Which organization-defined attribute(s), if any, a clause's freshness check
    depends on — the set of OrgCommitment attributes a change to would make this
    clause's links stale. Pure content-schema lookup, no DB: the DB-touching half
    (comparing OrgCommitment.updated_at against a link's evaluated_at) lives in
    app/service.py::link_commitment_stale, which calls this first.
    """
    try:
        pack = content.framework(framework)
    except KeyError:
        return set()
    req = next((r for r in pack.requirements if r.clause == clause), None)
    if req is None:
        return set()
    return {
        er.evidence_validity.org_defined_max_age_attribute
        for er in req.evidence_requirements
        if er.evidence_validity is not None and er.evidence_validity.org_defined_max_age_attribute
    }


def evaluate(
    attributes: dict[str, Any],
    artefact_type: str,
    frameworks: list[str],
    content: Content,
    as_of: date | None = None,
    org_commitments: dict[str, Any] | None = None,
) -> list[Link]:
    """One evidence artefact, every subscribed framework. This is the product.

    `as_of` is the date freshness is judged against — pass the audit period end so
    a verdict means "current for this audit". Defaults to today.

    `org_commitments` is this org's own stated values for organization-defined
    parameters (see docs/adr/013-organization-defined-commitments.md) — a plain
    `{attribute: value}` mapping, the same shape `Evidence.attribute_values()`
    already produces. Defaults to no commitments, which only matters to a
    requirement that actually declares `org_defined_max_age_attribute`.
    """
    links = []
    for code in frameworks:
        pack = content.framework(code)
        for req in pack.requirements:
            link = evaluate_requirement(req, code, attributes, artefact_type, as_of,
                                        org_commitments)
            if link is not None:
                links.append(link)
    return links
