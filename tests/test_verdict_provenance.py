"""Verdict provenance and replay (ADR-022): every computed verdict names the rule, engine, build
and inputs that produced it, and replaying them gives the same answer."""

from __future__ import annotations

import hashlib
import json
from datetime import date

import pytest

from app import provenance
from app.collectors import github_change_control as gcc
from app.content.load import load as load_content
from app.evaluate import ENGINE_VERSION, evaluate_requirement
from app.exceptions import rule_hash
from app.models import AuditEvent, EvidenceControlLink, RuleDefinition
from app.routers import connectors
from evaluation.runner import load_cases, sample_cases

CONTENT = load_content()

# Local copies (tests/ is not a package): a deterministic change-control snapshot via a fake
# collector, so verdicts come from rules alone with no model involved.
HEAD = "abc123"
PROTECTED = {"enabled": True, "required_approving_reviews": 1, "dismiss_stale_reviews": True,
             "enforce_admins": True, "allow_force_pushes": False}


def _pr(reviews=()):
    return {"number": 1, "author": {"login": "alice", "is_bot": False}, "head_sha": HEAD,
            "reviews": [{"user": {"login": who, "is_bot": False}, "state": "APPROVED",
                         "commit_id": HEAD, "submitted_at": "2026-10-01T00:00:00Z"} for who in reviews],
            "commits": [{"sha": HEAD, "message": "change", "author_login": "alice", "committer_login": "web-flow"}],
            "checks": [{"name": "ci", "conclusion": "success"}]}


def _snapshot(unapproved: int):
    pulls = [_pr(reviews=["bob"])] + [_pr() for _ in range(unapproved)]
    return gcc.summarize([{"protection": PROTECTED, "pulls": pulls, "default_commits": []}])


class _Response:
    content = b"{}"

    def __init__(self, attributes):
        self._a = attributes

    def raise_for_status(self):
        return None

    def json(self):
        return {"attributes": self._a}


def _sync(client, monkeypatch, org_id, unapproved=2):
    monkeypatch.setenv(connectors._env_key("github", "URL"), "https://collector.test/github")
    monkeypatch.setattr(connectors.requests, "get", lambda url, **_: _Response(_snapshot(unapproved)))
    assert client.post("/connectors/github/sync", headers={"authorization": f"org:{org_id}"}).status_code == 202


def _link(client, org_id):
    headers = {"authorization": f"org:{org_id}"}
    evidence = next(e for e in client.get("/evidence", headers=headers).json()
                    if e["artefact_type"] == "CHANGE_CONTROL_SNAPSHOT")
    detail = client.get(f"/evidence/{evidence['id']}", headers=headers).json()
    return evidence["id"], next(l for l in detail["links"] if l["clause"] == "CC8.1")


@pytest.fixture()
def synced(client, bootstrap, monkeypatch):
    org_id, engagement_id = bootstrap(client, frameworks=["SOC-2"])
    _sync(client, monkeypatch, org_id)
    evidence_id, link = _link(client, org_id)
    return org_id, engagement_id, evidence_id, link


def _replay(client, org_id, evidence_id, link_id):
    response = client.get(f"/evidence/{evidence_id}/links/{link_id}/replay",
                          headers={"authorization": f"org:{org_id}"})
    assert response.status_code == 200, response.text
    return response.json()


def test_a_computed_verdict_records_what_produced_it(synced, db):
    org_id, _, evidence_id, link = synced
    p = link["provenance"]
    assert p["rule_hash"] == rule_hash(CONTENT, "SOC-2", "CC8.1")
    assert p["engine_version"] == ENGINE_VERSION and p["build_id"]
    assert p["engine_verdict"] == link["verdict"] == "PARTIAL"
    assert p["as_of"] and len(p["evaluation_hash"]) == 64 and p["rules_changed_since"] is False

    row = db.get(EvidenceControlLink, link["id"])
    # only what the rule reads, not the whole extraction
    assert row.evaluation_inputs["attributes"]["merges_without_independent_approval"] == 2
    assert row.evaluation_inputs["artefact_type"] == "CHANGE_CONTROL_SNAPSHOT"
    stored = db.get(RuleDefinition, p["rule_hash"])
    assert stored is not None and stored.framework == "SOC-2"

    processed = db.query(AuditEvent).filter_by(action="EVIDENCE_PROCESSED", entity=evidence_id).one()
    assert {"framework": "SOC-2", "clause": "CC8.1", "verdict": "PARTIAL",
            "evaluation_hash": p["evaluation_hash"]} in processed.detail["evaluations"]


def test_replay_reproduces_the_verdict(client, synced):
    org_id, _, evidence_id, link = synced
    result = _replay(client, org_id, evidence_id, link["id"])
    assert result["status"] == "REPRODUCED"
    assert result["replayed"]["verdict"] == "PARTIAL"
    assert result["rules_changed_since"] is False


def test_replay_uses_the_rule_as_it_was_and_shows_what_todays_rule_says(client, synced, monkeypatch):
    org_id, _, evidence_id, link = synced
    from app.routers import evidence as evidence_router
    current = CONTENT.requirement("SOC-2", "CC8.1")
    loosened = current.model_copy(update={"mappings": tuple(
        m.model_copy(update={"delta_conditions": tuple(
            c for c in m.delta_conditions if c.attribute != "merges_without_independent_approval")})
        for m in current.mappings)})
    monkeypatch.setattr(type(evidence_router.CONTENT), "requirement",
                        lambda self, fw, clause: loosened if (fw, clause) == ("SOC-2", "CC8.1") else current)

    result = _replay(client, org_id, evidence_id, link["id"])
    assert result["status"] == "REPRODUCED"          # judged by the stored rule, not today's
    assert result["rules_changed_since"] is True
    assert result["under_current_rules"]["verdict"] == "PASS"


