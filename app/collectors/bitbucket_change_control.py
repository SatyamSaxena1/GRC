"""Change-control facts from a client's Bitbucket Cloud repositories (ADR-020).

The Bitbucket half of the collectors, alongside github_change_control.py and
gitlab_change_control.py. Only `fetch()` differs: it maps Bitbucket's REST API 2.0 onto the
same normalized dicts, and the GitHub module's `summarize()` and `exceptions()` decide.

Run it as a collector:

    BITBUCKET_TOKEN=... python -m app.collectors.bitbucket_change_control --repo workspace/slug --days 90

(or BITBUCKET_USERNAME + BITBUCKET_APP_PASSWORD). As with GitLab, wherever Bitbucket records
less than the rules need, the mapping is conservative and says so where it does it.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from app.collectors.github_change_control import (
    MAX_COMMITS_CHECKED, effective_protection, exceptions, summarize,
)

API = "https://api.bitbucket.org/2.0"
MAX_DEFAULT_COMMITS = 2000
MAX_RETRIES = 3
MAX_RETRY_WAIT_S = 120

_STATE = {"SUCCESSFUL": "success", "FAILED": "failure", "STOPPED": "cancelled", "INPROGRESS": "pending"}


class Bitbucket:
    """Read-only access to the Bitbucket Cloud REST API."""

    def __init__(self, session, api: str = API, sleep=time.sleep):
        self.session, self.api, self._sleep = session, api.rstrip("/"), sleep

    def _get(self, url: str, params) -> Any:
        """One GET, waiting out rate limits: Bitbucket answers 429 with Retry-After, and an
        hourly quota is easy to hit on a busy repository. Gives up after MAX_RETRIES."""
        for attempt in range(MAX_RETRIES + 1):
            response = self.session.get(url, params=params, timeout=30)
            if response.status_code != 429 or attempt == MAX_RETRIES:
                return response
            wait = (getattr(response, "headers", None) or {}).get("Retry-After")
            self._sleep(min(MAX_RETRY_WAIT_S, float(wait) if wait else 2.0 ** attempt * 5))
        return response

    def get(self, path: str, **params) -> Any:
        response = self._get(self.api + path, params or None)
        response.raise_for_status()
        return response.json()

    def get_or_none(self, path: str, **params) -> Any:
        """None when absent or hidden from this token: read as unknown, never as a pass."""
        response = self._get(self.api + path, params or None)
        if response.status_code in (401, 403, 404):
            return None
        response.raise_for_status()
        return response.json()

    def paged(self, path: str, _hidden_ok: bool = False, **params) -> Iterable[dict]:
        """Every value across pages. Bitbucket returns the next page as a full URL."""
        url, params = self.api + path, {**params, "pagelen": params.get("pagelen", 50)}
        while url:
            response = self._get(url, params)
            if _hidden_ok and response.status_code in (401, 403, 404):
                print(f"warning: {path} is hidden from this token; deployments are not reconciled "
                      "(the token needs repository and pipeline read access)", file=sys.stderr)
                return
            response.raise_for_status()
            body = response.json()
            yield from body.get("values", [])
            url, params = body.get("next"), None


def _person(raw: dict | None) -> dict | None:
    """A Bitbucket account as the shared rules see it. The login is the nickname, for
    readable rows; the uuid is kept for matching, because nicknames are not unique."""
    if not raw:
        return None
    return {"login": raw.get("nickname") or raw.get("display_name") or raw.get("uuid"),
            "is_bot": raw.get("type") in ("app_user", "team"), "uuid": raw.get("uuid"),
            "name": raw.get("display_name")}


def _applies(restriction: dict, branch: str, model: dict) -> bool:
    """Does a branch restriction cover the default branch? By glob, or by branching-model
    type when the default branch is that type's branch."""
    if restriction.get("branch_match_kind") == "glob":
        return fnmatch.fnmatchcase(branch, restriction.get("pattern") or "")
    branch_type = restriction.get("branch_type")
    typed = (model.get(branch_type) or {}).get("branch") or {}
    return bool(branch_type) and typed.get("name") == branch


def _classic_protection(bb: Bitbucket, repo: str, branch: str) -> dict:
    """Branch restrictions in the shape effective_protection() takes. Reading them needs
    repository admin; when hidden, the branch reads as unprotected — a possible false gap,
    never a false pass."""
    restrictions = bb.get_or_none(f"/repositories/{repo}/branch-restrictions", pagelen=100)
    if restrictions is None:
        return {"enabled": False}
    model = bb.get_or_none(f"/repositories/{repo}/effective-branching-model") or {}
    active = [r for r in restrictions.get("values", []) if _applies(r, branch, model)]
    kinds = {r.get("kind"): r for r in active}
    if not active:
        return {"enabled": False}

    def nobody_exempt(kind: str) -> bool:
        r = kinds.get(kind)
        return bool(r) and not r.get("users") and not r.get("groups")

    return {
        "enabled": True,
        "required_approving_reviews": int((kinds.get("require_approvals_to_merge") or {}).get("value") or 0),
        "dismiss_stale_reviews": "reset_pullrequest_approvals_on_change" in kinds,
        # Admins can skip merge checks unless "enforce merge checks" is on, and anyone listed on
        # the push restriction can push without a pull request at all.
        "enforce_admins": nobody_exempt("push") and "enforce_merge_checks" in kinds,
        "allow_force_pushes": not nobody_exempt("force"),
        "required_checks": [],
        "builds_must_pass": "require_passing_builds_to_merge" in kinds,
    }


