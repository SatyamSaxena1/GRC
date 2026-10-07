"""The GitLab collector maps GitLab's API onto the same snapshot as GitHub, so the same
rules decide (ADR-020). These tests pin the mapping, especially where GitLab records less
than the rules need and the mapping must stay conservative."""

from __future__ import annotations

from datetime import datetime, timezone

from app.collectors import github_change_control as gcc
from app.collectors import gitlab_change_control as glc
from app.routers import connectors

P = "/projects/acme%2Fapp"
SINCE = datetime(2026, 9, 1, tzinfo=timezone.utc)


class _Response:
    def __init__(self, body, status=200, headers=None):
        self._body, self.status_code, self.headers = body, status, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self._body


class FakeGitLab:
    """One project: protected main (push: no one), approvals reset on push, one MR (!7)
    approved by bob, one direct push, a deploy job that shipped the MR."""

    def __init__(self, **overrides):
        self.routes = {
            P: {"default_branch": "main", "only_allow_merge_if_pipeline_succeeds": True},
            P + "/protected_branches/main": {"push_access_levels": [{"access_level": 0}],
                                             "allow_force_push": False},
            P + "/approvals": {"reset_approvals_on_push": True, "approvals_before_merge": 0},
            P + "/approval_rules": [{"approvals_required": 1}],
            P + "/merge_requests": [{"iid": 7, "sha": "h7", "merge_commit_sha": "m7",
                                     "merged_at": "2026-10-02T00:00:00Z",
                                     "web_url": "https://gitlab.com/acme/app/-/merge_requests/7",
                                     "author": {"username": "alice", "name": "Alice A"}}],
            P + "/merge_requests/7/approvals": {"approved_by": [{"user": {"username": "bob", "name": "Bob B"}}]},
            P + "/merge_requests/7/commits": [{"id": "h7", "message": "fix", "author_name": "Alice A"}],
            P + "/merge_requests/7/diffs": [{"new_path": ".gitlab-ci.yml", "old_path": ".gitlab-ci.yml",
                                             "diff": "@@ secret code @@"}],
            # The merge-request pipeline ran in a fork (project 99); 71 ran on main after the merge.
            P + "/merge_requests/7/pipelines": [
                {"id": 71, "sha": "m7", "project_id": 1, "created_at": "2026-10-02T00:05:00Z"},
                {"id": 70, "sha": "h7", "project_id": 99, "created_at": "2026-10-01T00:00:00Z"}],
            "/projects/99/pipelines/70/jobs": [{"name": "test", "status": "success"}],
            P + "/repository/commits": [
                {"id": "m7", "web_url": "https://gitlab.com/acme/app/-/commit/m7", "committed_date": "2026-10-02T00:00:00Z"},
                {"id": "d1", "web_url": "https://gitlab.com/acme/app/-/commit/d1", "committed_date": "2026-10-03T00:00:00Z",
                 "author_name": "Alice A"}],
            P + "/repository/commits/m7/merge_requests": [{"iid": 7}],
            P + "/repository/commits/d1/merge_requests": [],
            P + "/deployments": [],
            P + "/jobs": [{"name": "deploy", "status": "success", "commit": {"id": "m7"},
                           "finished_at": "2026-10-02T01:00:00Z", "user": {"username": "alice"},
                           "web_url": "https://gitlab.com/acme/app/-/jobs/9"}],
            P + "/repository/merge_base": {"id": "m7"},
        }
        self.routes.update(overrides)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        path = url.split("/api/v4", 1)[1]
        self.calls.append((path, params))
        body = self.routes[path]
        return body if isinstance(body, _Response) else _Response(body)


_LAST = {}


def _fetch(**overrides):
    fake = FakeGitLab(**overrides)
    repo = glc.fetch(glc.GitLab(fake), "acme/app", SINCE, deploy_jobs=["deploy"])
    _LAST["calls"] = fake.calls
    return repo


def glc_calls(_pr=None):
    return _LAST["calls"]


def test_a_well_run_project_maps_onto_a_clean_snapshot():
    repo = _fetch()
    out = gcc.summarize([repo])
    assert out["default_branch_protected"] and not out["admins_can_bypass"]
    assert not out["force_push_allowed_on_default"] and out["stale_reviews_dismissed"]
    assert out["required_approving_reviews"] == 1
    assert out["merges_in_period"] == 1 and out["merges_without_independent_approval"] == 0
    assert out["merges_with_failing_or_missing_checks"] == 0
    assert out["direct_pushes_to_default"] == 1
    assert out["production_deployments"] == 1 and out["deployments_of_unreviewed_changes"] == 0
    # .gitlab-ci.yml is a gate file and one approval is not enough for it.
    assert out["gate_path_merges_without_two_independent_approvals"] == 1


def test_file_names_are_kept_and_diff_text_is_dropped():
    pr = _fetch()["pulls"][0]
    assert pr["files"] == [{"filename": ".gitlab-ci.yml", "status": "modified", "previous_filename": None}]
    assert "secret code" not in str(pr)


def test_an_approver_who_wrote_commits_is_not_independent():
    commits = [{"id": "h7", "message": "fix", "author_name": "Bob B"}]
    repo = _fetch(**{P + "/merge_requests/7/commits": commits})
    assert gcc.summarize([repo])["merges_without_independent_approval"] == 1
    assert "bob approved but wrote or committed" in gcc.approval_finding(repo["pulls"][0])


def test_without_reset_on_push_an_approval_may_be_stale_so_it_does_not_count():
    repo = _fetch(**{P + "/approvals": {"reset_approvals_on_push": False}})
    assert gcc.summarize([repo])["merges_without_independent_approval"] == 1
    assert "earlier push" in gcc.approval_finding(repo["pulls"][0])


