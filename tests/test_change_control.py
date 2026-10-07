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
            r + "/rules/branches/main": [],
            r + "/deployments": [],
            r + "/pulls/7/files": [{"filename": "app/main.py", "status": "modified", "patch": "@@ -1 +1 @@"}],
            r + "/pulls": [
                {"number": 7, "updated_at": "2026-10-02T00:00:00Z", "merged_at": "2026-10-02T00:00:00Z",
                 "html_url": "https://github.com/acme/app/pull/7",
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
            r + "/commits": [{"sha": "m7"},
                             {"sha": "d1", "html_url": "https://github.com/acme/app/commit/d1",
                              "author": {"login": "alice"}, "commit": {"committer": {"date": "2026-10-03T00:00:00Z"}}}],
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
    rows, _ = gcc.exceptions([repo])
    assert [(r["kind"], r["repo"], r["url"]) for r in rows] == [
        ("DIRECT_PUSH", "acme/app", "https://github.com/acme/app/commit/d1"),
        ("PULL_REQUEST", "acme/app", "https://github.com/acme/app/pull/7"),
        ("GATE_CHECK", "acme/app", None),   # "ci" passed every time it ran
    ]


# --- per-merge exceptions: the rows behind the counts ------------------------------

def test_each_failed_merge_names_every_rule_it_fails_in_words():
    laundered = _pr(author="coding-agent[bot]", reviews=[("alice", "APPROVED", None)], checks=(),
                    commits=[{"sha": HEAD, "message": "x\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
                              "author_login": "alice", "committer_login": "web-flow"}])
    laundered.update(number=9, url="https://github.com/acme/app/pull/9", merged_at="2026-10-02T00:00:00Z")
    repo = {"repo": "acme/app", "protection": PROTECTED, "pulls": [_approved(), laundered],
            "default_commits": [{"sha": "d1d1d1d1d1d1d1", "has_pull": False, "author_login": "alice",
                                 "date": "2026-10-03T00:00:00Z", "url": "https://github.com/acme/app/commit/d1"}]}
    rows, left_out = gcc.exceptions([repo])
    assert left_out == 0
    assert [(r["kind"], r["ref"]) for r in rows] == [
        ("DIRECT_PUSH", "d1d1d1d1d1d1"), ("PULL_REQUEST", "#9"), ("GATE_CHECK", "ci")]
    pr_row = rows[1]
    assert pr_row["ai_assisted"] is True and pr_row["url"].endswith("/pull/9")
    assert {r["rule"] for r in pr_row["reasons"]} == {"NO_INDEPENDENT_APPROVAL", "CHECKS_FAILED_OR_MISSING"}
    details = " ".join(r["detail"] for r in pr_row["reasons"])
    assert "alice approved but wrote or committed part of the change" in details
    assert "no checks ran" in details


def test_rows_exist_exactly_for_the_counted_merges():
    pulls = [_approved(), _approved(by="alice"), _pr(reviews=[("bob", "APPROVED", "old")]),
             _approved(checks=(("ci", "failure"),))]
    repo = {"repo": "acme/app", "protection": PROTECTED, "pulls": pulls, "default_commits": []}
    counts, (rows, _) = gcc.summarize([repo]), gcc.exceptions([repo])
    unapproved = sum(any(r["rule"] == "NO_INDEPENDENT_APPROVAL" for r in row["reasons"]) for row in rows)
    failing = sum(any(r["rule"] == "CHECKS_FAILED_OR_MISSING" for r in row["reasons"]) for row in rows)
    assert unapproved == counts["merges_without_independent_approval"] == 2
    assert failing == counts["merges_with_failing_or_missing_checks"] == 1


def test_reasons_cover_stale_withdrawn_and_bot_approvals():
    assert "earlier push" in gcc.approval_finding(_pr(reviews=[("bob", "APPROVED", "old")]))
    assert "changes requested" in gcc.approval_finding(
        _pr(reviews=[("bob", "APPROVED", None), ("bob", "CHANGES_REQUESTED", None)]))
    assert "bot approvals do not count" in gcc.approval_finding(_approved(by="review-bot[bot]"))
    assert gcc.approval_finding(_pr()) == "no approving review"


def test_rows_are_capped_but_counts_are_not():
    repo = {"repo": "acme/app", "protection": PROTECTED, "pulls": [],
            "default_commits": [{"sha": f"c{i}", "has_pull": False} for i in range(7)]}
    rows, left_out = gcc.exceptions([repo], limit=5)
    assert len(rows) == 5 and left_out == 2
    assert gcc.summarize([repo])["direct_pushes_to_default"] == 7


def test_the_auditor_can_open_the_rows_from_the_stored_snapshot(client, bootstrap, monkeypatch):
    org_id, _ = bootstrap(client, frameworks=["SOC-2"])
    headers = {"authorization": f"org:{org_id}"}
    row = {"kind": "PULL_REQUEST", "repo": "acme/app", "ref": "#9", "url": "https://github.com/acme/app/pull/9",
           "at": "2026-10-02T00:00:00Z", "author": "agent[bot]", "ai_assisted": True,
           "reasons": [{"rule": "NO_INDEPENDENT_APPROVAL", "detail": "no approving review"}],
           "title": "should be dropped: not a known key"}
    attributes = gcc.summarize([{"protection": PROTECTED, "pulls": [_pr()], "default_commits": []}])

    class _WithRows(_Response):
        def json(self):
            return {"attributes": attributes, "exceptions": [row, "not a row"], "exceptions_left_out": 3}

    monkeypatch.setenv(connectors._env_key("github", "URL"), "https://collector.test/github")
    monkeypatch.setattr(connectors.requests, "get", lambda url, **_: _WithRows(attributes))
    assert client.post("/connectors/github/sync", headers=headers).status_code == 202
    evidence_id = next(c["evidence_id"] for c in client.get("/connectors", headers=headers).json()
                       if c["source"] == "github")

    body = client.get(f"/evidence/{evidence_id}/exceptions", headers=headers).json()
    assert body["exceptions_left_out"] == 3
    assert body["exceptions"] == [{k: v for k, v in row.items() if k != "title"}]

    other_org, _ = bootstrap(client, frameworks=["SOC-2"])
    assert client.get(f"/evidence/{evidence_id}/exceptions",
                      headers={"authorization": f"org:{other_org}"}).status_code == 404


def test_a_document_has_no_exception_rows(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id, content=b"policy").json()["id"]
    body = client.get(f"/evidence/{evidence_id}/exceptions", headers={"authorization": f"org:{org_id}"}).json()
    assert body == {"exceptions": [], "exceptions_left_out": 0}


# --- gate liveness: a check that has never gone red is unproven -------------------

def _with_pushes(pr, *conclusions):
    """A PR whose earlier pushes ran "ci" with these conclusions before the merged head."""
    pr["commit_checks"] = pr["checks"] + [{"name": "ci", "conclusion": c} for c in conclusions]
    return pr


def test_a_check_that_failed_on_an_earlier_push_is_live():
    repo = {"repo": "acme/app", "protection": PROTECTED, "default_commits": [],
            "pulls": [_with_pushes(_approved(), "failure", "success")]}
    assert gcc.gate_liveness(repo) == [{"check": "ci", "runs": 3, "failures": 1}]
    out = gcc.summarize([repo])
    assert (out["gate_checks_observed"], out["gate_checks_never_seen_failing"]) == (1, 0)
    assert all(r["kind"] != "GATE_CHECK" for r in gcc.exceptions([repo])[0])


def test_a_check_that_never_went_red_is_flagged_with_its_run_count():
    repo = {"repo": "acme/app", "protection": PROTECTED, "default_commits": [],
            "pulls": [_with_pushes(_approved(), "success"), _approved()]}
    assert gcc.summarize([repo])["gate_checks_never_seen_failing"] == 1
    (row,) = [r for r in gcc.exceptions([repo])[0] if r["kind"] == "GATE_CHECK"]
    assert row["ref"] == "ci" and row["reasons"][0]["rule"] == "GATE_NEVER_FAILED"
    assert "ran 3 times" in row["reasons"][0]["detail"]


def test_cancelled_runs_do_not_prove_a_gate_can_fail():
    repo = {"repo": "acme/app", "protection": PROTECTED, "default_commits": [],
            "pulls": [_with_pushes(_approved(), "cancelled")]}
    assert gcc.gate_liveness(repo)[0]["failures"] == 0


def test_required_checks_define_the_gate_when_protection_names_them():
    """An optional check that fails says nothing about the required one."""
    pr = _approved(checks=(("ci", "success"), ("docs", "success")))
    pr["commit_checks"] = pr["checks"] + [{"name": "docs", "conclusion": "failure"}]
    repo = {"repo": "acme/app", "protection": dict(PROTECTED, required_checks=["ci"]),
            "pulls": [pr], "default_commits": []}
    assert gcc.gate_liveness(repo) == [{"check": "ci", "runs": 1, "failures": 0}]


def test_a_required_check_that_never_ran_is_not_counted_as_observed():
    repo = {"repo": "acme/app", "protection": dict(PROTECTED, required_checks=["security-scan"]),
            "pulls": [_approved()], "default_commits": []}
    out = gcc.summarize([repo])
    assert out["gate_checks_observed"] == 0 and out["gate_checks_never_seen_failing"] == 0
    # ...and a merge without it is already caught as failing or missing checks only if no
    # check ran at all; a required check that never ran is a protection-settings question.


def test_gate_rows_survive_the_row_cap():
    repo = {"repo": "acme/app", "protection": PROTECTED, "pulls": [_approved()],
            "default_commits": [{"sha": f"c{i}", "has_pull": False} for i in range(10)]}
    rows, left_out = gcc.exceptions([repo], limit=4)
    assert [r["kind"] for r in rows] == ["DIRECT_PUSH"] * 3 + ["GATE_CHECK"]
    assert left_out == 7


def test_liveness_is_advisory_and_never_changes_a_verdict(client, bootstrap, monkeypatch):
    clean = gcc.summarize([{"protection": PROTECTED, "pulls": [_approved()],
                            "default_commits": [{"sha": "m1", "has_pull": True}]}])
    assert clean["gate_checks_never_seen_failing"] == 1
    verdicts = _sync(client, bootstrap, monkeypatch, clean)
    assert [verdicts[c] for c in CLAUSES] == ["PASS", "PASS", "PASS"]


def test_fetch_reads_required_checks_and_earlier_pushes():
    from datetime import datetime, timezone

    api = _FakeGitHub()
    r = gcc.API + "/repos/acme/app"
    api.routes[r + "/branches/main/protection"] = {
        "required_status_checks": {"contexts": ["ci"], "checks": [{"context": "ci"}, {"context": "lint"}]},
        "required_pull_request_reviews": {"required_approving_review_count": 1},
    }
    api.routes[r + "/pulls/7/commits"] = [
        {"sha": "e1", "commit": {"message": "first try"}, "author": {"login": "alice", "type": "User"},
         "committer": {"login": "alice", "type": "User"}},
    ] + api.routes[r + "/pulls/7/commits"]
    api.routes[r + "/commits/e1/check-runs"] = {"check_runs": [{"name": "ci", "conclusion": "failure"}]}
    api.routes[r + "/commits/e1/status"] = {"statuses": []}

    repo = gcc.fetch(api, "acme/app", datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert repo["protection"]["required_checks"] == ["ci", "lint"]
    assert gcc.gate_liveness(repo) == [{"check": "ci", "runs": 2, "failures": 1},
                                       {"check": "lint", "runs": 0, "failures": 0}]


# --- rulesets: classic protection and rulesets together, strictest wins ----------

def _ruleset(rules, bypass=(), name="main-guard", rid=1):
    return {"id": rid, "name": name, "rules": rules, "bypass_actors": None if bypass is None else list(bypass)}


PR_RULE = {"pull_request": {"required_approving_review_count": 2, "dismiss_stale_reviews_on_push": True}}


def test_a_branch_guarded_only_by_a_ruleset_is_protected():
    p = gcc.effective_protection({"enabled": False}, [_ruleset({**PR_RULE, "non_fast_forward": {}})])
    assert p["enabled"] and p["required_approving_reviews"] == 2 and p["dismiss_stale_reviews"]
    assert p["allow_force_pushes"] is False and p["enforce_admins"] is True
    assert p["sources"] == ["ruleset:main-guard"]
    out = gcc.summarize([{"protection": p, "pulls": [], "default_commits": []}])
    assert out["default_branch_protected"] and not out["admins_can_bypass"]
    assert not out["force_push_allowed_on_default"]


def test_the_strictest_layer_wins():
    classic = dict(PROTECTED, required_approving_reviews=1, dismiss_stale_reviews=False,
                   allow_force_pushes=True, required_checks=["ci"])
    rules = {**PR_RULE, "non_fast_forward": {},
             "required_status_checks": {"required_status_checks": [{"context": "lint"}]}}
    p = gcc.effective_protection(classic, [_ruleset(rules)])
    assert p["required_approving_reviews"] == 2
    assert p["dismiss_stale_reviews"] is True
    assert p["allow_force_pushes"] is False
    assert p["required_checks"] == ["ci", "lint"]
    assert p["sources"] == ["classic", "ruleset:main-guard"]


def test_a_ruleset_with_bypass_actors_does_not_bind_admins():
    p = gcc.effective_protection({"enabled": False}, [_ruleset(PR_RULE, bypass=[{"actor_type": "RepositoryRole"}])])
    assert p["enforce_admins"] is False


def test_hidden_bypass_actors_count_as_bypassable():
    """Visible only to callers who can edit the ruleset; unknown is never a pass."""
    p = gcc.effective_protection({"enabled": False}, [_ruleset(PR_RULE, bypass=None)])
    assert p["enforce_admins"] is False


def test_admins_are_bound_if_any_reviewing_layer_binds_them():
    lax_classic = dict(PROTECTED, enforce_admins=False)
    assert gcc.effective_protection(lax_classic, [_ruleset(PR_RULE, bypass=[])])["enforce_admins"] is True
    assert gcc.effective_protection(lax_classic, [_ruleset(PR_RULE, bypass=None)])["enforce_admins"] is False


def test_a_ruleset_without_a_review_rule_does_not_bind_admins_to_review():
    p = gcc.effective_protection({"enabled": False}, [_ruleset({"deletion": {}}, bypass=[])])
    assert p["enabled"] is True and p["enforce_admins"] is False and p["required_approving_reviews"] == 0


def test_no_classic_protection_and_no_rulesets_is_unprotected():
    p = gcc.effective_protection({"enabled": False}, [])
    assert not p["enabled"] and p["allow_force_pushes"] and p["sources"] == []


def test_classic_settings_are_ignored_when_classic_protection_is_off():
    stale = {"enabled": False, "required_approving_reviews": 3, "dismiss_stale_reviews": True}
    p = gcc.effective_protection(stale, [])
    assert p["required_approving_reviews"] == 0 and p["dismiss_stale_reviews"] is False


def test_fetch_reads_rulesets_and_their_bypass_lists():
    from datetime import datetime, timezone

    api = _FakeGitHub()
    r = gcc.API + "/repos/acme/app"
    api.routes[r + "/rules/branches/main"] = [
        {"type": "pull_request", "ruleset_id": 42,
         "parameters": {"required_approving_review_count": 1, "dismiss_stale_reviews_on_push": True}},
        {"type": "non_fast_forward", "ruleset_id": 42},
        {"type": "required_status_checks", "ruleset_id": 43,
         "parameters": {"required_status_checks": [{"context": "ci"}]}},
    ]
    api.routes[r + "/rulesets/42"] = {"name": "main-guard", "bypass_actors": []}
    api.routes[r + "/rulesets/43"] = _FakeResponse({"message": "Not Found"}, 404)

    p = gcc.fetch(api, "acme/app", datetime(2026, 9, 1, tzinfo=timezone.utc))["protection"]
    assert p["enabled"] and p["enforce_admins"] and not p["allow_force_pushes"]
    assert p["required_checks"] == ["ci"]
    assert p["sources"] == ["ruleset:main-guard", "ruleset:43"]


# --- gate paths: changes to CI, tests and ownership need two independent approvals ----

def _touching(*files, approvers=("bob",), status="modified"):
    pr = _pr(reviews=[(a, "APPROVED", None) for a in approvers])
    pr["files"] = [{"filename": f, "status": status} for f in files]
    return pr


def test_gate_files_are_recognised_by_path():
    pr = _touching(".github/workflows/ci.yml", "tests/unit/test_x.py", "app/conftest.py",
                   "CODEOWNERS", "web/src/Button.test.tsx", "app/main.py", "docs/readme.md")
    assert gcc.gate_paths(pr) == [".github/workflows/ci.yml", "CODEOWNERS", "app/conftest.py",
                                  "tests/unit/test_x.py", "web/src/Button.test.tsx"]


def test_a_rename_out_of_a_gate_path_still_counts():
    pr = _touching("archive/ci.yml")
    pr["files"][0].update(status="renamed", previous_filename=".github/workflows/ci.yml")
    assert gcc.gate_paths(pr) == [".github/workflows/ci.yml"]   # moved out of CI is still a CI change


def test_one_independent_approval_is_not_enough_for_a_gate_file():
    assert gcc.gate_path_under_reviewed(_touching(".github/workflows/ci.yml"))
    assert not gcc.gate_path_under_reviewed(_touching(".github/workflows/ci.yml", approvers=("bob", "carol")))
    assert not gcc.gate_path_under_reviewed(_touching("app/main.py"))


def test_an_author_approving_their_own_gate_change_does_not_count_toward_two():
    assert gcc.gate_path_under_reviewed(_touching("tests/test_x.py", approvers=("bob", "alice")))


def test_gate_counts_and_rows_name_the_files_and_the_shortfall():
    pulls = [_touching(".github/workflows/ci.yml", "tests/test_a.py", "tests/test_b.py", "tests/test_c.py"),
             _touching("app/main.py"),
             _touching("tests/test_old.py", status="removed", approvers=("bob", "carol"))]
    repo = {"repo": "acme/app", "protection": PROTECTED, "pulls": pulls, "default_commits": []}
    out = gcc.summarize([repo])
    assert out["gate_path_merges"] == 2
    assert out["gate_path_merges_without_two_independent_approvals"] == 1
    assert out["gate_files_removed"] == 1
    reasons = {r["rule"]: r["detail"] for row in gcc.exceptions([repo])[0] for r in row["reasons"]}
    assert reasons["GATE_PATH_UNDER_REVIEWED"] == (
        "changed .github/workflows/ci.yml, tests/test_a.py, tests/test_b.py (+1 more); "
        "1 independent approval, 2 required for gate files")
    assert reasons["GATE_FILE_REMOVED"].startswith("removed tests/test_old.py")


def test_a_client_can_add_gate_patterns():
    pr = _touching("policy/rego/deny.rego")
    repo = {"repo": "acme/app", "protection": PROTECTED, "pulls": [pr], "default_commits": [],
            "extra_gate_patterns": ["policy/*"]}
    assert gcc.summarize([repo])["gate_path_merges_without_two_independent_approvals"] == 1
    assert gcc.summarize([dict(repo, extra_gate_patterns=[])])["gate_path_merges"] == 0


def test_fetch_keeps_file_names_but_never_the_diff():
    from datetime import datetime, timezone

    repo = gcc.fetch(_FakeGitHub(), "acme/app", datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert repo["pulls"][0]["files"] == [{"filename": "app/main.py", "status": "modified",
                                          "previous_filename": None}]


def test_an_under_reviewed_gate_change_fails_soc2_and_pci_but_not_iso(client, bootstrap, monkeypatch):
    snapshot = gcc.summarize([{"protection": PROTECTED, "default_commits": [],
                               "pulls": [_touching(".github/workflows/ci.yml")]}])
    assert snapshot["merges_without_independent_approval"] == 0   # one approval: fine for ordinary code
    verdicts = _sync(client, bootstrap, monkeypatch, snapshot)
    assert verdicts[("ISO-27001", "A.8.32")] == "PASS"
    assert verdicts[("SOC-2", "CC8.1")] == "PARTIAL"
    assert verdicts[("PCI-DSS", "6.5.1")] == "PARTIAL"


# --- deploy reconciliation: what ran in production against what was approved -----

def _deploy(sha, on_default=True, at="2026-10-04T00:00:00Z"):
    return {"sha": sha, "on_default": on_default, "at": at, "environment": "production",
            "by": "release-bot[bot]", "url": f"https://ci.example/{sha}"}


def _repo_with_deploys(*deployments):
    reviewed = _approved()
    reviewed.update(number=1, merge_commit_sha="m-reviewed")
    unreviewed = _pr(reviews=[])
    unreviewed.update(number=2, head_sha="h-unrev", merge_commit_sha="m-unreviewed")
    return {"repo": "acme/app", "protection": PROTECTED, "pulls": [reviewed, unreviewed],
            "default_commits": [{"sha": "m-reviewed", "has_pull": True},
                                {"sha": "m-unreviewed", "has_pull": True},
                                {"sha": "direct1", "has_pull": False}],
            "deployments": list(deployments)}


def test_deploying_a_reviewed_merge_is_clean():
    repo = _repo_with_deploys(_deploy("m-reviewed"))
    assert gcc.deployment_finding(repo["deployments"][0], repo) is None


def test_each_way_of_shipping_unreviewed_code_is_named():
    repo = _repo_with_deploys(_deploy("feature-branch-sha", on_default=False), _deploy("direct1"),
                              _deploy("m-unreviewed"), _deploy("m-reviewed"), _deploy("from-2025"))
    findings = [gcc.deployment_finding(d, repo) for d in repo["deployments"]]
    assert findings[0][0] == "DEPLOY_NOT_FROM_DEFAULT"
    assert findings[1] == ("DEPLOY_OF_UNREVIEWED_CHANGE", "deployed a direct push to the default branch")
    assert findings[2] == ("DEPLOY_OF_UNREVIEWED_CHANGE", "deployed #2, merged without an independent approval")
    assert findings[3] is None
    assert findings[4] is None   # older than the period: not judged, not flagged

    out = gcc.summarize([repo])
    assert out["production_deployments"] == 5
    assert out["deployments_not_from_default_branch"] == 1
    assert out["deployments_of_unreviewed_changes"] == 2
    rows = [r for r in gcc.exceptions([repo])[0] if r["kind"] == "DEPLOYMENT"]
    assert len(rows) == 3 and all("(production)" in r["reasons"][0]["detail"] for r in rows)


def test_no_deployments_is_zero_not_a_failure(client, bootstrap, monkeypatch):
    clean = gcc.summarize([{"protection": PROTECTED, "pulls": [_approved()], "default_commits": []}])
    assert clean["production_deployments"] == 0
    verdicts = _sync(client, bootstrap, monkeypatch, clean)
    assert [verdicts[c] for c in CLAUSES] == ["PASS", "PASS", "PASS"]


def test_a_deploy_from_a_branch_fails_every_framework(client, bootstrap, monkeypatch):
    snapshot = gcc.summarize([_repo_with_deploys(_deploy("hotfix", on_default=False))
                              | {"pulls": [_approved()], "default_commits": []}])
    assert snapshot["deployments_not_from_default_branch"] == 1
    verdicts = _sync(client, bootstrap, monkeypatch, snapshot)
    assert [verdicts[c] for c in CLAUSES] == ["PARTIAL", "PARTIAL", "PARTIAL"]


def test_fetch_reads_deployments_and_deploy_jobs_and_checks_the_branch():
    from datetime import datetime, timezone

    api = _FakeGitHub()
    r = gcc.API + "/repos/acme/app"
    api.routes[r + "/deployments"] = [
        {"id": 11, "sha": "m7", "created_at": "2026-10-03T00:00:00Z", "creator": {"login": "alice"}},
        {"id": 10, "sha": "old", "created_at": "2026-01-01T00:00:00Z", "creator": {"login": "alice"}},
    ]
    api.routes[r + "/deployments/11/statuses"] = [{"state": "success", "target_url": "https://render/1"}]
    api.routes[r + "/actions/runs"] = {"workflow_runs": [
        {"id": 5, "head_sha": "hotfix", "actor": {"login": "bob"}}]}
    api.routes[r + "/actions/runs/5/jobs"] = {"jobs": [
        {"name": "deploy", "conclusion": "success", "completed_at": "2026-10-04T00:00:00Z", "html_url": "https://gh/j/5"},
        {"name": "test", "conclusion": "success"}]}
    api.routes[r + "/compare/m7...main"] = {"status": "identical"}
    api.routes[r + "/compare/hotfix...main"] = {"status": "diverged"}

    repo = gcc.fetch(api, "acme/app", datetime(2026, 9, 1, tzinfo=timezone.utc),
                     environments=["production"], deploy_jobs=["deploy"])
    assert [(d["sha"], d["environment"], d["on_default"]) for d in repo["deployments"]] == [
        ("m7", "production", True), ("hotfix", "job:deploy", False)]
    assert gcc.summarize([repo])["deployments_not_from_default_branch"] == 1


def test_pagination_keeps_the_owner_name_url_and_follows_the_page_number():
    calls = []

    class Paged:
        def get(self, url, params=None, timeout=None):
            calls.append((url, dict(params)))
            response = _FakeResponse([params["page"]])
            if params["page"] < 3:
                response.links = {"next": {"url": f"https://api.github.com/repositories/1/x?per_page=100&page={params['page'] + 1}"}}
            return response

    assert list(gcc._paged(Paged(), gcc.API + "/repos/acme/app/x", state="closed")) == [1, 2, 3]
    assert {url for url, _ in calls} == {gcc.API + "/repos/acme/app/x"}
    assert all(p["state"] == "closed" for _, p in calls)