def _merged_at(bb: Bitbucket, repo: str, pr_id: int) -> tuple[str | None, list[dict]]:
    """(when it was merged, the activity log). Bitbucket has no merged_at field; the MERGED
    update in the activity log is the record of it."""
    activity = list(bb.paged(f"/repositories/{repo}/pullrequests/{pr_id}/activity"))
    merged = [a["update"].get("date") for a in activity
              if (a.get("update") or {}).get("state") == "MERGED"]
    return (max(merged) if merged else None), activity


def _pull(bb: Bitbucket, repo: str, summary: dict, merged_at: str, approvals_reset: bool) -> dict:
    pr_id = summary["id"]
    pr = bb.get(f"/repositories/{repo}/pullrequests/{pr_id}")
    commits = list(bb.paged(f"/repositories/{repo}/pullrequests/{pr_id}/commits"))
    # The head is the source branch's commit. Not commits[0]: for a merged PR that list starts
    # with the merge commit. The API gives the source commit as a short hash; resolve it.
    source = ((pr.get("source") or {}).get("commit") or {}).get("hash") or ""
    head = next((c["hash"] for c in commits if source and c["hash"].startswith(source)), source or None)

    author_uuids = {((c.get("author") or {}).get("user") or {}).get("uuid") for c in commits} - {None}
    unlinked_names = {((c.get("author") or {}).get("raw") or "").split("<")[0].strip().lower()
                      for c in commits if not (c.get("author") or {}).get("user")} - {""}
    reviews = []
    for p in pr.get("participants", []):
        user = _person(p.get("user"))
        state = {"approved": "APPROVED", "changes_requested": "CHANGES_REQUESTED"}.get(p.get("state"))
        if not user or not state:
            continue
        if user["uuid"] in author_uuids or (user.get("name") or "").strip().lower() in unlinked_names:
            user = dict(user, contributed=True)
        # Bitbucket does not record the commit an approval was given on. Only when approvals
        # reset on every change is an approval known to cover the merged commit.
        reviews.append({"user": user, "state": state, "commit_id": head if approvals_reset else None,
                        "submitted_at": p.get("participated_on")})

    statuses = list(bb.paged(f"/repositories/{repo}/pullrequests/{pr_id}/statuses"))

    def as_check(s: dict) -> dict:
        return {"name": s.get("name") or s.get("key"), "conclusion": _STATE.get(s.get("state"), s.get("state"))}

    pushes = {c["hash"] for c in commits[:MAX_COMMITS_CHECKED]}
    merge_commit = (pr.get("merge_commit") or {}).get("hash")
    if merge_commit and len(merge_commit) < 40:
        merge_commit = (bb.get_or_none(f"/repositories/{repo}/commit/{merge_commit}") or {}).get("hash", merge_commit)
    return {
        "number": pr_id, "url": ((pr.get("links") or {}).get("html") or {}).get("href"),
        "merged_at": merged_at, "merge_commit_sha": merge_commit,
        "author": _person(pr.get("author")), "head_sha": head, "reviews": reviews,
        "commits": [
            {"sha": c["hash"], "message": c.get("message") or "",
             "author_login": _person((c.get("author") or {}).get("user") or None)["login"]
             if (c.get("author") or {}).get("user") else None,
             "committer_login": None, "author_is_bot": False}
            for c in commits
        ],
        "checks": [as_check(s) for s in statuses if (s.get("commit") or {}).get("hash") == head],
        "commit_checks": [as_check(s) for s in statuses if (s.get("commit") or {}).get("hash") in pushes],
        # The diffstat endpoint returns paths and status only — no diff text to discard.
        "files": [
            {"filename": (d.get("new") or d.get("old") or {}).get("path"),
             "status": d.get("status"),
             "previous_filename": (d.get("old") or {}).get("path") if d.get("status") == "renamed" else None}
            for d in bb.paged(f"/repositories/{repo}/pullrequests/{pr_id}/diffstat")
        ],
        "_commit_set": {c["hash"] for c in commits},
    }