def test_an_edited_rule_definition_is_detected(client, synced, db):
    org_id, _, evidence_id, link = synced
    stored = db.get(RuleDefinition, link["provenance"]["rule_hash"])
    stored.body = {**stored.body, "title": "quietly edited"}
    db.commit()
    assert _replay(client, org_id, evidence_id, link["id"])["status"] == "RULE_BODY_INVALID"


def test_a_link_judged_before_provenance_says_so(client, synced, db):
    org_id, _, evidence_id, link = synced
    row = db.get(EvidenceControlLink, link["id"])
    row.evaluation_hash = row.evaluation_inputs = row.rule_hash = None
    db.commit()
    assert _replay(client, org_id, evidence_id, link["id"])["status"] == "NOT_RECORDED"


def test_locking_keeps_what_the_rules_said(client, synced, db):
    org_id, engagement_id, evidence_id, link = synced
    response = client.post(f"/audit/links/{link['id']}/lock", headers={"authorization": f"auditor:{engagement_id}"},
                           json={"verdict": "COMPLIANT", "reason": "reviewed the merges"})
    assert response.status_code == 200, response.text
    db.expire_all()
    row = db.get(EvidenceControlLink, link["id"])
    assert row.verdict == "COMPLIANT" and row.engine_verdict == "PARTIAL"
    locked = db.query(AuditEvent).filter_by(action="CONTROL_LOCKED", entity=link["id"]).one()
    assert locked.detail["evaluation_hash"] == link["provenance"]["evaluation_hash"]
    assert _replay(client, org_id, evidence_id, link["id"])["status"] == "REPRODUCED"


def test_replay_is_tenant_scoped(client, synced, bootstrap):
    _, _, evidence_id, link = synced
    other, _ = bootstrap(client, frameworks=["SOC-2"])
    assert client.get(f"/evidence/{evidence_id}/links/{link['id']}/replay",
                      headers={"authorization": f"org:{other}"}).status_code == 404


def test_content_packs_are_named_by_hash(client, synced):
    org_id = synced[0]
    body = client.get("/content/packs", headers={"authorization": f"org:{org_id}"}).json()
    soc2 = next(p for p in body["packs"] if p["framework"] == "SOC-2")
    assert len(soc2["pack_hash"]) == 64 and body["engine_version"] == ENGINE_VERSION


# --- the inputs recorded are enough, and the engine fingerprint is pinned ------------------------

def _cases():
    """Golden label cases, the demo samples, and change-control snapshots: every shape of
    input the evaluator sees in practice."""
    cases = [{"name": c["name"], "artefact_type": c["artefact_type"], "frameworks": c["frameworks"],
              "as_of": c.get("as_of") or "2026-06-30", "commitments": c.get("commitments") or {},
              "attributes": {k: v["value"] if isinstance(v, dict) else v
                             for k, v in c["attributes"].items()}}
             for c in load_cases()]
    cases += [{"name": f"change-control-{n}", "artefact_type": "CHANGE_CONTROL_SNAPSHOT",
               "frameworks": ["SOC-2", "ISO-27001", "PCI-DSS"], "as_of": "2026-06-30",
               "commitments": {}, "attributes": _snapshot(n)} for n in (0, 3)]
    return cases


def _every_evaluation(cases):
    for case in cases:
        for pack in CONTENT.packs:
            for req in pack.requirements:
                yield case, pack.framework.code, req


def test_recorded_inputs_alone_reproduce_every_evaluation():
    samples = [{**c, "commitments": c.get("commitments") or {}} for c in sample_cases()]
    for case, framework, req in _every_evaluation(_cases() + samples):
        as_of = date.fromisoformat(case["as_of"])
        full = evaluate_requirement(req, framework, case["attributes"], case["artefact_type"],
                                    as_of, case["commitments"])
        if full is None:
            continue
        inputs = provenance.inputs_for(req, case["artefact_type"], case["attributes"], as_of,
                                       case["commitments"])
        replayed = provenance._run(req, framework, inputs)
        digest = rule_hash(CONTENT, framework, req.clause)
        assert provenance.evaluation_hash(digest, ENGINE_VERSION, framework, req.clause, inputs,
                                          full.verdict, provenance._gaps(full)) == \
            provenance.evaluation_hash(digest, ENGINE_VERSION, framework, req.clause, inputs,
                                       replayed.verdict, provenance._gaps(replayed)), \
            f"{case['name']} {framework} {req.clause}"


# Change this only together with ENGINE_VERSION: a logic change that alters any verdict or gap
# below must also say so on every verdict it produces from now on.
ENGINE_FINGERPRINT = {"1": "afed8623b0642be2a4a54c3bdc9b7e12875e8bc5ff4f8aa90dfcb9dfeb5f9c28"}


def test_the_engine_fingerprint_matches_its_version():
    outcomes = []
    for case, framework, req in _every_evaluation(_cases()):
        link = evaluate_requirement(req, framework, case["attributes"], case["artefact_type"],
                                    date.fromisoformat(case["as_of"]), case["commitments"])
        if link is not None:
            outcomes.append([case["name"], framework, req.clause, link.verdict,
                             provenance._jsonable(provenance._gaps(link))])
    fingerprint = hashlib.sha256(json.dumps(outcomes, sort_keys=True, default=str).encode()).hexdigest()
    assert ENGINE_FINGERPRINT.get(ENGINE_VERSION) == fingerprint, (
        f"the evaluator's behaviour changed: bump ENGINE_VERSION in app/evaluate.py and pin {fingerprint}")
