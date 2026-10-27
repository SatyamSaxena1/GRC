"""Connector runs: "no evidence" and "could not collect evidence" are different states (ADR-030)."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from app import collection, db as db_module
from app.models import AuditEvent, CollectionRun, Evidence, EvidenceControlLink
from app.routers import connectors
from app.service import process_evidence
from app.storage import get_storage

ATTRS = {"repositories_in_scope": 2, "merges_in_period": 40, "merges_without_independent_approval": 0,
         "default_branch_protected": True}


@pytest.fixture()
def org(client, bootstrap, monkeypatch):
    org_id, _ = bootstrap(client)
    monkeypatch.setenv("DPDP_GITHUB_COLLECTOR_URL", "http://collector.test/github")
    return org_id


@pytest.fixture()
def collector(monkeypatch):
    """Script the collector's answer: collector.reply = {...} or an Exception."""
    class Reply:
        reply: object = {}

    def fake_get(url, **kwargs):
        if isinstance(Reply.reply, Exception):
            raise Reply.reply
        class R:
            content = json.dumps(Reply.reply).encode()
            def raise_for_status(self): pass
            def json(self): return Reply.reply
        return R()

    monkeypatch.setattr(connectors.requests, "get", fake_get)
    return Reply


def sync(org_id):
    with Session(db_module.engine) as s:
        evidence = connectors.sync_connector_for_org(s, org_id, "system:test", "", "github")
        process_evidence(s, connectors.CONTENT, evidence, "system:test", "")
        return evidence.id


def runs():
    with Session(db_module.engine) as s:
        return s.query(CollectionRun).order_by(CollectionRun.started_at).all()


def links(evidence_id):
    with Session(db_module.engine) as s:
        return s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id).all()


def test_a_clean_first_run_is_complete_but_says_it_had_nothing_to_compare_with(org, collector):
    collector.reply = {"attributes": ATTRS}
    sync(org)
    (run,) = runs()
    assert (run.status, run.expectation, run.signals) == ("COMPLETE", "NONE", [])


def test_a_collector_that_reports_truncation_makes_the_run_partial_and_never_a_pass(org, collector):
    collector.reply = {"attributes": ATTRS,
                       "collection": {"truncated": True, "pages_fetched": 3, "pages_expected": 9}}
    evidence_id = sync(org)
    (run,) = runs()
    assert run.status == "PARTIAL" and run.expectation == "REPORTED"
    assert any("3 of 9 pages" in s for s in run.signals)
    found = links(evidence_id)
    assert found and all(l.verdict != "PASS" for l in found)  # "0 unapproved merges" was withheld, not read as 0
    with Session(db_module.engine) as s:
        stored = json.loads(get_storage().get(s.get(Evidence, evidence_id).storage_key))
        assert stored["attributes"] == {} and stored["unverified_attributes"]["merges_in_period"] == 40
        assert "Values were withheld" in s.get(Evidence, evidence_id).description


@pytest.mark.parametrize("declared, fragment", [
    ({"rate_limited": True}, "rate limit"),
    ({"errors": ["GET /deployments: 403"]}, "GET /deployments: 403"),
    ({"complete": False}, "incomplete"),
    ({"total_returned": 80, "total_expected": 100}, "80 of 100"),
])
def test_each_collector_signal_makes_the_run_partial(declared, fragment):
    result = collection.assess(declared, ATTRS, None)
    assert result["status"] == "PARTIAL" and any(fragment in s for s in result["signals"])


def test_history_catches_what_the_collector_did_not_declare(org, collector):
    collector.reply = {"attributes": ATTRS}
    sync(org)
    collector.reply = {"attributes": {**ATTRS, "repositories_in_scope": 1, "merges_in_period": 0}}
    evidence_id = sync(org)
    first, second = runs()
    assert second.status == "PARTIAL" and second.expectation == "HISTORY"
    assert any("fell from 2 to 1" in s for s in second.signals)
    assert any("no merges returned where the last complete run had 40" in s for s in second.signals)
    assert all(l.verdict != "PASS" for l in links(evidence_id))


def test_attributes_that_vanish_between_runs_are_flagged():
    baseline = collection.summary(ATTRS)
    result = collection.assess(None, {"repositories_in_scope": 2, "merges_in_period": 40}, baseline)
    assert result["status"] == "PARTIAL"
    assert "default_branch_protected" in result["signals"][0]


def test_a_partial_run_is_not_the_next_runs_baseline(org, collector):
    collector.reply = {"attributes": ATTRS}
    sync(org)
    collector.reply = {"attributes": {**ATTRS, "repositories_in_scope": 1}}
    sync(org)  # partial
    collector.reply = {"attributes": {**ATTRS, "repositories_in_scope": 2}}
    sync(org)
    assert [r.status for r in runs()] == ["COMPLETE", "PARTIAL", "COMPLETE"]


def test_a_failed_collection_is_recorded_and_raised_not_swallowed(org, collector):
    collector.reply = connectors.requests.RequestException("connection refused")
    with pytest.raises(Exception) as caught:
        with Session(db_module.engine) as s:
            connectors.sync_connector_for_org(s, org, "system:test", "", "github")
    assert getattr(caught.value, "status_code", None) == 502
    (run,) = runs()
    assert run.status == "FAILED" and "connection refused" in run.signals[0] and run.evidence_id is None


def test_every_run_is_in_the_audit_log(org, collector):
    collector.reply = {"attributes": ATTRS, "collection": {"rate_limited": True}}
    sync(org)
    with Session(db_module.engine) as s:
        (event,) = s.query(AuditEvent).filter_by(action="CONNECTOR_RUN").all()
    assert event.detail["status"] == "PARTIAL" and event.detail["signals"]


def test_connector_status_reports_the_last_run_not_just_the_last_evidence(client, org, collector):
    collector.reply = {"attributes": ATTRS}
    sync(org)
    collector.reply = connectors.requests.RequestException("boom")
    with pytest.raises(Exception):
        with Session(db_module.engine) as s:
            connectors.sync_connector_for_org(s, org, "system:test", "", "github")
    github = next(c for c in client.get("/connectors", headers={"authorization": f"org:{org}"}).json()
                  if c["source"] == "github")
    assert github["collection"]["status"] == "FAILED"