def _deployments(bb: Bitbucket, repo: str, cutoff: str, environments: Iterable[str]) -> list[dict]:
    """Successful Bitbucket Deployments to the named environments (case-insensitive)."""
    wanted = {e.lower() for e in environments}
    envs = [e for e in bb.paged(f"/repositories/{repo}/environments/", True)
            if (e.get("name") or "").lower() in wanted]
    out = []
    for env in envs:
        for d in bb.paged(f"/repositories/{repo}/deployments/", True, environment=env["uuid"],
                          sort="-state.completed_on"):
            state = d.get("state") or {}
            done = state.get("completed_on") or ""
            if done and done < cutoff:
                break
            if (state.get("status") or {}).get("name") == "SUCCESSFUL":
                commit = ((d.get("release") or {}).get("commit") or {}).get("hash")
                out.append({"sha": commit, "at": done, "environment": env.get("name"),
                            "by": None, "url": ((d.get("release") or {}).get("url"))})
    return out


def _on_default(bb: Bitbucket, repo: str, branch: str, sha: str, cache: dict) -> bool:
    if sha not in cache:
        base = bb.get_or_none(f"/repositories/{repo}/merge-base/{sha}..{branch}")
        # The commit is in the branch's history exactly when it is the merge base of both.
        cache[sha] = bool(base) and str(base.get("hash", "")).startswith(sha)
    return cache[sha]


def fetch(bb: Bitbucket, repo: str, since: datetime, environments: Iterable[str] = ("production",)) -> dict:
    """One repository, as github_change_control.summarize() expects it. Reads only."""
    info = bb.get(f"/repositories/{repo}")
    branch = (info.get("mainbranch") or {}).get("name") or "main"
    cutoff = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    classic = _classic_protection(bb, repo, branch)
    protection = effective_protection(classic, [])
    query = f'destination.branch.name = "{branch}" AND updated_on >= {cutoff}'
    pulls = []
    for summary in bb.paged(f"/repositories/{repo}/pullrequests", state="MERGED", q=query, sort="-updated_on"):
        merged_at, _ = _merged_at(bb, repo, summary["id"])
        if merged_at and merged_at >= cutoff:
            pulls.append(_pull(bb, repo, summary, merged_at, bool(classic.get("dismiss_stale_reviews"))))
    if classic.get("builds_must_pass"):
        protection["required_checks"] = sorted({c["name"] for pr in pulls for c in pr["checks"] if c.get("name")})

    # Bitbucket's commit→PR link needs an add-on, so a direct push is worked out instead: a
    # commit on the default branch in the period that is neither a PR's merge commit nor one
    # of a PR's own commits.
    from_prs = {pr.get("merge_commit_sha") for pr in pulls} | {s for pr in pulls for s in pr.pop("_commit_set")}
    default_commits, seen = [], 0
    for c in bb.paged(f"/repositories/{repo}/commits/{branch}"):
        seen += 1
        if seen > MAX_DEFAULT_COMMITS or (c.get("date") or "") < cutoff:
            break
        default_commits.append({
            "sha": c["hash"], "url": ((c.get("links") or {}).get("html") or {}).get("href"),
            "date": c.get("date"),
            "author_login": ((c.get("author") or {}).get("user") or {}).get("nickname")
            or (c.get("author") or {}).get("raw"),
            "has_pull": c["hash"] in from_prs,
        })
    cache: dict[str, bool] = {}
    deployments = [dict(d, on_default=_on_default(bb, repo, branch, d["sha"], cache))
                   for d in _deployments(bb, repo, cutoff, environments) if d.get("sha")]
    return {"repo": repo, "protection": protection, "pulls": pulls,
            "default_commits": default_commits, "deployments": deployments}


def main(argv: list[str] | None = None) -> int:
    import requests

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", action="append", required=True, help="workspace/slug; repeatable")
    parser.add_argument("--days", type=int, default=90, help="audit period, ending now")
    parser.add_argument("--environment", action="append", default=None,
                        help="deployment environment that is production (default: production); repeatable")
    parser.add_argument("--gate-path", action="append", default=[],
                        help="extra gate file pattern (fnmatch), added to the defaults; repeatable")
    args = parser.parse_args(argv)

    session = requests.Session()
    if token := os.environ.get("BITBUCKET_TOKEN"):
        session.headers["Authorization"] = f"Bearer {token}"
    elif os.environ.get("BITBUCKET_USERNAME"):
        session.auth = (os.environ["BITBUCKET_USERNAME"], os.environ.get("BITBUCKET_APP_PASSWORD", ""))
    bb = Bitbucket(session)
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    repos = [dict(fetch(bb, r, since, args.environment or ["production"]), extra_gate_patterns=args.gate_path)
             for r in args.repo]
    rows, left_out = exceptions(repos)
    json.dump({"attributes": summarize(repos), "exceptions": rows,
               "exceptions_left_out": left_out}, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
