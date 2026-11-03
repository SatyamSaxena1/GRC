"""The demo snapshots (demo/collectors) must keep producing a demonstrable result: real verdicts
with both passes and failures, gaps and tasks, and a COMPLETE run, with no model involved."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app import db as db_module
from app.models import EvidenceControlLink, GapRow, TaskRow
from app.routers import connectors
from app.service import process_evidence

DEMO = Path(__file__).resolve().parent.parent / "demo" / "collectors"


def _sync(client, bootstrap, monkeypatch, source):
    org_id, _ = bootstrap(client, frameworks=("ISO-27001", "PCI-DSS", "SOC-2", "DPDP"))
    body = (DEMO / f"{source}.json").read_bytes()

    class R:
        content = body
        def raise_for_status(self): pass
        def json(self): return json.loads(body)

    monkeypatch.setenv(connectors._env_key(source, "URL"), "https://collector.test/x")
    monkeypatch.setattr(connectors.requests, "get", lambda url, **kw: R())
    with Session(db_module.engine) as s:
        evidence = connectors.sync_connector_for_org(s, org_id, "system:test", "", source)
        process_evidence(s, connectors.CONTENT, evidence, "system:test", "")
        run = s.query(connectors.CollectionRun).filter_by(org_id=org_id, source=source).one()
        links = s.query(EvidenceControlLink).filter_by(evidence_id=evidence.id).all()
        return run, [l.verdict for l in links], s.query(GapRow).count(), s.query(TaskRow).count()


EXPECT = {"github": "gaps", "aws": "gaps", "m365": "pass", "hrms": "pass"}


@pytest.mark.parametrize("source", list(EXPECT))
def test_each_demo_snapshot_is_a_complete_run_with_the_verdicts_the_demo_relies_on(client, bootstrap, monkeypatch, source):
    run, verdicts, gaps, tasks = _sync(client, bootstrap, monkeypatch, source)
    assert run.status == "COMPLETE" and run.signals == [] and verdicts
    if EXPECT[source] == "pass":
        assert set(verdicts) == {"PASS"} and gaps == 0
    else:
        assert "PASS" not in verdicts and gaps > 0 and tasks == gaps  # real gaps, one task each


def test_the_demo_files_are_obviously_fake_and_only_use_supported_attributes():
    for name in EXPECT:
        data = json.loads((DEMO / f"{name}.json").read_text(encoding="utf-8"))
        assert set(data["attributes"]) <= connectors.SOURCES[name][2], name
        urls = [r["url"] for r in data.get("exceptions", [])]
        assert all(u.split("/")[2].endswith(".invalid") for u in urls)
        assert all(r["repo"].startswith("demo-org/") for r in data.get("exceptions", []))
