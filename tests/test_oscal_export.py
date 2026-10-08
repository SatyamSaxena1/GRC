"""OSCAL Assessment Results export: valid against NIST's schema, deterministic, and every gap,
exception and hash carried over (docs/product/oscal-export.md)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest

from app import exceptions as exc_rules
from app.collectors import github_change_control as gcc
from app.content.load import load as load_content
from app.models import AuditEvent, Evidence, EvidenceControlLink, GapException, GapRow
from app.oscal import NS, token
from app.routers import connectors

SCHEMA = Path(__file__).parent / "fixtures" / "oscal" / "oscal_assessment-results_schema-1.2.3.json"
# The vendored file is NIST's release asset for OSCAL v1.2.3; a changed file must be a decision.
SCHEMA_SHA256 = "4034e2032332dbf597e59e0646ec16c2c31df992962490371e91f47b219ff42c"
CONTENT = load_content()

# Local copies (tests/ is not a package): a deterministic change-control snapshot.
HEAD = "abc123"


def _pr(reviews=()):
    return {"number": 1, "author": {"login": "alice", "is_bot": False}, "head_sha": HEAD,
            "reviews": [{"user": {"login": who, "is_bot": False}, "state": "APPROVED",
                         "commit_id": HEAD, "submitted_at": "2026-10-01T00:00:00Z"} for who in reviews],
            "commits": [{"sha": HEAD, "message": "change", "author_login": "alice", "committer_login": "web-flow"}],
            "checks": [{"name": "ci", "conclusion": "success"}]}


class _Response:
    content = b"{}"

    def __init__(self, attributes):
        self._a = attributes

    def raise_for_status(self):
        return None

    def json(self):
        return {"attributes": self._a}


def _sync(client, monkeypatch, org_id):
    protection = {"enabled": True, "required_approving_reviews": 1, "dismiss_stale_reviews": False,
                  "enforce_admins": True, "allow_force_pushes": False}
    snapshot = gcc.summarize([{"protection": protection, "pulls": [_pr(["bob"]), _pr(), _pr()],
                               "default_commits": []}])
    monkeypatch.setenv(connectors._env_key("github", "URL"), "https://collector.test/github")
    monkeypatch.setattr(connectors.requests, "get", lambda url, **_: _Response(snapshot))
    assert client.post("/connectors/github/sync", headers={"authorization": f"org:{org_id}"}).status_code == 202


def validator():
    """NIST writes TokenDatatype with ECMAScript's \\p{L}/\\p{N}, which Python's re cannot
    compile. Swap in the ASCII subset: stricter, so a document that passes it passes the real one
    (and everything this export emits is ASCII by construction)."""
    raw = SCHEMA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256
    schema = json.loads(raw)
    token_def = schema["definitions"]["TokenDatatype"]
    assert token_def["pattern"] == "^(\\p{L}|_)(\\p{L}|\\p{N}|[.\\-_])*$"
    token_def["pattern"] = "^[A-Za-z_][A-Za-z0-9._-]*$"
    return jsonschema.Draft7Validator(schema, format_checker=jsonschema.FormatChecker())


def _export(client, org_id, framework="SOC-2"):
    response = client.get("/export/oscal/assessment-results.json", params={"framework": framework},
                          headers={"authorization": f"org:{org_id}"})
    assert response.status_code == 200, response.text
    return response


@pytest.fixture()
def org(client, bootstrap, monkeypatch, db):
    org_id, _ = bootstrap(client, frameworks=["SOC-2", "PCI-DSS"])
    _sync(client, monkeypatch, org_id)
    gaps = {g.attribute: (g, l) for g, l in db.query(GapRow, EvidenceControlLink)
            .join(EvidenceControlLink, EvidenceControlLink.id == GapRow.link_id)
            .filter(EvidenceControlLink.framework == "SOC-2")}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for attribute, status in (("merges_without_independent_approval", "APPROVED"),
                              ("stale_reviews_dismissed", "REQUESTED")):
        gap, link = gaps[attribute]
        db.add(GapException(
            org_id=org_id, framework="SOC-2", clause=link.clause, attribute=attribute, gap_kind=gap.kind,
            rule_hash=exc_rules.rule_hash(CONTENT, "SOC-2", link.clause),
            value_fingerprint=exc_rules.gap_fingerprint(gap, link), actual_value=gap.actual_value,
            justification="Accepted for the pilot, reviewed weekly by the CISO.", status=status,
            requested_by="org", expires_at=now + timedelta(days=30),
            decided_by="auditor" if status == "APPROVED" else None,
            decided_at=now if status == "APPROVED" else None))
    db.commit()
    return org_id


def test_the_export_is_valid_oscal(client, org):
    document = _export(client, org).json()
    errors = sorted(validator().iter_errors(document), key=lambda e: list(e.path))
    assert not errors, [f"{list(e.path)}: {e.message}" for e in errors[:5]]
    assert document["assessment-results"]["metadata"]["oscal-version"] == "1.2.3"


def test_same_state_same_bytes_and_the_hash_is_in_the_audit_trail(client, org, db):
    first, second = _export(client, org), _export(client, org)
    assert first.content == second.content
    digest = hashlib.sha256(first.content).hexdigest()
    assert first.headers["x-content-sha256"] == digest
    events = db.query(AuditEvent).filter_by(action="EXPORT_GENERATED", org_id=org).all()
    assert [e.detail["sha256"] for e in events] == [digest, digest]


def test_gaps_and_exceptions_map_to_risk_status(client, org):
    result = _export(client, org).json()["assessment-results"]["results"][0]
    risks = {next(p["value"] for p in r["props"] if p["name"] == "attribute"): r for r in result["risks"]}
    approved = risks["merges_without_independent_approval"]
    assert approved["status"] == "deviation-approved" and approved["deadline"].endswith("Z")
    assert risks["stale_reviews_dismissed"]["status"] == "deviation-requested"
    finding = next(f for f in result["findings"] if f["target"]["target-id"] == "soc-2_cc8.1")
    assert finding["target"]["status"]["state"] == "not-satisfied"
    assert {r["risk-uuid"] for r in finding["related-risks"]} >= {approved["uuid"]}


def test_evidence_hashes_and_verdict_provenance_travel(client, org, db):
    document = _export(client, org).json()["assessment-results"]
    evidence = db.query(Evidence).filter_by(org_id=org).one()
    resources = document["back-matter"]["resources"]
    hashes = [h["value"] for r in resources for l in r.get("rlinks", []) for h in l["hashes"]]
    assert evidence.sha256 in hashes
    assert document["import-ap"]["href"] == f"#{resources[0]['uuid']}"  # no dangling reference
    observation = document["results"][0]["observations"][0]
    names = {p["name"] for p in observation["props"]}
    assert {"rule-hash", "evaluation-hash", "engine-version"} <= names
    assert observation["methods"] == ["TEST"]  # a connector snapshot is a test, not a document review
    every_prop = [p for p in _walk(document) if isinstance(p, dict) and "name" in p and "value" in p]
    assert every_prop and all(p.get("ns") == NS for p in every_prop)


def test_control_ids_are_oscal_tokens(client, org):
    result = _export(client, org, "PCI-DSS").json()["assessment-results"]["results"][0]
    ids = [c["control-id"] for c in result["reviewed-controls"]["control-selections"][0]["include-controls"]]
    assert token("PCI-DSS", "6.5.1") == "pci-dss_6.5.1" and "pci-dss_6.5.1" in ids


def test_unknown_framework_and_other_tenants(client, org, bootstrap):
    assert client.get("/export/oscal/assessment-results.json", params={"framework": "NOPE"},
                      headers={"authorization": f"org:{org}"}).status_code == 404
    other, _ = bootstrap(client, frameworks=["SOC-2"])
    document = _export(client, other).json()["assessment-results"]
    assert "observations" not in document["results"][0]  # nothing of the first tenant's leaks
    assert not list(validator().iter_errors({"assessment-results": document}))  # empty is still valid


def _walk(node):
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)
