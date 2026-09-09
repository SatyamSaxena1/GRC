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

from sqlalchemy.orm import Session

from app.content.load import Content
from app.evaluate import evaluate
from app.models import Evidence, EvidenceControlLink

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
    readiness: float        # 0.0 - 1.0, satisfied / total
    already_subscribed: bool
    clauses: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {
            "framework": self.framework,
            "already_subscribed": self.already_subscribed,
            "total_requirements": self.total_requirements,
            "evaluated": self.evaluated,
            "satisfied": self.satisfied,
            "partial": self.partial,
            "readiness": round(self.readiness, 4),
            "clauses": list(self.clauses),
        }


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
    and different artefacts legitimately cover different clauses.
    """
    pack = content.framework(framework)
    total = len(pack.requirements)

    evidence_pool = (
        db.query(Evidence)
        .filter_by(org_id=org_id, lifecycle_status="CURRENT", deleted_at=None)
        .all()
    )

    best: dict[str, str] = {}
    for evidence in evidence_pool:
        attributes = evidence.attribute_values()
        for link in evaluate(attributes, evidence.artefact_type, [framework], content, as_of):
            best[link.clause] = _better(best.get(link.clause), link.verdict)

    satisfied = sum(1 for v in best.values() if v == SATISFIED)
    partial = sum(1 for v in best.values() if v == "PARTIAL")

    return FrameworkReadiness(
        framework=framework,
        total_requirements=total,
        evaluated=len(best),
        satisfied=satisfied,
        partial=partial,
        readiness=(satisfied / total) if total else 0.0,
        already_subscribed=framework in (subscribed or []),
        clauses=tuple(
            {"clause": req.clause, "title": req.title,
             "verdict": best.get(req.clause, "NO_EVIDENCE")}
            for req in pack.requirements
        ),
    )


_RANK = {"NO_EVIDENCE": 0, "FAIL": 1, "PARTIAL": 2, "PASS": 3}


def _better(current: str | None, candidate: str) -> str:
    if current is None:
        return candidate
    return candidate if _RANK.get(candidate, 0) > _RANK.get(current, 0) else current
