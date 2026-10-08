"""OSCAL Assessment Results export (idea from the earlier Trishul attempt, without its gaps).

One framework's current results for one organisation, as an OSCAL 1.2.3 assessment-results
document that other GRC tools can import. Deterministic: UUIDs are derived from natural keys
and `last-modified` from the data, so the same state always gives the same bytes and the same
hash. Every GRC-specific fact is a namespaced prop.

Mapping (docs/product/oscal-export.md):
  clause              -> control-id token  <framework>_<clause>, lowercased
  evidence x clause   -> observation (EXAMINE for documents, TEST for connector snapshots)
  evidence file       -> back-matter resource with its SHA-256
  control verdict     -> finding, target objective-id, satisfied / not-satisfied
  open gap            -> risk: open, deviation-requested or deviation-approved (exceptions)
  engagement          -> back-matter resource that import-ap points at
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import provenance
from app.auth import Actor
from app.content.load import Content
from app.exceptions import gap_fingerprint
from app.models import Engagement, Evidence, EvidenceControlLink, GapException, GapRow, Organization

OSCAL_VERSION = "1.2.3"
NS = "https://github.com/SatyamSaxena1/GRC/ns/oscal"
_ROOT = uuid.uuid5(uuid.NAMESPACE_URL, NS)
CONNECTOR_MIME = "application/vnd.grc.connector+json"
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _uuid(*parts: str) -> str:
    return str(uuid.uuid5(_ROOT, "\x1f".join(parts)))


def token(framework: str, clause: str) -> str:
    """An OSCAL token: starts with a letter, then letters, digits, '.', '-', '_'."""
    raw = f"{framework}_{clause}".lower()
    return re.sub(r"[^a-z0-9._-]", "-", raw)


def _line(text: str) -> str:
    """OSCAL titles are single-line markup: fold any line breaks a free-text name carries."""
    return " ".join(str(text).split())


def _ts(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _prop(name: str, value) -> dict:
    return {"name": name, "ns": NS, "value": str(value)}


def _props(**values) -> list[dict]:
    return [_prop(k.replace("_", "-"), v) for k, v in values.items() if v not in (None, "")]


_STATE = {"PASS": "satisfied"}
_AUDITOR = {"COMPLIANT": "PASS", "PARTIALLY_COMPLIANT": "PARTIAL", "NON_COMPLIANT": "FAIL"}


def build(db: Session, actor: Actor, content: Content, framework: str, controls: list[dict],
          gaps: list[dict], verdict_of) -> dict:
    """`controls`, `gaps` and `verdict_of` come from the same sweeps the other exports use
    (app/routers/analytics.py), so this adds no authorization rule of its own."""
    org = db.get(Organization, actor.org_id)
    # The auditor's own engagement when acting under one; the latest active one otherwise.
    engagement = db.get(Engagement, actor.engagement_id) if actor.engagement_id else None
    if engagement is None or engagement.org_id != actor.org_id:
        engagement = (db.query(Engagement).filter_by(org_id=actor.org_id, status="ACTIVE")
                      .order_by(Engagement.period_end.desc()).first())
    org_name = _line(org.name)
    controls = sorted((c for c in controls if c["framework"] == framework), key=lambda c: c["clause"])
    gaps = [g for g in gaps if g["framework"] == framework]

    stamps: list[datetime] = []
    resources: dict[str, dict] = {}
    observations, findings, risks = [], [], []

    for control in controls:
        cid = token(framework, control["clause"])
        observation_ids = []
        for out in sorted(control["links"], key=lambda l: l["id"]):
            if not out.get("current", True):
                continue  # superseded versions are history, not the current result
            link = db.get(EvidenceControlLink, out["id"])
            evidence = db.get(Evidence, link.evidence_id)
            stamps += [t for t in (link.evaluated_at, link.locked_at) if t]
            resource_id = _uuid("evidence", evidence.id)
            resources[resource_id] = {
                "uuid": resource_id,
                "title": _line(evidence.original_filename or evidence.artefact_type),
                "props": _props(artefact_type=evidence.artefact_type, version=evidence.version),
                "rlinks": [{"href": f"/evidence/{evidence.id}/file",
                            "hashes": [{"algorithm": "SHA-256", "value": evidence.sha256}]}],
            }
            obs_id = _uuid("observation", link.id)
            observation_ids.append(obs_id)
            observations.append({
                "uuid": obs_id,
                "title": f"{framework} {control['clause']}: {evidence.artefact_type}",
                "description": f"Deterministic rule evaluation of {evidence.artefact_type} "
                               f"against {framework} {control['clause']}: {link.engine_verdict or link.verdict}.",
                "props": _props(clause=control["clause"], verdict=link.verdict,
                                engine_verdict=link.engine_verdict, auditor_verdict=link.auditor_verdict,
                                locked="true" if link.locked else "false",
                                rule_hash=link.rule_hash, engine_version=link.engine_version,
                                evaluation_hash=link.evaluation_hash),
                "methods": ["TEST" if evidence.mime_type == CONNECTOR_MIME else "EXAMINE"],
                "types": ["control-objective"],
                "relevant-evidence": [{"href": f"#{resource_id}",
                                       "description": evidence.original_filename or evidence.artefact_type}],
                "collected": _ts(link.evaluated_at),
            })

        risk_ids = []
        for gap in sorted((g for g in gaps if g["clause"] == control["clause"]), key=lambda g: g["id"]):
            risk = _risk(db, actor, gap, stamps)
            risk_ids.append(risk["uuid"])
            risks.append(risk)

        # Judge the finding on exactly the evidence its observations show: the current versions.
        verdict = verdict_of([l for l in control["links"] if l.get("current", True)])
        verdict = _AUDITOR.get(verdict, verdict)
        finding = {
            "uuid": _uuid("finding", framework, control["clause"]),
            "title": _line(f"{framework} {control['clause']}" + (f": {control['title']}" if control["title"] else "")),
            "description": f"Control verdict {verdict}"
                           + (" (locked by the auditor)" if control["locked"] else "") + ".",
            "props": _props(clause=control["clause"], verdict=verdict,
                            locked="true" if control["locked"] else "false"),
            "target": {"type": "objective-id", "target-id": cid,
                       "status": {"state": _STATE.get(verdict, "not-satisfied")}},
        }
        if observation_ids:
            finding["related-observations"] = [{"observation-uuid": o} for o in observation_ids]
        if risk_ids:
            finding["related-risks"] = [{"risk-uuid": r} for r in risk_ids]
        findings.append(finding)

    plan_id = _uuid("assessment-plan", actor.org_id, engagement.id if engagement else "self-assessment")
    plan = {"uuid": plan_id,
            "title": "Assessment plan" + (f": engagement {engagement.id}" if engagement else ": self-assessment"),
            "description": f"{framework} assessment of {org_name} on the GRC platform. There is no separate "
                           f"OSCAL assessment plan; this resource stands in for it.",
            "props": _props(engagement=engagement.id if engagement else None, framework=framework)}

    pack = next((p for p in provenance.packs(content) if p["framework"] == framework), None)
    last_modified = max(stamps, default=EPOCH)
    start = (engagement.period_start if engagement and engagement.period_start
             else min(stamps, default=EPOCH))
    result = {
        "uuid": _uuid("result", actor.org_id, framework),
        "title": f"{framework} results for {org_name}",
        "description": "Verdicts decided by deterministic rules over extracted facts; a model never "
                       "decides a verdict (ADR-004). Auditor locks are shown as props.",
        "start": _ts(start),
        "reviewed-controls": {"control-selections": [
            {"include-controls": [{"control-id": token(framework, c["clause"])} for c in controls]}
            if controls else {"include-all": {}}]},
    }
    if engagement and engagement.period_end:
        result["end"] = _ts(engagement.period_end)
    for key, items in (("observations", observations), ("risks", risks), ("findings", findings)):
        if items:
            result[key] = items

    document = {
        "metadata": {
            "title": f"{org_name}: {framework} assessment results",
            "last-modified": _ts(last_modified),
            "version": "",
            "oscal-version": OSCAL_VERSION,
            "props": _props(framework=framework,
                            framework_edition=pack["edition"] if pack else None,
                            pack_hash=pack["pack_hash"] if pack else None,
                            engine_version=provenance.ENGINE_VERSION),
        },
        "import-ap": {"href": f"#{plan_id}"},
        "results": [result],
        "back-matter": {"resources": [plan, *sorted(resources.values(), key=lambda r: r["uuid"])]},
    }
    # Same state, same document: the version and uuid are derived from the content itself.
    digest = hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
    document["metadata"]["version"] = digest[:16]
    return {"assessment-results": {"uuid": _uuid("document", digest), **document}}


def _risk(db: Session, actor: Actor, gap: dict, stamps: list[datetime]) -> dict:
    status, deadline, exception_id = "open", None, None
    if gap.get("waived") and gap.get("exception"):
        status, deadline = "deviation-approved", gap["exception"]["expires_at"]
        exception_id = gap["exception"]["id"]
        decided = db.get(GapException, exception_id)
        if decided is not None and decided.decided_at:
            stamps.append(decided.decided_at)
    else:
        row = db.get(GapRow, gap["id"])
        link = db.get(EvidenceControlLink, row.link_id)
        pending = db.query(GapException).filter_by(
            org_id=actor.org_id, framework=link.framework, clause=link.clause, status="REQUESTED",
            value_fingerprint=gap_fingerprint(row, link)).order_by(GapException.requested_at).first()
        if pending is not None:
            status, exception_id = "deviation-requested", pending.id
            stamps.append(pending.requested_at)
    risk = {
        "uuid": _uuid("risk", gap["id"]),
        "title": f"{gap['attribute']}: {gap['kind'].lower().replace('_', ' ')}",
        "description": gap["detail"],
        "statement": gap.get("required_action") or gap["detail"],
        "props": _props(clause=gap["clause"], gap_kind=gap["kind"], attribute=gap["attribute"],
                        actual_value=gap.get("actual_value"), required_value=gap.get("required_value"),
                        exception=exception_id),
        "status": status,
    }
    if deadline:
        risk["deadline"] = deadline if deadline.endswith("Z") or "+" in deadline[10:] else deadline + "Z"
    return risk


def render(document: dict) -> bytes:
    return json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False).encode()
