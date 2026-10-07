"""Change-control facts from a client's GitLab projects (ADR-020).

The GitLab half of app/collectors/github_change_control.py. Only `fetch()` differs: it maps
GitLab's REST API (v4, gitlab.com or self-managed) onto the same normalized dicts, and the
rules — independent approval, checks, gate paths, gate liveness, deploy reconciliation —
are the GitHub module's `summarize()` and `exceptions()`, unchanged. So a SOC 2 verdict
means the same thing whichever platform the code lives on.

Run it as a collector:

    GITLAB_TOKEN=... python -m app.collectors.gitlab_change_control --project group/name --days 90

Where GitLab does not record something the rules need, the mapping is conservative — a
possible false gap, never a false pass — and says so beside the line that does it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import quote

from app.collectors.github_change_control import (
    MAX_COMMITS_CHECKED, effective_protection, exceptions, summarize,
)

DEFAULT_URL = "https://gitlab.com"
MAX_DEPLOY_JOBS = 500

# GitLab job and pipeline states, onto the GitHub conclusions summarize() reads.
_STATUS = {"success": "success", "failed": "failure", "canceled": "cancelled",
           "skipped": "skipped", "manual": "skipped"}
_NO_ONE = 0  # GitLab access level "No one"


class GitLab:
    """Read-only access to one GitLab instance's REST API."""

    def __init__(self, session, url: str = DEFAULT_URL):
        self.session, self.api = session, url.rstrip("/") + "/api/v4"

    def get(self, path: str, **params) -> Any:
        response = self.session.get(self.api + path, params=params or None, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_or_none(self, path: str, **params) -> Any:
        """None when the resource is absent or hidden from this token (401/403/404). Callers
        read None as "unknown" and stay conservative: a possible false gap, never a pass."""
        response = self.session.get(self.api + path, params=params or None, timeout=30)
        if response.status_code in (401, 403, 404):
            return None
        response.raise_for_status()
        return response.json()

    def paged(self, path: str, _hidden_ok: bool = False, **params) -> Iterable[dict]:
        params = {**params, "per_page": 100, "page": 1}
        while True:
            response = self.session.get(self.api + path, params=params, timeout=30)
            if _hidden_ok and response.status_code in (401, 403):
                # Not "none": the token cannot see them. Said loudly, because reading this as
                # zero would let the deploy rules pass by omission.
                print(f"warning: {path} is hidden from this token; deployments are not "
                      "reconciled (the token needs at least Reporter access)", file=sys.stderr)
                return
            response.raise_for_status()
            yield from response.json()
            next_page = (response.headers or {}).get("X-Next-Page") or (response.headers or {}).get("x-next-page")
            if not next_page:
                return
            params = {**params, "page": int(next_page)}


def _user(raw: dict | None) -> dict | None:
    if not raw:
        return None
    username = raw.get("username") or ""
    # Project and group access tokens act through generated "project_<id>_bot_..." users.
    is_bot = bool(raw.get("bot")) or (username.startswith(("project_", "group_")) and "_bot" in username)
    return {"login": username, "is_bot": is_bot, "name": raw.get("name")}


def _job_check(job: dict) -> dict:
    status = job.get("status")
    if status == "failed" and job.get("allow_failure"):
        status = "skipped"  # an allowed failure never blocked the merge, so it is not the gate going red
    return {"name": job.get("name"), "conclusion": _STATUS.get(status, status)}


def _mr_checks(gl: GitLab, project: str, iid: int, merged_at: str) -> tuple[list[dict], list[dict]]:
    """(checks of the pipeline that gated the merge, checks of every pipeline the MR ran).

    Read from the MR's own pipelines, not the project's pipelines-by-commit: merge-request
    pipelines often run in the contributor's fork, and "merged results" pipelines run on a
    temporary merge commit that belongs to no branch, so both only appear on the MR. The list
    also holds pipelines that ran on the target branch after the merge; only pipelines that
    started before the merge count, and the latest of those is the one that gated it."""
    pipelines = [p for p in gl.paged(f"/projects/{project}/merge_requests/{iid}/pipelines")
                 if (p.get("created_at") or "") <= (merged_at or "~")]
    pipelines.sort(key=lambda p: p.get("id") or 0, reverse=True)
    head_checks, all_checks, seen = [], [], 0
    for pipeline in pipelines:
        seen += 1
        if seen > MAX_COMMITS_CHECKED:
            break
        jobs = [_job_check(j) for j in gl.paged(
            f"/projects/{pipeline.get('project_id') or project}/pipelines/{pipeline['id']}/jobs", True)]
        all_checks += jobs
        if seen == 1:
            head_checks = jobs  # the latest pipeline before the merge: what gated it
    return head_checks, all_checks


def _classic_protection(gl: GitLab, project: str, branch: str, settings: dict) -> dict:
    """Protected-branch settings plus the project's merge-request approval settings,
    in the shape github_change_control.effective_protection() takes."""
    protected = gl.get_or_none(f"/projects/{project}/protected_branches/{quote(branch, safe='')}")
    if not protected:
        return {"enabled": False}
    approvals = gl.get_or_none(f"/projects/{project}/approvals") or {}
    rules = gl.get_or_none(f"/projects/{project}/approval_rules") or []
    # Only rules that apply to the default branch: a rule can target selected protected
    # branches, and counting one scoped to another branch would overstate the gate.
    def applies(rule: dict) -> bool:
        scoped = rule.get("protected_branches") or []
        return bool(rule.get("applies_to_all_protected_branches")) or not scoped or \
            any(b.get("name") == branch for b in scoped)

    required = max([int(r.get("approvals_required") or 0) for r in rules if applies(r)]
                   + [int(approvals.get("approvals_before_merge") or 0)])
    push_levels = [p.get("access_level") for p in protected.get("push_access_levels", [])]
    return {
        "enabled": True,
        "required_approving_reviews": required,
        "dismiss_stale_reviews": bool(approvals.get("reset_approvals_on_push")),
        # The gate binds everyone only when nobody may push to the branch directly.
        "enforce_admins": bool(push_levels) and all(level == _NO_ONE for level in push_levels),
        "allow_force_pushes": bool(protected.get("allow_force_push")),
        # GitLab's gate is "pipelines must succeed": the whole pipeline, not named checks.
        "required_checks": [],
        "pipeline_must_succeed": bool(settings.get("only_allow_merge_if_pipeline_succeeds")),
    }


def _merge_requests(gl: GitLab, project: str, branch: str, cutoff: str,
                    approvals_reset_on_push: bool) -> list[dict]:
    pulls = []
    for mr in gl.paged(f"/projects/{project}/merge_requests", state="merged", target_branch=branch,
                       updated_after=cutoff, order_by="updated_at", sort="desc"):
        if not mr.get("merged_at") or mr["merged_at"] < cutoff:
            continue
        iid, head = mr["iid"], mr.get("sha")
        approval = gl.get_or_none(f"/projects/{project}/merge_requests/{iid}/approvals") or {}
        # GitLab does not record which commit an approval was given on. Only when approvals
        # reset on every push is an approval known to cover the merged commit; otherwise it
        # may predate the last push, so it is treated as stale.
        approved_on = head if approvals_reset_on_push else None
        commits = list(gl.paged(f"/projects/{project}/merge_requests/{iid}/commits"))
        # GitLab commits carry a name and email but no username. A contributor is matched to an
        # approver by name, so an approver who also wrote commits does not count as independent.
        commit_authors = {(c.get("author_name") or "").strip().lower() for c in commits}
        reviews = []
        for entry in approval.get("approved_by", []):
            user = _user(entry.get("user"))
            if user and (user.get("name") or "").strip().lower() in commit_authors - {""}:
                user = dict(user, contributed=True)
            reviews.append({"user": user, "state": "APPROVED", "commit_id": approved_on,
                            "submitted_at": mr.get("merged_at")})
        head_checks, commit_checks = _mr_checks(gl, project, iid, mr.get("merged_at"))
        # File names come from the diffs endpoint, which also returns diff text; only the
        # names and status are kept (ADR-020 data minimisation).
        diffs = gl.paged(f"/projects/{project}/merge_requests/{iid}/diffs")
        pulls.append({
            "number": iid, "url": mr.get("web_url"), "merged_at": mr.get("merged_at"),
            "merge_commit_sha": mr.get("merge_commit_sha") or mr.get("squash_commit_sha"),
            "author": _user(mr.get("author")), "head_sha": head, "reviews": reviews,
            "commits": [
                {"sha": c["id"], "message": c.get("message") or "",
                 # Usernames are unknown for commits; approvals by a commit author are caught
                 # by the name match above, via `contributed`.
                 "author_login": None, "committer_login": None, "author_is_bot": False}
                for c in commits
            ],
            "checks": head_checks,
            "commit_checks": commit_checks,
            "files": [
                {"filename": d.get("new_path"),
                 "status": "removed" if d.get("deleted_file") else
                           "renamed" if d.get("renamed_file") else
                           "added" if d.get("new_file") else "modified",
                 "previous_filename": d.get("old_path") if d.get("renamed_file") else None}
                for d in diffs
            ],
        })
    return pulls


def _deployments(gl: GitLab, project: str, cutoff: str, environments: Iterable[str],
                 deploy_jobs: Iterable[str]) -> list[dict]:
    out = []
    for env in environments:
        for d in gl.paged(f"/projects/{project}/deployments", True, environment=env, status="success",
                          updated_after=cutoff, order_by="updated_at", sort="desc"):
            out.append({"sha": d.get("sha"), "at": d.get("created_at"), "environment": env,
                        "by": (d.get("user") or {}).get("username"),
                        "url": (d.get("deployable") or {}).get("web_url")})
    names, seen = set(deploy_jobs), 0
    if names:
        for job in gl.paged(f"/projects/{project}/jobs", True, **{"scope[]": "success"}):
            seen += 1
            if seen > MAX_DEPLOY_JOBS or (job.get("finished_at") or "") < cutoff:
                break  # newest first
            if job.get("name") in names:
                out.append({"sha": (job.get("commit") or {}).get("id"), "at": job.get("finished_at"),
                            "environment": f"job:{job['name']}",
                            "by": (job.get("user") or {}).get("username"), "url": job.get("web_url")})
    return out


def _on_default(gl: GitLab, project: str, branch: str, sha: str, cache: dict) -> bool:
    """Is `sha` in the default branch's history? Exactly when it is the merge base of
    itself and the branch."""
    if sha not in cache:
        base = gl.get_or_none(f"/projects/{project}/repository/merge_base", **{"refs[]": [sha, branch]})
        cache[sha] = bool(base) and base.get("id") == sha
    return cache[sha]


def fetch(gl: GitLab, path: str, since: datetime, environments: Iterable[str] = ("production",),
          deploy_jobs: Iterable[str] = ()) -> dict:
    """One project, as github_change_control.summarize() expects it. Reads only."""
    project = quote(path, safe="")
    settings = gl.get(f"/projects/{project}")
    branch = settings["default_branch"]
    cutoff = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    classic = _classic_protection(gl, project, branch, settings)
    protection = effective_protection(classic, [])
    pulls = _merge_requests(gl, project, branch, cutoff, bool(classic.get("dismiss_stale_reviews")))
    if classic.get("pipeline_must_succeed"):
        # "Pipelines must succeed" gates on the pipeline as a whole, so every job that ran on
        # a merged commit is part of the gate.
        protection["required_checks"] = sorted({c["name"] for pr in pulls for c in pr["checks"] if c.get("name")})

    default_commits = [
        {"sha": c["id"], "url": c.get("web_url"), "date": c.get("committed_date"),
         "author_login": c.get("author_name"),
         "has_pull": bool(gl.get(f"/projects/{project}/repository/commits/{c['id']}/merge_requests"))}
        for c in gl.paged(f"/projects/{project}/repository/commits", ref_name=branch, since=cutoff)
    ]
    cache: dict[str, bool] = {}
    deployments = [
        dict(d, on_default=_on_default(gl, project, branch, d["sha"], cache))
        for d in _deployments(gl, project, cutoff, environments, deploy_jobs) if d.get("sha")
    ]
    return {"repo": path, "protection": protection, "pulls": pulls,
            "default_commits": default_commits, "deployments": deployments}


def main(argv: list[str] | None = None) -> int:
    import requests

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--project", action="append", required=True, help="group/name; repeatable")
    parser.add_argument("--url", default=os.environ.get("GITLAB_URL", DEFAULT_URL),
                        help="GitLab instance (default: gitlab.com, or $GITLAB_URL)")
    parser.add_argument("--days", type=int, default=90, help="audit period, ending now")
    parser.add_argument("--environment", action="append", default=None,
                        help="deployment environment that is production (default: production); repeatable")
    parser.add_argument("--deploy-job", action="append", default=[],
                        help="name of a CI job whose successful run deploys to production; repeatable")
    parser.add_argument("--gate-path", action="append", default=[],
                        help="extra gate file pattern (fnmatch), added to the defaults; repeatable")
    args = parser.parse_args(argv)

    session = requests.Session()
    if token := os.environ.get("GITLAB_TOKEN"):
        session.headers["PRIVATE-TOKEN"] = token
    gl = GitLab(session, args.url)
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    repos = [dict(fetch(gl, p, since, args.environment or ["production"], args.deploy_job),
                  extra_gate_patterns=args.gate_path) for p in args.project]
    rows, left_out = exceptions(repos)
    json.dump({"attributes": summarize(repos), "exceptions": rows,
               "exceptions_left_out": left_out}, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