def test_project_access_token_bots_never_approve():
    approved = {"approved_by": [{"user": {"username": "project_42_bot_abc", "name": "ci"}}]}
    repo = _fetch(**{P + "/merge_requests/7/approvals": approved})
    assert gcc.summarize([repo])["merges_without_independent_approval"] == 1


def test_maintainers_who_can_push_directly_can_bypass_the_gate():
    repo = _fetch(**{P + "/protected_branches/main": {"push_access_levels": [{"access_level": 40}]}})
    assert gcc.summarize([repo])["admins_can_bypass"] is True


def test_an_unprotected_branch_reads_as_unprotected():
    repo = _fetch(**{P + "/protected_branches/main": _Response({"message": "404"}, 404)})
    out = gcc.summarize([repo])
    assert not out["default_branch_protected"] and out["force_push_allowed_on_default"]


def test_a_failed_job_is_a_failing_check_and_keeps_the_gate_live():
    jobs = [{"name": "test", "status": "failed"}]
    repo = _fetch(**{"/projects/99/pipelines/70/jobs": jobs})
    out = gcc.summarize([repo])
    assert out["merges_with_failing_or_missing_checks"] == 1
    assert out["gate_checks_never_seen_failing"] == 0


def test_pipelines_must_succeed_makes_every_job_part_of_the_gate():
    assert _fetch()["protection"]["required_checks"] == ["test"]
    off = _fetch(**{P: {"default_branch": "main", "only_allow_merge_if_pipeline_succeeds": False}})
    assert off["protection"]["required_checks"] == []


def test_a_deploy_of_a_commit_off_the_default_branch_is_found():
    jobs = [{"name": "deploy", "status": "success", "commit": {"id": "hotfix"},
             "finished_at": "2026-10-04T00:00:00Z", "user": {"username": "alice"}}]
    repo = _fetch(**{P + "/jobs": jobs, P + "/repository/merge_base": {"id": "older"}})
    assert gcc.summarize([repo])["deployments_not_from_default_branch"] == 1


def test_pagination_follows_the_next_page_header():
    calls = []

    class Paged:
        def get(self, url, params=None, timeout=None):
            calls.append(params["page"])
            return _Response([params["page"]], headers={"X-Next-Page": str(params["page"] + 1)}
                             if params["page"] < 3 else {})

    assert list(glc.GitLab(Paged()).paged("/x")) == [1, 2, 3] and calls == [1, 2, 3]


def test_gitlab_is_a_connector_source_with_the_same_snapshot():
    label, artefact, allowed = connectors.SOURCES["gitlab"]
    assert artefact == "CHANGE_CONTROL_SNAPSHOT" and allowed == set(gcc.ATTRIBUTES)
    assert "gitlab" in connectors.EXCEPTION_SOURCES


def test_settings_hidden_from_the_token_stay_conservative():
    hidden = _Response({"message": "401 Unauthorized"}, 401)
    repo = _fetch(**{P + "/approvals": hidden, P + "/approval_rules": hidden})
    out = gcc.summarize([repo])
    assert out["stale_reviews_dismissed"] is False
    assert out["merges_without_independent_approval"] == 1   # approval may predate the last push


def test_an_allowed_failure_is_not_the_gate_going_red():
    jobs = [{"name": "test", "status": "success"}, {"name": "flaky", "status": "failed", "allow_failure": True}]
    repo = _fetch(**{"/projects/99/pipelines/70/jobs": jobs})
    assert gcc.summarize([repo])["merges_with_failing_or_missing_checks"] == 0


def test_checks_come_from_the_mr_pipeline_in_the_fork_not_the_post_merge_one():
    pr = _fetch()["pulls"][0]
    assert pr["checks"] == [{"name": "test", "conclusion": "success"}]
    assert all(path != "/projects/1/pipelines/71/jobs" for path, _ in glc_calls(pr))


def test_an_earlier_failed_push_keeps_the_gate_live():
    commits = [{"id": "e1", "message": "first", "author_name": "Alice A"},
               {"id": "h7", "message": "fix", "author_name": "Alice A"}]
    pipelines = [{"id": 70, "sha": "h7", "project_id": 99, "created_at": "2026-10-01T00:00:00Z"},
                 {"id": 69, "sha": "e1", "project_id": 99, "created_at": "2026-09-30T00:00:00Z"}]
    repo = _fetch(**{P + "/merge_requests/7/commits": commits, P + "/merge_requests/7/pipelines": pipelines,
                     "/projects/99/pipelines/69/jobs": [{"name": "test", "status": "failed"}]})
    out = gcc.summarize([repo])
    assert out["merges_with_failing_or_missing_checks"] == 0   # the merged commit was green
    assert out["gate_checks_never_seen_failing"] == 0          # and the gate was seen failing first


def test_a_merged_results_pipeline_on_a_temporary_merge_commit_is_the_gate():
    """Its commit is in no branch and not one of the MR's commits; it ran before the merge."""
    pipelines = [{"id": 71, "sha": "m7", "project_id": 1, "created_at": "2026-10-02T00:05:00Z"},
                 {"id": 72, "sha": "tmp-merge-ref", "project_id": 1, "created_at": "2026-10-01T12:00:00Z"},
                 {"id": 70, "sha": "h7", "project_id": 99, "created_at": "2026-10-01T00:00:00Z"}]
    repo = _fetch(**{P + "/merge_requests/7/pipelines": pipelines,
                     "/projects/1/pipelines/72/jobs": [{"name": "test", "status": "success"},
                                                       {"name": "lint", "status": "success"}]})
    assert {c["name"] for c in repo["pulls"][0]["checks"]} == {"test", "lint"}
