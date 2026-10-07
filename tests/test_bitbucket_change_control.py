"""The Bitbucket collector maps Bitbucket Cloud's API onto the same snapshot as GitHub and
GitLab (ADR-020). These tests pin the mapping and its conservative choices."""

from __future__ import annotations

from datetime import datetime, timezone

from app.collectors import bitbucket_change_control as bbc
from app.collectors import github_change_control as gcc
from app.routers import connectors

R = "/repositories/acme/app"
SINCE = datetime(2026, 9, 1, tzinfo=timezone.utc)
ALICE = {"type": "user", "nickname": "alice", "display_name": "Alice A", "uuid": "{a}"}
BOB = {"type": "user", "nickname": "bob", "display_name": "Bob B", "uuid": "{b}"}
H7 = "h7" + "0" * 38


class _Response:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self._body


def _page(*values):
    return {"values": list(values)}


class FakeBitbucket:
    """One repo: main restricted (approvals 1, reset on change, push nobody, enforce merge
    checks, no force, builds must pass), one merged PR (#7) approved by bob, one direct push,
    one production deployment of the PR's merge commit."""

    def __init__(self, **overrides):
        self.routes = {
            R: {"mainbranch": {"name": "main"}},
            R + "/branch-restrictions": _page(
                *[{"kind": k, "branch_match_kind": "glob", "pattern": "main", "users": [], "groups": [], "value": v}
                  for k, v in [("require_approvals_to_merge", 1), ("reset_pullrequest_approvals_on_change", None),
                               ("push", None), ("enforce_merge_checks", None), ("force", None),
                               ("require_passing_builds_to_merge", None)]],
                {"kind": "push", "branch_match_kind": "glob", "pattern": "release/*", "users": [ALICE], "groups": []}),
            R + "/effective-branching-model": {},
            R + "/pullrequests": _page({"id": 7}),
            R + "/pullrequests/7/activity": _page({"update": {"state": "OPEN", "date": "2026-10-01T00:00:00+00:00"}},
                                                  {"update": {"state": "MERGED", "date": "2026-10-02T00:00:00+00:00"}}),
            R + "/pullrequests/7": {"id": 7, "author": ALICE, "source": {"commit": {"hash": H7[:12]}},
                                    "links": {"html": {"href": "https://bitbucket.org/acme/app/pull-requests/7"}},
                                    "merge_commit": {"hash": "m7" + "0" * 38},
                                    "participants": [{"user": BOB, "state": "approved", "participated_on": "2026-10-01T12:00:00+00:00"},
                                                     {"user": {"type": "app_user", "nickname": "ci"}, "state": None}]},
            R + "/pullrequests/7/commits": _page({"hash": H7, "message": "fix", "author": {"raw": "Alice A <a@x>", "user": ALICE}}),
            R + "/pullrequests/7/statuses": _page({"name": "build", "state": "SUCCESSFUL", "commit": {"hash": H7}}),
            R + "/pullrequests/7/diffstat": _page({"status": "modified", "new": {"path": "bitbucket-pipelines.yml"},
                                                   "old": {"path": "bitbucket-pipelines.yml"}}),
            R + "/commits/main": _page(
                {"hash": "d1" + "0" * 38, "date": "2026-10-03T00:00:00+00:00", "author": {"raw": "Alice A <a@x>"}},
                {"hash": "m7" + "0" * 38, "date": "2026-10-02T00:00:00+00:00", "author": {"raw": "x"}},
                {"hash": "old", "date": "2026-08-01T00:00:00+00:00"}),
            R + "/environments/": _page({"name": "Production", "uuid": "{env}"}),
            R + "/deployments/": _page({"state": {"completed_on": "2026-10-02T01:00:00+00:00", "status": {"name": "SUCCESSFUL"}},
                                        "release": {"commit": {"hash": "m7" + "0" * 38}, "url": "https://bb/deploy/1"}}),
            R + "/merge-base/" + "m7" + "0" * 38 + "..main": {"hash": "m7" + "0" * 38},
        }
        self.routes.update(overrides)

    def get(self, url, params=None, timeout=None):
        body = self.routes[url.split("/2.0", 1)[1]]
        return body if isinstance(body, _Response) else _Response(body)


def _fetch(**overrides):
    return bbc.fetch(bbc.Bitbucket(FakeBitbucket(**overrides)), "acme/app", SINCE)


def test_a_well_run_repo_maps_onto_the_snapshot():
    repo = _fetch()
    out = gcc.summarize([repo])
    assert out["default_branch_protected"] and not out["admins_can_bypass"]
    assert not out["force_push_allowed_on_default"] and out["stale_reviews_dismissed"]
    assert out["required_approving_reviews"] == 1
    assert out["merges_in_period"] == 1 and out["merges_without_independent_approval"] == 0
    assert out["merges_with_failing_or_missing_checks"] == 0
    assert out["direct_pushes_to_default"] == 1                  # d1; m7 came from the PR, "old" is out of period
    assert out["production_deployments"] == 1 and out["deployments_of_unreviewed_changes"] == 0
    assert out["gate_path_merges_without_two_independent_approvals"] == 1   # pipelines file, one approval
    assert repo["protection"]["required_checks"] == ["build"]


