"""The pre-merge change-control gate (ADR-024): the audit's rules on one open pull request, with
a strict exit-code contract and a warn-only mode that never hides a broken gate."""

from __future__ import annotations

import json

import pytest

from app import change_gate
from app.collectors import github_change_control as gcc

R = gcc.API + "/repos/acme/app"


class _Response:
    def __init__(self, body, status=200):
        self._body, self.status_code, self.links = body, status, {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


class _GitHub:
    """One open PR (#9) by alice, head h9. Reviews, checks and files are set per test."""

    def __init__(self, reviews=(), checks=(("ci", "success"),), files=("app/main.py",), ai=False,
                 status=200):
        message = "change\n\nCo-Authored-By: Claude <noreply@anthropic.com>" if ai else "change"
        self.routes = {
            R + "/pulls/9": {"number": 9, "html_url": "https://github.com/acme/app/pull/9", "merged_at": None,
                             "user": {"login": "alice", "type": "User"}, "head": {"sha": "h9"}},
            R + "/pulls/9/commits": [{"sha": "h9", "commit": {"message": message},
                                      "author": {"login": "alice", "type": "User"},
                                      "committer": {"login": "web-flow", "type": "User"}}],
            R + "/pulls/9/reviews": [{"user": {"login": who, "type": "User"}, "state": "APPROVED",
                                      "commit_id": sha, "submitted_at": "2026-10-08T00:00:00Z"}
                                     for who, sha in reviews],
            R + "/pulls/9/files": [{"filename": f, "status": "modified"} for f in files],
            R + "/commits/h9/check-runs": {"check_runs": [{"name": n, "conclusion": c} for n, c in checks]},
            R + "/commits/h9/status": {"statuses": []},
        }
        self.status = status
        self.writes = 0

    def get(self, url, params=None, timeout=None):
        if self.status != 200:
            return _Response({"message": "Bad credentials"}, self.status)
        return _Response(self.routes[url])

    def post(self, *a, **k):  # pragma: no cover — the gate must never write
        self.writes += 1


def _run(api, *extra, capsys=None):
    code = change_gate.main(["--repo", "acme/app", "--pr", "9", "--json", *extra], session=api)
    out = json.loads(capsys.readouterr().out) if capsys else None
    return code, out


def test_an_independently_approved_green_change_passes(capsys):
    api = _GitHub(reviews=[("bob", "h9")])
    code, out = _run(api, capsys=capsys)
    assert code == change_gate.PASS and out["findings"] == [] and out["independent_approvers"] == ["bob"]
    assert api.writes == 0


@pytest.mark.parametrize("github, rule", [
    (dict(reviews=[]), "merges_without_independent_approval"),
    (dict(reviews=[("bob", "an-older-push")]), "merges_without_independent_approval"),
    (dict(reviews=[("bob", "h9")], checks=[("ci", "failure")]), "merges_with_failing_or_missing_checks"),
    (dict(reviews=[("bob", "h9")], checks=[]), "merges_with_failing_or_missing_checks"),
    (dict(reviews=[], ai=True), "ai_assisted_merges_without_independent_approval"),
    (dict(reviews=[("bob", "h9")], files=[".github/workflows/ci.yml"]),
     "gate_path_merges_without_two_independent_approvals"),
])
def test_each_per_merge_rule_fails_the_gate_and_names_the_clauses(github, rule, capsys):
    code, out = _run(_GitHub(**github), "--framework", "SOC-2", "--framework", "PCI-DSS", capsys=capsys)
    assert code == change_gate.WOULD_ADD_GAP
    finding = next(f for f in out["findings"] if f["rule"] == rule)
    assert set(finding["clauses"]) == {"SOC-2 CC8.1", "PCI-DSS 6.5.1"} and finding["fix"]


def test_two_independent_approvals_satisfy_a_gate_path_change(capsys):
    code, _ = _run(_GitHub(reviews=[("bob", "h9"), ("carol", "h9")], files=["tests/test_x.py"]), capsys=capsys)
    assert code == change_gate.PASS


def test_the_gate_does_not_wait_for_itself_but_does_for_others(capsys):
    own = _GitHub(reviews=[("bob", "h9")], checks=[("ci", "success"), ("change-control gate", "in_progress")])
    assert _run(own, capsys=capsys)[0] == change_gate.PASS
    other = _GitHub(reviews=[("bob", "h9")], checks=[("ci", "in_progress")])
    code, out = _run(other, capsys=capsys)
    assert code == change_gate.PENDING and out["pending_checks"] == ["ci"]


def test_warn_only_reports_but_never_hides_a_broken_gate(capsys):
    assert _run(_GitHub(reviews=[]), "--warn-only")[0] == change_gate.PASS
    assert "warn-only" in capsys.readouterr().err
    code = change_gate.main(["--repo", "acme/app", "--pr", "9", "--warn-only"], session=_GitHub(status=401))
    assert code == change_gate.ERROR
    assert "could not run" in capsys.readouterr().out


def test_the_step_summary_is_written_for_the_reviewer(tmp_path, monkeypatch, capsys):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    change_gate.main(["--repo", "acme/app", "--pr", "9"], session=_GitHub(reviews=[]))
    text = summary.read_text()
    assert "would add a change-control gap" in text and "merges_without_independent_approval" in text
    assert "Not evaluated here" in text


def test_the_gate_and_the_period_audit_agree_on_the_same_change():
    """Whatever the gate passes, the period collector counts as clean, and vice versa."""
    for github in (dict(reviews=[("bob", "h9")]), dict(reviews=[]), dict(reviews=[("bob", "h9")], checks=[]),
                   dict(reviews=[("bob", "h9")], files=[".github/workflows/x.yml"])):
        api = _GitHub(**github)
        pr = gcc.pull_facts(api, "acme/app", api.routes[R + "/pulls/9"])
        gate = change_gate.judge(pr, ["SOC-2"], {"change-control gate"})
        rows, _ = gcc.exceptions([{"repo": "acme/app", "protection": {}, "pulls": [pr],
                                   "default_commits": [], "deployments": []}])
        assert (gate["status"] == change_gate.PASS) == (not [r for r in rows if r["kind"] == "PULL_REQUEST"]), github


def test_waiting_rereads_only_the_head_checks(monkeypatch, capsys):
    """Review fix: polling must not re-read reviews, commits and files on every round."""
    monkeypatch.setattr(change_gate.time, "sleep", lambda s: None)
    api = _GitHub(reviews=[("bob", "h9")], checks=[("ci", "in_progress")])
    calls = []
    original = api.get
    api.get = lambda url, params=None, timeout=None: (calls.append(url), original(url, params, timeout))[1]
    clock = iter([0, 0, 1, 2, 3, 100, 100, 100])
    monkeypatch.setattr(change_gate.time, "monotonic", lambda: next(clock))
    code = change_gate.main(["--repo", "acme/app", "--pr", "9", "--wait", "10", "--poll", "1", "--json"],
                            session=api)
    assert code == change_gate.PENDING
    assert calls.count(R + "/pulls/9/reviews") == 1 and calls.count(R + "/pulls/9/files") == 1
    assert calls.count(R + "/commits/h9/check-runs") > 1
