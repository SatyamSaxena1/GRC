"""Verdict provenance and replay (ADR-022; the reproducibility idea from the earlier
Trishul attempt, without its gaps).

Every computed verdict records the rule it was judged against (by rule_hash, with the
body kept in rule_definitions), the engine version, the build, and exactly the inputs
the rule read. Replay re-runs the stored rule over the stored inputs: the same answer
proves the verdict, a different one shows what moved.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.content.load import Content, Requirement
from app.evaluate import ENGINE_VERSION, Link, consulted_attributes, evaluate_requirement
from app.exceptions import rule_hash
from app.models import EvidenceControlLink, RuleDefinition

def build_id() -> str:
    """The deployed commit, so 'engine 1' can always be traced to the exact code."""
    return os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("BUILD_ID") or "dev"


def _body_hash(body: Any) -> str:
    # Must stay byte-identical to app/exceptions.py::rule_hash.
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def _canonical_hash(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def ensure_rule(db: Session, content: Content, framework: str, clause: str) -> str | None:
    """Store this requirement's definition under its hash, once. Returns the hash."""
    req = content.requirement(framework, clause)
    if req is None:
        return None
    digest = rule_hash(content, framework, clause)
    # No process-level cache: a cached hash would outlive a rolled-back transaction and
    # leave a verdict pointing at a definition that was never stored.
    if db.get(RuleDefinition, digest) is None:
        try:
            with db.begin_nested():
                db.add(RuleDefinition(rule_hash=digest, framework=framework, clause=clause,
                                      body=req.model_dump(mode="json")))
        except IntegrityError:
            pass  # another worker stored the same definition first
    return digest


def inputs_for(req: Requirement, artefact_type: str, attributes: dict[str, Any], as_of: date,
               org_commitments: dict[str, Any]) -> dict:
    """Exactly what evaluate_requirement can read for this requirement, nothing more."""
    attrs, commitments = consulted_attributes(req, artefact_type)
    return _jsonable({
        "artefact_type": artefact_type,
        "as_of": as_of.isoformat(),
        "attributes": {k: attributes[k] for k in sorted(attrs) if k in attributes},
        "org_commitments": {k: org_commitments[k] for k in sorted(commitments) if k in org_commitments},
    })


def _gaps(link: Link) -> list[dict]:
    return [{"kind": g.kind, "attribute": g.attribute, "detail": g.detail,
             "actual": g.actual, "required": g.required} for g in link.gaps]


def evaluation_hash(digest: str, engine_version: str, framework: str, clause: str, inputs: dict,
                    verdict: str, gaps: list[dict]) -> str:
    """No ids and no timestamps: two runs that decided the same thing hash the same."""
    return _canonical_hash({"rule_hash": digest, "engine_version": engine_version,
                            "framework": framework, "clause": clause, "inputs": inputs,
                            "verdict": verdict, "gaps": _jsonable(gaps)})


def _run(req: Requirement, framework: str, inputs: dict) -> Link | None:
    return evaluate_requirement(req, framework, inputs["attributes"], inputs["artefact_type"],
                                date.fromisoformat(inputs["as_of"]), inputs["org_commitments"])


def stamp(db: Session, content: Content, row: EvidenceControlLink, link: Link, artefact_type: str,
          attributes: dict[str, Any], as_of: date, org_commitments: dict[str, Any]) -> None:
    """Record on the link what produced its verdict."""
    req = content.requirement(link.framework, link.clause)
    digest = ensure_rule(db, content, link.framework, link.clause)
    if req is None or digest is None:
        return
    inputs = inputs_for(req, artefact_type, attributes, as_of, org_commitments)
    row.rule_hash = digest
    row.engine_version = ENGINE_VERSION
    row.build_id = build_id()
    row.evaluation_inputs = inputs
    row.engine_verdict = link.verdict
    row.evaluation_hash = evaluation_hash(digest, ENGINE_VERSION, link.framework, link.clause,
                                          inputs, link.verdict, _gaps(link))


def replay(db: Session, content: Content, row: EvidenceControlLink) -> dict:
    """Re-run the recorded rule over the recorded inputs, and say what today's rule would say."""
    recorded = {"verdict": row.engine_verdict, "rule_hash": row.rule_hash,
                "engine_version": row.engine_version, "build_id": row.build_id,
                "as_of": (row.evaluation_inputs or {}).get("as_of"),
                "evaluation_hash": row.evaluation_hash}
    result: dict[str, Any] = {"link_id": row.id, "framework": row.framework, "clause": row.clause,
                              "recorded": recorded, "current_engine_version": ENGINE_VERSION}
    if row.evaluation_hash is None or row.evaluation_inputs is None or row.rule_hash is None:
        return {**result, "status": "NOT_RECORDED"}

    current_hash = rule_hash(content, row.framework, row.clause)
    result["rules_changed_since"] = current_hash != row.rule_hash
    current_req = content.requirement(row.framework, row.clause)
    current = _run(current_req, row.framework, row.evaluation_inputs) if current_req else None
    result["under_current_rules"] = (
        {"verdict": current.verdict, "gaps": _jsonable(_gaps(current))} if current else None)

    stored = db.get(RuleDefinition, row.rule_hash)
    if stored is None or _body_hash(stored.body) != row.rule_hash:
        return {**result, "status": "RULE_BODY_INVALID"}
    replayed = _run(Requirement.model_validate(stored.body), row.framework, row.evaluation_inputs)
    if replayed is None:
        return {**result, "status": "DIFFERS", "replayed": None}
    digest = evaluation_hash(row.rule_hash, row.engine_version or "", row.framework, row.clause,
                             row.evaluation_inputs, replayed.verdict, _gaps(replayed))
    return {**result,
            "status": "REPRODUCED" if digest == row.evaluation_hash else "DIFFERS",
            "replayed": {"verdict": replayed.verdict, "gaps": _jsonable(_gaps(replayed))}}


_pack_hashes: dict[int, list[dict]] = {}


def packs(content: Content) -> list[dict]:
    """Each framework pack's whole definition, hashed with the same canonicalisation as
    rule_hash, so 'which rules were live' can be named in one string per framework."""
    if id(content) not in _pack_hashes:
        _pack_hashes[id(content)] = [
            {"framework": p.framework.code, "edition": p.framework.version,
             "requirements": len(p.requirements),
             "pack_hash": _body_hash(p.model_dump(mode="json"))}
            for p in content.packs]
    return _pack_hashes[id(content)]
