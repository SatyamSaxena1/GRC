"""Change-control evidence from GitHub (ADR-020): the rules about who counts as an
independent approver, and the connector path from snapshot to SOC 2 / ISO / PCI verdicts."""

from __future__ import annotations

from app.collectors import github_change_control as gcc
from app.content.load import load
from app.routers import connectors

HEAD = "abc123"
PROTECTED = {"enabled": True, "required_approving_reviews": 1, "dismiss_stale_reviews": True,
             "enforce_admins": True, "allow_force_pushes": False}


def _user(login, bot=False):
    return {"login": login, "is_bot": bot}


def _pr(author="alice", reviews=(), commits=None, checks=(("ci", "success"),), head=HEAD):
    return {
        "number": 1,
        "author": _user(author, bot=author.endswith("[bot]")),
        "head_sha": head,
        "reviews": [{"user": _user(login, bot=login.endswith("[bot]")), "state": state,
                     "commit_id": commit or head, "submitted_at": f"2026-10-0{i + 1}T00:00:00Z"}
                    for i, (login, state, commit) in enumerate(reviews)],
        "commits": commits if commits is not None else [
            {"sha": head, "message": "change", "author_login": author, "committer_login": "web-flow"}],
        "checks": [{"name": n, "conclusion": c} for n, c in checks],
    }


def _approved(by="bob", **kw):
    return _pr(reviews=[(by, "APPROVED", None)], **kw)


# --- who counts as an independent approver ---------------------------------------

def test_an_approval_by_someone_else_on_the_merged_commit_is_independent():
    assert gcc.has_independent_approval(_approved())


def test_the_author_cannot_approve_their_own_change():
    assert not gcc.has_independent_approval(_approved(by="alice"))


def test_a_bot_approval_never_counts():
    assert not gcc.has_independent_approval(_approved(by="review-bot[bot]"))


def test_prompting_an_agent_and_approving_its_pr_is_still_self_review():
    """The laundering case: a person prompts an agent, the agent's bot account opens
    the PR, and the same person approves it. The person authored the commits."""
    pr = _pr(author="coding-agent[bot]",
             reviews=[("alice", "APPROVED", None)],
             commits=[{"sha": HEAD, "message": "fix\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
                       "author_login": "alice", "committer_login": "web-flow"}])
    assert not gcc.has_independent_approval(pr)
    assert gcc.is_ai_assisted(pr)


def test_an_approval_of_an_earlier_push_says_nothing_about_what_shipped():
    assert not gcc.has_independent_approval(_pr(reviews=[("bob", "APPROVED", "old-sha")]))


def test_a_later_change_request_withdraws_an_approval():
    pr = _pr(reviews=[("bob", "APPROVED", None), ("bob", "CHANGES_REQUESTED", None)])
    assert not gcc.has_independent_approval(pr)


def test_a_comment_after_an_approval_does_not_withdraw_it():
    assert gcc.has_independent_approval(
        _pr(reviews=[("bob", "APPROVED", None), ("bob", "COMMENTED", None)]))


def test_reviewer_login_case_does_not_create_a_second_person():
    assert not gcc.has_independent_approval(_approved(by="Alice"))


# --- checks ---------------------------------------------------------------------

def test_no_checks_at_all_is_not_a_pass():
    assert not gcc.checks_passed(_pr(checks=()))


def test_one_failing_check_fails_the_merge():
    assert not gcc.checks_passed(_pr(checks=(("ci", "success"), ("lint", "failure"))))


def test_skipped_and_neutral_checks_do_not_fail_the_merge():
    assert gcc.checks_passed(_pr(checks=(("ci", "success"), ("docs", "skipped"), ("x", "neutral"))))


# --- AI assistance is declared, not detected ------------------------------------

def test_a_human_only_change_is_not_ai_assisted():
    assert not gcc.is_ai_assisted(_approved())


def test_an_ai_co_author_trailer_marks_the_change_ai_assisted():
    pr = _approved(commits=[{"sha": HEAD, "message": "x\n\nCo-authored-by: GitHub Copilot <copilot@github.com>",
                             "author_login": "alice", "committer_login": "alice"}])
    assert gcc.is_ai_assisted(pr)


# --- summarize --------------------------------------------------------------------

def test_a_clean_period_summarizes_to_all_zero_exceptions():
    repo = {"protection": PROTECTED, "pulls": [_approved(), _approved()],
            "default_commits": [{"sha": "m1", "has_pull": True}]}
    out = gcc.summarize([repo])
    assert set(out) == set(gcc.ATTRIBUTES)
    assert out["default_branch_protected"] is True
    assert out["merges_in_period"] == 2
    assert out["merges_without_independent_approval"] == 0
    assert out["direct_pushes_to_default"] == 0
    assert out["admins_can_bypass"] is False


def test_the_weakest_repository_sets_the_protection_attributes():
    weak = {"protection": {"enabled": False}, "pulls": [], "default_commits": []}
    out = gcc.summarize([{"protection": PROTECTED, "pulls": [], "default_commits": []}, weak])
    assert out["default_branch_protected"] is False
    assert out["force_push_allowed_on_default"] is True
    assert out["required_approving_reviews"] == 0


def test_no_repositories_is_not_a_protected_estate():
    assert gcc.summarize([])["default_branch_protected"] is False


# --- connector -> verdicts ---------------------------------------------------------

class _Response:
    content = b"{}"

    def __init__(self, attributes):
        self._attributes = attributes

    def raise_for_status(self):
        return None

    def json(self):
        return {"attributes": self._attributes}


