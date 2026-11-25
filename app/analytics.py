"""Reuse analytics — the numbers that demonstrate the product's central claim.

"Upload once, comply many" is the pitch; these are the measurements that make it
a fact rather than a slogan. Two questions:

  - Reuse rate: of the control links we hold, how many came from inheritance
    rather than from someone uploading another document?
  - Day-1 readiness: if this organisation subscribed to a new framework right
    now, how much of it would already be satisfied by evidence on file?

Day-1 readiness runs the ordinary evaluator against a framework the org has NOT
subscribed to. That is the whole thesis in one call: nothing special happens for
a new framework, because evidence was never attached to a framework in the first
place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.actor_names import resolve_actors
from app.content.load import Content
from app.evaluate import evaluate
from app.models import AiAssessment, ControlAttestation, DpdpDutyNa, Evidence, EvidenceControlLink, OrgCommitment, Organization

# Hours of effort a single evidence artefact costs to locate, prepare and upload.
# Deliberately conservative; the spec makes this organisation-configurable, so it
# is a parameter rather than a constant baked into the calculation.
DEFAULT_EFFORT_HOURS_PER_ARTEFACT = 1.5

# A verdict counts toward readiness only if it needs no further work.
SATISFIED = "PASS"


@dataclass(frozen=True)
class ReuseStats:
    total_links: int
    distinct_evidence: int
    reused_links: int
    reuse_rate: float          # 0.0 - 1.0
    avoided_uploads: int
    effort_hours_saved: float

    def to_dict(self) -> dict:
        return {
            "total_links": self.total_links,
            "distinct_evidence": self.distinct_evidence,
            "reused_links": self.reused_links,
            "reuse_rate": round(self.reuse_rate, 4),
            "avoided_uploads": self.avoided_uploads,
            "effort_hours_saved": round(self.effort_hours_saved, 1),
        }


def reuse_stats(
    db: Session, org_id: str, effort_hours: float = DEFAULT_EFFORT_HOURS_PER_ARTEFACT
) -> ReuseStats:
    """One artefact satisfying N requirements means N-1 uploads did not happen.

    Counts only CURRENT evidence: a superseded version's links describe work that
    was redone, not work that was saved.
    """
    rows = (
        db.query(EvidenceControlLink.evidence_id)
        .join(Evidence, Evidence.id == EvidenceControlLink.evidence_id)
        .filter(Evidence.org_id == org_id, Evidence.lifecycle_status == "CURRENT",
                Evidence.deleted_at.is_(None))
        # A run whose extraction failed read nothing, so it saved no work (service.py: no_facts).
        .filter(or_(Evidence.status != "NEEDS_REVIEW", Evidence.status_detail.is_(None),
                    Evidence.status_detail.not_like("extraction %")))
        .all()
    )
    total = len(rows)
    distinct = len({evidence_id for (evidence_id,) in rows})
    reused = total - distinct  # the first link per artefact is the upload; the rest are free

    return ReuseStats(
        total_links=total,
        distinct_evidence=distinct,
        reused_links=reused,
        reuse_rate=(reused / total) if total else 0.0,
        avoided_uploads=reused,
        effort_hours_saved=reused * effort_hours,
    )


@dataclass(frozen=True)
class FrameworkReadiness:
    framework: str
    total_requirements: int
    evaluated: int          # requirements the evidence pool could speak to at all
    satisfied: int
    partial: int
    readiness: float        # 0.0 - 1.0, (satisfied + attested) / total
    already_subscribed: bool
    clauses: tuple[dict, ...] = ()
    attested: int = 0       # clauses no rule judges, met by a person's statement in force (ADR-060)
    ai_awaiting: int = 0    # AI-assessed, awaiting a person's confirmation (ADR-069): progress, not met
    ai_confirmed: int = 0   # AI-assessed and confirmed MET by a named person: counted, never as PASS

    def to_dict(self) -> dict:
        return {
            "framework": self.framework,
            "already_subscribed": self.already_subscribed,
            "total_requirements": self.total_requirements,
            "evaluated": self.evaluated,
            "satisfied": self.satisfied,
            "partial": self.partial,
            "attested": self.attested,
            "ai_awaiting": self.ai_awaiting,
            "ai_confirmed": self.ai_confirmed,
            "readiness": round(self.readiness, 4),
            "clauses": list(self.clauses),
        }


# An auditor's verdict, in the rules' PASS / PARTIAL / FAIL vocabulary. Locking overwrites the
# stored link.verdict with the auditor's word (COMPLIANT...), so every count that reads stored
# verdicts folds it through this map; an unknown value passes through rather than 500ing.
AUDITOR_VERDICT = {"COMPLIANT": "PASS", "PARTIALLY_COMPLIANT": "PARTIAL", "NON_COMPLIANT": "FAIL"}


def ai_in_force(db: Session, org_id: str, framework: str) -> dict[str, AiAssessment]:
    """clause -> the AI assessment that counts (ADR-069): the newest CONFIRMED one if any, since a later re-run never
    displaces a confirmation, else the newest unconfirmed proposal that is not NEEDS_REVIEW."""
    rows = (db.query(AiAssessment).filter_by(org_id=org_id, framework=framework)
            .order_by(AiAssessment.created_at.desc()).all())
    found: dict[str, AiAssessment] = {}
    for r in rows:
        if r.confirmed_at is not None:
            found.setdefault(r.clause, r)
    for r in rows:
        if r.clause not in found and r.outcome != "NEEDS_REVIEW":
            found[r.clause] = r
    return found


def duty_na_in_force(db: Session, org_id: str, framework: str) -> dict[str, DpdpDutyNa]:
    """clause -> the duty-level not-applicable mark in force (marked and not reversed)."""
    return {r.clause: r for r in db.query(DpdpDutyNa).filter_by(org_id=org_id, framework=framework, reversed_at=None)}


def framework_readiness(
    db: Session,
    org_id: str,
    framework: str,
    content: Content,
    *,
    subscribed: list[str] | None = None,
    as_of: date | None = None,
) -> FrameworkReadiness:
    """What proportion of `framework` the existing evidence pool already satisfies.

    Every CURRENT artefact is evaluated against the target framework and the best
    verdict per clause wins — an artefact only has to satisfy a requirement once,
    and different artefacts legitimately cover different clauses. The exception is
    whole-estate evidence (WHOLE_ESTATE_TYPES), where the worst verdict wins.
    """
    pack = content.framework(framework)

    # DPDP-only: a clause backed by a connector source the org has declared out
    # of scope (Organization.dpdp_na_sources) reads NOT_APPLICABLE rather than
    # counting forever as NO_EVIDENCE. Four known clauses, already hardcoded
    # strings in app/content/dpdp-2023.yaml — a local dict is proportionate.
    na_clauses: set[str] = set()
    if framework == "DPDP":
        clause_source = {
            "Rule 6 - AWS baseline": "aws",
            "Rule 6 - M365 baseline": "m365",
            "Rule 6 - Google Workspace baseline": "google-workspace",
            "Rule 6 - HRMS baseline": "hrms",
        }
        org = db.get(Organization, org_id)
        na_sources = set(org.dpdp_na_sources) if org else set()
        na_clauses = {clause for clause, source in clause_source.items() if source in na_sources}

    # A duty the org marked not applicable, with a written reason (app/routers/duty_na.py): out of the score too.
    duty_na = duty_na_in_force(db, org_id, framework)
    na_clauses |= set(duty_na)
    na_names = resolve_actors(db, (r.marked_by for r in duty_na.values()))

    # Guidance-only clauses are listed but never scored: not in the total, never attested, never passed.
    guidance = [req for req in pack.requirements if req.guidance_only]
    requirements = [req for req in pack.requirements if req.clause not in na_clauses and not req.guidance_only]
    total = len(requirements)

    evidence_pool = (
        db.query(Evidence)
        .filter_by(org_id=org_id, lifecycle_status="CURRENT", deleted_at=None)
        .all()
    )

    # The org's own thresholds, as the pipeline evaluates with (service._org_commitments).
    org_commitments = {c.attribute: c.value for c in db.query(OrgCommitment).filter_by(org_id=org_id)}

    per_clause: dict[str, list[tuple[str, str, bool]]] = {}
    for evidence in evidence_pool:
        attributes = evidence.attribute_values()
        for link in evaluate(attributes, evidence.artefact_type, [framework], content, as_of,
                             org_commitments):
            if link.clause in na_clauses:
                continue
            per_clause.setdefault(link.clause, []).append((link.verdict, evidence.artefact_type, True))
    best = {clause: combine_verdicts(v) for clause, v in per_clause.items()}

    # An auditor's lock is the verdict of record: it overrides what the rules computed, exactly as
    # the controls rollup (routers/analytics.best_verdict) counts it. Without this a locked
    # COMPLIANT over a FAIL control read PASS there and 0% here.
    locked: dict[str, list[tuple[str, str, bool]]] = {}
    for link, artefact_type in (
        db.query(EvidenceControlLink, Evidence.artefact_type)
        .join(Evidence, Evidence.id == EvidenceControlLink.evidence_id)
        .filter(Evidence.org_id == org_id, Evidence.lifecycle_status == "CURRENT",
                Evidence.deleted_at.is_(None), EvidenceControlLink.framework == framework,
                EvidenceControlLink.locked_by_engagement_id.is_not(None))
    ):
        if link.clause not in na_clauses:
            locked.setdefault(link.clause, []).append(
                (AUDITOR_VERDICT.get(link.verdict, link.verdict), artefact_type, True))
    best.update({clause: combine_verdicts(v) for clause, v in locked.items()})

    satisfied = sum(1 for v in best.values() if v == SATISFIED)
    partial = sum(1 for v in best.values() if v == "PARTIAL")

    # A rule-less clause is never in `best` (no evidence is matched to it); a person's statement in force
    # reads ATTESTED. Counted toward readiness, never as satisfied by the rules (ADR-060).
    rule_less = {req.clause for req in requirements if req.attestation_only}
    today = as_of or date.today()
    attested_clauses = {
        a.clause for a in db.query(ControlAttestation).filter_by(org_id=org_id, framework=framework, revoked_at=None)
        if a.clause in rule_less and a.valid_until >= today}

    # AI-assessed (ADR-069): only a clause the pack marks assessable, never one a rule already passed. A confirmed MET
    # counts toward readiness; an unconfirmed proposal is shown as its own bucket and counts as nothing yet.
    assessable = {req.clause for req in requirements if req.ai_assessable}
    ai_rows = {c: r for c, r in ai_in_force(db, org_id, framework).items()
               if c in assessable and best.get(c) != SATISFIED}
    ai_confirmed = {c for c, r in ai_rows.items() if r.confirmed_at is not None and r.confirmed_outcome == "MET"}
    ai_awaiting = {c for c, r in ai_rows.items() if r.confirmed_at is None}

    def verdict_of(clause: str) -> str:
        if clause in attested_clauses:
            return "ATTESTED"
        return "AI_ASSESSED" if clause in ai_rows else best.get(clause, "NO_EVIDENCE")

    def ai_state(clause: str) -> str | None:
        r = ai_rows.get(clause)
        return None if r is None else ("confirmed" if r.confirmed_at is not None else "awaiting")

    return FrameworkReadiness(
        framework=framework,
        total_requirements=total,
        evaluated=len(best),
        satisfied=satisfied,
        partial=partial,
        readiness=((satisfied + len(attested_clauses) + len(ai_confirmed)) / total) if total else 0.0,
        attested=len(attested_clauses),
        ai_awaiting=len(ai_awaiting),
        ai_confirmed=len(ai_confirmed),
        already_subscribed=framework in (subscribed or []),
        clauses=tuple(
            {"clause": req.clause, "title": req.title, "attestation_only": req.attestation_only,
             "ai_assessable": req.ai_assessable, "ai_state": ai_state(req.clause),
             "verdict": verdict_of(req.clause)}
            for req in requirements
        ) + tuple(
            {"clause": req.clause, "title": req.title, "attestation_only": True, "guidance_only": True,
             "verdict": "GUIDANCE"}
            for req in guidance
        ) + tuple(
            {"clause": clause, "title": next((r.title for r in pack.requirements if r.clause == clause), clause),
             "verdict": "NOT_APPLICABLE",
             **({"na_id": duty_na[clause].id, "na_reason": duty_na[clause].reason, "na_by": na_names.get(duty_na[clause].marked_by, duty_na[clause].marked_by),
                 "na_at": duty_na[clause].marked_at.isoformat()} if clause in duty_na else {})}
            for clause in sorted(na_clauses)
        ),
    )


_RANK = {"NO_EVIDENCE": 0, "FAIL": 1, "PARTIAL": 2, "PASS": 3}


# Evidence types where each artefact covers a different part of the estate (one change-control
# snapshot per platform: GitHub, GitLab, Bitbucket), so every one must pass. For these a clause
# takes the WORST current verdict; taking the best would let a clean GitHub snapshot hide a
# failing GitLab one. Every other type is alternative evidence for the same requirement, where
# satisfying it once is enough.
WHOLE_ESTATE_TYPES = {"CHANGE_CONTROL_SNAPSHOT", "KEY_HEALTH_SNAPSHOT"}


def combine_verdicts(verdicts: list[tuple[str, str | None, bool]]) -> str:
    """One clause verdict from (verdict, artefact_type, is_current) triples. Current
    whole-estate evidence decides by its worst verdict; otherwise the best verdict wins."""
    whole = [v for v, kind, current in verdicts if kind in WHOLE_ESTATE_TYPES and current]
    if whole:
        return min(whole, key=lambda v: _RANK.get(v, 0))
    rest = [v for v, kind, _ in verdicts if kind not in WHOLE_ESTATE_TYPES]
    return max(rest, key=lambda v: _RANK.get(v, 0)) if rest else "NO_EVIDENCE"


def _better(current: str | None, candidate: str) -> str:
    if current is None:
        return candidate
    return candidate if _RANK.get(candidate, 0) > _RANK.get(current, 0) else current
