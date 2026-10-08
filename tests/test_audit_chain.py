"""Per-tenant audit chains: each organisation's events, and the platform's, form their own
chain that verifies end to end; events from before the chains are sealed by each chain's
genesis; content, order, time and deletion are all tamper-evident."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app import audit_log, monitor
from app.models import AuditEvent, Organization


@pytest.fixture()
def db(client):
    from app import db as db_module
    with Session(db_module.engine) as s:
        yield s


def _org(db, name="Acme"):
    org = Organization(name=name, frameworks=[])
    db.add(org)
    db.flush()
    return org.id


def _write(db, org_id, action="TOUCHED", **kw):
    return audit_log.record(db, actor="test", action=action, entity_type="test", entity="x",
                            org_id=org_id, **kw)


def test_each_org_and_the_platform_has_its_own_chain(db):
    a, b = _org(db, "Acme"), _org(db, "Beta")
    _write(db, a)
    _write(db, b)
    _write(db, None)
    _write(db, a)
    db.commit()
    assert audit_log.visible_chains(db) == sorted([a, b, audit_log.PLATFORM])
    report = audit_log.verify(db, a)
    assert report.ok and report.events == 3 and report.head_seq == 3   # genesis + 2
    seqs = [e.chain_seq for e in db.query(AuditEvent).filter_by(chain=a).order_by(AuditEvent.chain_seq)]
    assert seqs == [1, 2, 3]
    assert db.query(AuditEvent).filter_by(chain=a, chain_seq=1).one().action == "CHAIN_GENESIS"
    assert audit_log.verify_chain(db)


@pytest.mark.parametrize("tamper", [
    lambda e: setattr(e, "detail", {"edited": True}),
    lambda e: setattr(e, "at", e.at - timedelta(days=3)),     # v1 never covered the time
    lambda e: setattr(e, "actor", "someone else"),
])
def test_editing_any_committed_field_breaks_the_chain(db, tamper):
    a = _org(db)
    _write(db, a)
    target = _write(db, a, detail={"n": 1})
    _write(db, a)
    db.commit()
    tamper(target)
    db.commit()
    report = audit_log.verify(db, a)
    assert not report.ok and report.broken_at == target.chain_seq


def test_deleting_an_event_breaks_the_chain(db):
    a = _org(db)
    _write(db, a)
    middle = _write(db, a)
    _write(db, a)
    db.commit()
    db.delete(middle)
    db.commit()
    report = audit_log.verify(db, a)
    assert not report.ok and "missing" in report.problems[0]


def _legacy(db, org_id, at, action="OLD"):
    """A row as the previous code wrote it: no chain columns."""
    event = AuditEvent(org_id=org_id, actor="old", action=action, entity_type="test", entity="x",
                       detail={}, reason="", seq=1, prev_hash="", entry_hash="legacy", at=at)
    db.add(event)
    db.flush()
    return event


def test_genesis_seals_the_events_written_before_chains(db):
    a = _org(db)
    old = [_legacy(db, a, datetime(2026, 1, d)) for d in (1, 2, 3)]
    db.commit()
    _write(db, a)
    db.commit()
    genesis = db.query(AuditEvent).filter_by(chain=a, chain_seq=1).one()
    assert genesis.detail["legacy_events"] == 3
    assert audit_log.verify(db, a).ok

    old[1].detail = {"rewritten": "history"}
    db.commit()
    report = audit_log.verify(db, a)
    assert not report.ok and "genesis seal" in report.problems[0]


def test_removing_a_sealed_event_is_detected(db):
    a = _org(db)
    old = [_legacy(db, a, datetime(2026, 1, d)) for d in (1, 2)]
    _write(db, a)
    db.commit()
    db.delete(old[0])
    db.commit()
    assert not audit_log.verify(db, a).ok


def test_a_row_from_the_previous_code_during_a_deploy_is_reported_not_flagged(db):
    a = _org(db)
    _write(db, a)
    db.commit()
    _legacy(db, a, datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=5))
    db.commit()
    report = audit_log.verify(db, a)
    assert report.ok and report.unchained_after_genesis == 1


def test_chain_status_endpoint_is_per_tenant(client, bootstrap, db):
    a, _ = bootstrap(client)
    b, _ = bootstrap(client)
    client.post("/connectors/github/not-applicable", headers={"authorization": f"org:{a}"})
    status = client.get("/audit/chain", headers={"authorization": f"org:{a}"}).json()
    assert status["ok"] is True and status["chain"] == a
    assert client.get("/audit/chain", headers={"authorization": f"org:{b}"}).json()["chain"] == b


def test_the_nightly_monitor_fails_on_a_broken_chain(db):
    a = _org(db)
    _write(db, a)
    victim = _write(db, a)
    db.commit()
    assert monitor._report_chain(db, a) == 0
    victim.reason = "edited"
    db.commit()
    assert monitor._report_chain(db, a) == 1