def _sync(client, bootstrap, monkeypatch, attributes):
    org_id, _ = bootstrap(client, frameworks=["SOC-2", "ISO-27001", "PCI-DSS"])
    headers = {"authorization": f"org:{org_id}"}
    monkeypatch.setenv(connectors._env_key("github", "URL"), "https://collector.test/github")
    monkeypatch.setattr(connectors.requests, "get", lambda url, **_: _Response(attributes))
    assert client.post("/connectors/github/sync", headers=headers).status_code == 202
    verdicts = {}
    for framework in ("SOC-2", "ISO-27001", "PCI-DSS"):
        rows = client.get(f"/analytics/readiness/{framework}", headers=headers).json()["clauses"]
        verdicts.update({(framework, r["clause"]): r["verdict"] for r in rows})
    return verdicts


CLAUSES = [("SOC-2", "CC8.1"), ("ISO-27001", "A.8.32"), ("PCI-DSS", "6.5.1")]


def test_change_management_clauses_exist_and_share_the_change_control_ucos():
    content = load()
    for framework, clause in CLAUSES:
        ucos = {m.uco for m in content.requirement(framework, clause).mappings}
        assert ucos == {"UCO-CHG-001", "UCO-CHG-002"}


def test_one_clean_snapshot_passes_all_three_frameworks(client, bootstrap, monkeypatch):
    clean = gcc.summarize([{"protection": PROTECTED, "pulls": [_approved()],
                            "default_commits": [{"sha": "m1", "has_pull": True}]}])
    verdicts = _sync(client, bootstrap, monkeypatch, clean)
    assert [verdicts[c] for c in CLAUSES] == ["PASS", "PASS", "PASS"]


def test_one_self_approved_ai_merge_is_a_gap_in_every_framework(client, bootstrap, monkeypatch):
    laundered = _pr(author="coding-agent[bot]", reviews=[("alice", "APPROVED", None)],
                    commits=[{"sha": HEAD, "message": "x\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
                              "author_login": "alice", "committer_login": "web-flow"}])
    snapshot = gcc.summarize([{"protection": PROTECTED, "pulls": [_approved(), laundered],
                               "default_commits": []}])
    assert snapshot["ai_assisted_merges_without_independent_approval"] == 1
    verdicts = _sync(client, bootstrap, monkeypatch, snapshot)
    assert [verdicts[c] for c in CLAUSES] == ["PARTIAL", "PARTIAL", "PARTIAL"]


def test_iso_is_less_strict_about_admin_bypass_than_soc2_and_pci(client, bootstrap, monkeypatch):
    """The cross-framework delta: the same snapshot can satisfy ISO while PCI and SOC 2
    still want the gate enforced for administrators."""
    lax_admins = dict(PROTECTED, enforce_admins=False)
    snapshot = gcc.summarize([{"protection": lax_admins, "pulls": [_approved()], "default_commits": []}])
    verdicts = _sync(client, bootstrap, monkeypatch, snapshot)
    assert verdicts[("ISO-27001", "A.8.32")] == "PASS"
    assert verdicts[("SOC-2", "CC8.1")] == "PARTIAL"
    assert verdicts[("PCI-DSS", "6.5.1")] == "PARTIAL"


# --- fetch: GitHub REST -> summarize() input, against a fake API -----------------

class _FakeResponse:
    def __init__(self, body, status=200):
        self._body, self.status_code, self.links = body, status, {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self._body


class _FakeGitHub:
    """Just enough of the REST API for one repo: an unprotected main branch, one PR merged
    in the period (agent-opened, approved by its prompter), one older PR, one direct push."""

    def __init__(self):
        r = gcc.API + "/repos/acme/app"
        self.routes = {
            r: {"default_branch": "main"},
            r + "/branches/main/protection": _FakeResponse({"message": "Not Found"}, 404),
            r + "/pulls": [
                {"number": 7, "updated_at": "2026-10-02T00:00:00Z", "merged_at": "2026-10-02T00:00:00Z",
                 "user": {"login": "agent[bot]", "type": "Bot"}, "head": {"sha": "h7"}},
                {"number": 3, "updated_at": "2026-01-01T00:00:00Z", "merged_at": "2026-01-01T00:00:00Z",
                 "user": {"login": "bob", "type": "User"}, "head": {"sha": "h3"}},
            ],
            r + "/pulls/7/reviews": [{"user": {"login": "alice", "type": "User"}, "state": "APPROVED",
                                      "commit_id": "h7", "submitted_at": "2026-10-02T00:00:00Z"}],
            r + "/pulls/7/commits": [{"sha": "h7", "commit": {"message": "x\n\nCo-Authored-By: Claude <noreply@anthropic.com>"},
                                      "author": {"login": "alice", "type": "User"},
                                      "committer": {"login": "web-flow", "type": "User"}}],
            r + "/commits/h7/check-runs": {"check_runs": [{"name": "ci", "conclusion": "success"}]},
            r + "/commits/h7/status": {"statuses": []},
            r + "/commits": [{"sha": "m7"}, {"sha": "d1"}],
            r + "/commits/m7/pulls": [{"number": 7}],
            r + "/commits/d1/pulls": [],
        }
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        body = self.routes[url]
        return body if isinstance(body, _FakeResponse) else _FakeResponse(body)


def test_fetch_maps_github_onto_the_summary_and_never_writes():
    from datetime import datetime, timezone

    api = _FakeGitHub()
    repo = gcc.fetch(api, "acme/app", datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert [pr["number"] for pr in repo["pulls"]] == [7]   # the January PR is outside the period
    out = gcc.summarize([repo])
    assert out["default_branch_protected"] is False
    assert out["merges_in_period"] == 1
    assert out["ai_assisted_merges_without_independent_approval"] == 1
    assert out["direct_pushes_to_default"] == 1
    assert out["merges_with_failing_or_missing_checks"] == 0
    assert not hasattr(api, "post")  # the fake has no write verbs; fetch() never needed one
