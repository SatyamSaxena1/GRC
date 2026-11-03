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


# Which framework controls each connector snapshot is read against (ADR-037). The DPDP clause was
# the only place these facts counted; the same evidence now also counts toward these controls.
FRAMEWORK_CONTROLS = {
    "aws": {("ISO-27001", "A.8.2"), ("ISO-27001", "A.8.15"), ("SOC-2", "CC7.2"),
            ("PCI-DSS", "10.2.1"), ("PCI-DSS", "8.4.1")},
    "m365": {("ISO-27001", "A.8.5"), ("PCI-DSS", "8.4.3")},
    "hrms": {("PCI-DSS", "8.2.5")},
}


@pytest.mark.parametrize("source", list(FRAMEWORK_CONTROLS))
def test_connector_evidence_also_counts_toward_framework_controls(client, bootstrap, monkeypatch, source):
    _sync(client, bootstrap, monkeypatch, source)
    with Session(db_module.engine) as s:
        linked = {(l.framework, l.clause) for l in s.query(EvidenceControlLink).all()}
    assert FRAMEWORK_CONTROLS[source] <= linked
