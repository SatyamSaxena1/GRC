"""The scheduled connector sync (python -m app.monitor --sync-connectors) must evaluate what it
collects, exactly as the "Collect evidence" button does. A snapshot that is stored but never
judged is a green run that changed nothing (ADR-019 rule 1)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import db as db_module, monitor
from app.collectors import github_change_control as gcc
from app.models import Evidence, EvidenceControlLink, GapRow
from app.routers import connectors

# Local copies (tests/ is not a package): a deterministic change-control snapshot.
HEAD = "abc123"
PROTECTED = {"enabled": True, "required_approving_reviews": 1, "dismiss_stale_reviews": True,
             "enforce_admins": True, "allow_force_pushes": False}


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


def test_the_scheduled_sync_evaluates_what_it_collects(client, bootstrap, monkeypatch):
    org_id, _ = bootstrap(client, frameworks=["SOC-2"])
    snapshot = gcc.summarize([{"protection": PROTECTED, "pulls": [_pr(["bob"]), _pr()], "default_commits": []}])
    monkeypatch.setenv(connectors._env_key("github", "URL"), "https://collector.test/github")
    monkeypatch.setattr(connectors.requests, "get", lambda url, **_: _Response(snapshot))

    with Session(db_module.engine) as db:
        results = monitor.sync_all_connectors(db, org_id)
        db.commit()
    assert any(r.startswith("github: synced and evaluated") for r in results), results

    with Session(db_module.engine) as db:
        evidence = db.query(Evidence).filter_by(org_id=org_id, artefact_type="CHANGE_CONTROL_SNAPSHOT").one()
        assert evidence.status == "READY"
        link = db.query(EvidenceControlLink).filter_by(evidence_id=evidence.id, clause="CC8.1").one()
        assert link.verdict == "PARTIAL" and link.evaluation_hash
        assert db.query(GapRow).filter_by(link_id=link.id, attribute="merges_without_independent_approval").count() == 1


def test_an_evaluation_failure_fails_the_run(client, bootstrap, monkeypatch):
    org_id, _ = bootstrap(client, frameworks=["SOC-2"])
    monkeypatch.setenv(connectors._env_key("github", "URL"), "https://collector.test/github")
    monkeypatch.setattr(connectors.requests, "get", lambda url, **_: _Response({"default_branch_protected": True}))

    def broken(*args, **kwargs):
        raise RuntimeError("model gateway exploded")
    monkeypatch.setattr(monitor, "process_evidence", broken, raising=False)

    with Session(db_module.engine) as db:
        results = monitor.sync_all_connectors(db, org_id)
    assert any("evaluation failed" in r and "failed" in r for r in results), results


def test_a_scoped_sync_reaches_only_the_named_organisations(client, bootstrap, monkeypatch):
    """A collector URL is platform-wide; --org keeps one client's repositories from reaching
    every other client on the platform."""
    mine, _ = bootstrap(client, frameworks=["SOC-2"])
    other, _ = bootstrap(client, frameworks=["SOC-2"])
    snapshot = gcc.summarize([{"protection": PROTECTED, "pulls": [_pr(["bob"])], "default_commits": []}])
    monkeypatch.setenv(connectors._env_key("github", "URL"), "https://collector.test/github")
    monkeypatch.setattr(connectors.requests, "get", lambda url, **_: _Response(snapshot))

    assert monitor._sync_connectors({mine}, {"github"}) == 0
    with Session(db_module.engine) as db:
        assert db.query(Evidence).filter_by(org_id=mine, artefact_type="CHANGE_CONTROL_SNAPSHOT").count() == 1
        assert db.query(Evidence).filter_by(org_id=other).count() == 0
    assert monitor._sync_connectors({"no-such-org"}, {"github"}) == 1
