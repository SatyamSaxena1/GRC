"""A customer-run script's snapshot is evidence for 30 days (ADR-061): after that the rules read it as stale, exactly as
an expired policy, so a control cannot stay green on a check nobody has re-run. A snapshot from before collection dates
were recorded is judged as it was."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app import db as db_module
from app.content.load import load
from app.evaluate import evaluate
from app.models import Evidence

TODAY = date(2026, 11, 11)


def _iso_a82(attributes):
    links = evaluate(attributes, "AWS_SNAPSHOT", ["ISO-27001"], load(), as_of=TODAY)
    return next(l for l in links if l.clause == "A.8.2")


def test_a_recent_snapshot_passes_and_an_old_one_is_stale():
    fresh = _iso_a82({"privileged_access_mfa": True, "collected_at": (TODAY - timedelta(days=5)).isoformat()})
    assert fresh.verdict == "PASS" or fresh.verdict == "PARTIAL"
    assert not any(g.kind == "STALE" for g in fresh.gaps)
    old = _iso_a82({"privileged_access_mfa": True, "collected_at": (TODAY - timedelta(days=31)).isoformat()})
    assert old.verdict == "FAIL" and any(g.kind == "STALE" and g.attribute == "collected_at" for g in old.gaps)


def test_a_snapshot_without_a_collection_date_is_judged_as_before():
    assert not any(g.kind in ("STALE", "MISSING_ATTRIBUTE") for g in _iso_a82({"privileged_access_mfa": True}).gaps)


def test_every_script_snapshot_rule_carries_the_limit():
    kinds = {"AWS_SNAPSHOT", "M365_SNAPSHOT", "GOOGLE_WORKSPACE_SNAPSHOT", "HRMS_SNAPSHOT"}
    seen = 0
    for pack in load().packs:
        for req in pack.requirements:
            for er in req.evidence_requirements:
                if er.artefact_type in kinds:
                    seen += 1
                    assert er.evidence_validity and er.evidence_validity.issued_attribute == "collected_at"
                    assert er.evidence_validity.max_age_days == 30
    assert seen >= 16


@pytest.fixture()
def aws_env(monkeypatch):
    monkeypatch.setenv("CONNECTIONS_KEY", Fernet.generate_key().decode())


def test_an_upload_records_the_day_it_was_collected(client, bootstrap, aws_env):
    org = bootstrap(client)[0]
    token = client.post("/connections/aws/token", headers={"authorization": f"org:{org}"}).json()["new_token"]
    body = {"attributes": {"encryption_at_rest": True, "privileged_access_mfa": True, "access_logging_enabled": True,
                           "backup_enabled": True}, "collection": {"complete": True, "errors": []}}
    assert client.post("/ingest/aws", json=body, headers={"authorization": f"Bearer {token}"}).status_code == 202
    with Session(db_module.engine) as s:
        ev = s.query(Evidence).filter_by(org_id=org, artefact_type="AWS_SNAPSHOT").one()
        collected = ev.attribute_values().get("collected_at")
    assert collected and date.fromisoformat(collected) >= date.today() - timedelta(days=1)