def test_an_approver_who_authored_a_commit_is_not_independent():
    commits = _page({"hash": H7, "message": "fix", "author": {"raw": "Bob B <b@x>", "user": BOB}})
    repo = _fetch(**{R + "/pullrequests/7/commits": commits})
    assert "bob approved but wrote or committed" in gcc.approval_finding(repo["pulls"][0])


def test_an_unlinked_commit_author_is_matched_by_name():
    commits = _page({"hash": H7, "message": "fix", "author": {"raw": "Bob B <bob@laptop>"}})
    repo = _fetch(**{R + "/pullrequests/7/commits": commits})
    assert gcc.approval_finding(repo["pulls"][0]) is not None


def test_without_reset_on_change_an_approval_may_be_stale():
    restrictions = _page({"kind": "require_approvals_to_merge", "branch_match_kind": "glob", "pattern": "main",
                          "users": [], "groups": [], "value": 1})
    repo = _fetch(**{R + "/branch-restrictions": restrictions})
    assert "earlier push" in gcc.approval_finding(repo["pulls"][0])


def test_hidden_restrictions_read_as_unprotected_and_approvals_as_possibly_stale():
    repo = _fetch(**{R + "/branch-restrictions": _Response({}, 403)})
    out = gcc.summarize([repo])
    assert not out["default_branch_protected"] and out["merges_without_independent_approval"] == 1


def test_admins_can_bypass_without_enforced_merge_checks():
    restrictions = _page(*[{"kind": k, "branch_match_kind": "glob", "pattern": "main", "users": [], "groups": []}
                           for k in ("push", "force")])
    assert gcc.summarize([_fetch(**{R + "/branch-restrictions": restrictions})])["admins_can_bypass"] is True


def test_a_user_exempt_from_the_push_restriction_can_bypass():
    restrictions = _page({"kind": "push", "branch_match_kind": "glob", "pattern": "main", "users": [ALICE], "groups": []},
                         {"kind": "enforce_merge_checks", "branch_match_kind": "glob", "pattern": "main"})
    assert gcc.summarize([_fetch(**{R + "/branch-restrictions": restrictions})])["admins_can_bypass"] is True


def test_restrictions_by_branching_model_apply_to_the_matching_branch():
    restrictions = _page({"kind": "force", "branch_match_kind": "branching_model", "branch_type": "production",
                          "users": [], "groups": []})
    model = {"production": {"branch": {"name": "main"}}}
    repo = _fetch(**{R + "/branch-restrictions": restrictions, R + "/effective-branching-model": model})
    assert repo["protection"]["allow_force_pushes"] is False


def test_a_failed_build_on_the_merged_commit_fails_the_merge():
    statuses = _page({"name": "build", "state": "FAILED", "commit": {"hash": H7}})
    assert gcc.summarize([_fetch(**{R + "/pullrequests/7/statuses": statuses})])["merges_with_failing_or_missing_checks"] == 1


def test_a_deployment_of_a_commit_outside_main_is_found():
    deploys = _page({"state": {"completed_on": "2026-10-04T00:00:00+00:00", "status": {"name": "SUCCESSFUL"}},
                     "release": {"commit": {"hash": "hotfix"}}})
    repo = _fetch(**{R + "/deployments/": deploys, R + "/merge-base/hotfix..main": {"hash": "other"}})
    assert gcc.summarize([repo])["deployments_not_from_default_branch"] == 1


def test_pagination_follows_the_next_url():
    class Paged:
        def __init__(self):
            self.urls = []

        def get(self, url, params=None, timeout=None):
            self.urls.append(url)
            n = len(self.urls)
            return _Response({"values": [n], **({"next": f"{bbc.API}/x?page={n + 1}"} if n < 3 else {})})

    fake = Paged()
    assert list(bbc.Bitbucket(fake).paged("/x")) == [1, 2, 3]


def test_bitbucket_is_a_connector_source_with_the_same_snapshot():
    label, artefact, allowed = connectors.SOURCES["bitbucket"]
    assert artefact == "CHANGE_CONTROL_SNAPSHOT" and allowed == set(gcc.ATTRIBUTES)
    assert "bitbucket" in connectors.EXCEPTION_SOURCES


def test_rate_limits_are_waited_out_then_given_up_on():
    waits = []

    class Limited:
        def __init__(self, limited):
            self.left = limited

        def get(self, url, params=None, timeout=None):
            if self.left:
                self.left -= 1
                r = _Response({}, 429)
                r.headers = {"Retry-After": "7"}
                return r
            return _Response({"ok": True})

    assert bbc.Bitbucket(Limited(2), sleep=waits.append).get("/x") == {"ok": True}
    assert waits == [7.0, 7.0]
    try:
        bbc.Bitbucket(Limited(9), sleep=waits.append).get("/x")
        raise AssertionError("should give up")
    except RuntimeError as exc:
        assert "429" in str(exc)


def test_the_head_is_the_source_commit_not_the_merge_commit_listed_first():
    commits = _page({"hash": "m7" + "0" * 38, "message": "Merged in feature", "author": {"raw": "Alice A", "user": ALICE}},
                    {"hash": H7, "message": "fix", "author": {"raw": "Alice A", "user": ALICE}})
    pr = _fetch(**{R + "/pullrequests/7/commits": commits})["pulls"][0]
    assert pr["head_sha"] == H7
    assert pr["checks"] == [{"name": "build", "conclusion": "success"}]
