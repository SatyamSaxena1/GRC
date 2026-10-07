"""Change-control facts from a client's GitHub repositories (ADR-020).

Read-only and metadata-only: branch protection, pull requests, reviews, commit
authorship and check results. Never source code, never a write. The output is the
collector contract app/routers/connectors.py expects — {"attributes": {...}} — and the
content packs decide what those facts mean for SOC 2 CC8.1, ISO 27001 A.8.32 and
PCI DSS 6.5.1.

Two halves, kept apart on purpose:

- `summarize()` is pure and deterministic: normalized dicts in, attribute counts out.
  It is where the rules about *who counts as an independent approver* live, so it is
  the part with tests.
- `fetch()` maps GitHub's REST API onto those dicts. It is thin, and the only part that
  talks to the network.

Run it as a collector:

    GITHUB_TOKEN=... python -m app.collectors.github_change_control --repo owner/name --days 90

and serve the printed JSON at the URL configured as DPDP_GITHUB_COLLECTOR_URL.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

# Attribute names, in the order a snapshot lists them. app/routers/connectors.py
# imports this tuple as the "github" source's allowlist, so the two cannot drift.
ATTRIBUTES = (
    "repositories_in_scope",
    "default_branch_protected",
    "required_approving_reviews",
    "stale_reviews_dismissed",
    "admins_can_bypass",
    "force_push_allowed_on_default",
    "merges_in_period",
    "merges_without_independent_approval",
    "merges_with_failing_or_missing_checks",
    "direct_pushes_to_default",
    "ai_assisted_merges",
    "ai_assisted_merges_without_independent_approval",
)

PASSING_CONCLUSIONS = {"success", "neutral", "skipped"}

# A commit counts as AI-assisted when a co-author trailer or the author names a known
# coding agent. A heuristic over what tools *declare*, not a detector: an undeclared AI
# edit is invisible here, which is why no rule treats "not AI-assisted" as a pass.
_AI_MARKERS = re.compile(
    r"(anthropic\.com|claude|copilot|cursor|openai\.com|codex|gemini|devin|"
    r"aider|cody|windsurf|codeium|tabnine|amazon\s*q)",
    re.IGNORECASE,
)
_CO_AUTHOR = re.compile(r"^co-authored-by:\s*(.+)$", re.IGNORECASE | re.MULTILINE)

# The account GitHub uses as committer for merges and web edits; it is never a person.
_PLATFORM_COMMITTERS = {"web-flow", "github"}


def _is_bot(user: dict | None) -> bool:
    if not user:
        return True  # an unknown actor never counts as an independent human
    login = str(user.get("login") or "")
    return bool(user.get("is_bot")) or login.endswith("[bot]")


def is_ai_assisted(pr: dict) -> bool:
    if _is_bot(pr.get("author")):
        return True
    for commit in pr.get("commits", []):
        if commit.get("author_is_bot"):
            return True
        for co_author in _CO_AUTHOR.findall(commit.get("message") or ""):
            if _AI_MARKERS.search(co_author):
                return True
    return False


def _contributors(pr: dict) -> set[str]:
    """Every human login that wrote or committed any part of the change. An approval
    from any of them is self-review, however the PR was opened — including the case
    where a person prompts an agent, the agent's bot account opens the PR, and the
    same person approves it."""
    logins = set()
    author = pr.get("author") or {}
    if not _is_bot(author):
        logins.add(author.get("login"))
    for commit in pr.get("commits", []):
        for key in ("author_login", "committer_login"):
            login = commit.get(key)
            if login and login not in _PLATFORM_COMMITTERS and not login.endswith("[bot]"):
                logins.add(login)
    logins.discard(None)
    return {login.lower() for login in logins}


def has_independent_approval(pr: dict) -> bool:
    """An approval counts only if it is a human's latest review, it approves the exact
    commit that was merged (an approval of an earlier push says nothing about what
    shipped), and the approver contributed nothing to the change."""
    contributors = _contributors(pr)
    latest: dict[str, dict] = {}
    for review in sorted(pr.get("reviews", []), key=lambda r: r.get("submitted_at") or ""):
        user = review.get("user")
        if _is_bot(user) or review.get("state") in {"COMMENTED", "PENDING"}:
            continue  # a comment neither grants nor withdraws approval
        latest[str(user["login"]).lower()] = review
    return any(
        review.get("state") == "APPROVED"
        and review.get("commit_id") == pr.get("head_sha")
        and login not in contributors
        for login, review in latest.items()
    )


def checks_passed(pr: dict) -> bool:
    """At least one check ran on the merged commit, and none of them failed. No checks
    at all is not a pass: a gate that never ran cannot have stopped anything."""
    checks = pr.get("checks", [])
    return bool(checks) and all(
        str(c.get("conclusion") or "").lower() in PASSING_CONCLUSIONS for c in checks
    )


def summarize(repos: Iterable[dict]) -> dict[str, Any]:
    """Attributes for one snapshot, across every repository in scope.

    Each repo is {"protection": {...} | None, "pulls": [pr, ...], "default_commits":
    [{"sha", "has_pull"}, ...]} where `pulls` are the PRs merged into the default branch
    during the period. Protection settings are the weakest across repos (one unprotected
    repository is enough to fail); counts are summed.
    """
    repos = list(repos)
    protections = [r.get("protection") or {} for r in repos]
    pulls = [pr for r in repos for pr in r.get("pulls", [])]
    ai_pulls = [pr for pr in pulls if is_ai_assisted(pr)]
    return {
        "repositories_in_scope": len(repos),
        "default_branch_protected": bool(repos) and all(p.get("enabled") for p in protections),
        "required_approving_reviews": min(
            (int(p.get("required_approving_reviews") or 0) for p in protections), default=0),
        "stale_reviews_dismissed": bool(repos) and all(
            p.get("dismiss_stale_reviews") for p in protections),
        "admins_can_bypass": any(not p.get("enforce_admins") for p in protections),
        "force_push_allowed_on_default": any(
            p.get("allow_force_pushes") or not p.get("enabled") for p in protections),
        "merges_in_period": len(pulls),
        "merges_without_independent_approval": sum(
            not has_independent_approval(pr) for pr in pulls),
        "merges_with_failing_or_missing_checks": sum(not checks_passed(pr) for pr in pulls),
        "direct_pushes_to_default": sum(
            not c.get("has_pull") for r in repos for c in r.get("default_commits", [])),
        "ai_assisted_merges": len(ai_pulls),
        "ai_assisted_merges_without_independent_approval": sum(
            not has_independent_approval(pr) for pr in ai_pulls),
    }


# --- GitHub REST -> the dicts above -------------------------------------------------

API = "https://api.github.com"


def _get(session, url: str, **params) -> Any:
    response = session.get(url, params=params or None, timeout=30)
    response.raise_for_status()
    return response.json()


def _paged(session, url: str, **params) -> Iterable[dict]:
    params.setdefault("per_page", 100)
    while url:
        response = session.get(url, params=params, timeout=30)
        response.raise_for_status()
        yield from response.json()
        url, params = response.links.get("next", {}).get("url"), {}


def _user(raw: dict | None) -> dict | None:
    if not raw:
        return None
    return {"login": raw.get("login"), "is_bot": raw.get("type") == "Bot"}


def _protection(session, repo: str, branch: str) -> dict:
    response = session.get(f"{API}/repos/{repo}/branches/{branch}/protection", timeout=30)
    if response.status_code == 404:
        return {"enabled": False}
    response.raise_for_status()
    raw = response.json()
    reviews = raw.get("required_pull_request_reviews") or {}
    return {
        "enabled": True,
        "required_approving_reviews": reviews.get("required_approving_review_count", 0),
        "dismiss_stale_reviews": bool(reviews.get("dismiss_stale_reviews")),
        "enforce_admins": bool((raw.get("enforce_admins") or {}).get("enabled")),
        "allow_force_pushes": bool((raw.get("allow_force_pushes") or {}).get("enabled")),
    }


def _checks(session, repo: str, sha: str) -> list[dict]:
    runs = _get(session, f"{API}/repos/{repo}/commits/{sha}/check-runs", per_page=100)
    checks = [{"name": r["name"], "conclusion": r.get("conclusion") or r.get("status")}
              for r in runs.get("check_runs", [])]
    status = _get(session, f"{API}/repos/{repo}/commits/{sha}/status")
    checks += [{"name": s["context"], "conclusion": s["state"]} for s in status.get("statuses", [])]
    return checks


def fetch(session, repo: str, since: datetime) -> dict:
    """One repository, as summarize() expects it. Reads only."""
    branch = _get(session, f"{API}/repos/{repo}")["default_branch"]
    cutoff = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # GitHub's format
    pulls = []
    for raw in _paged(session, f"{API}/repos/{repo}/pulls", state="closed", base=branch,
                      sort="updated", direction="desc"):
        if raw["updated_at"] < cutoff:
            break  # sorted by update time: nothing older can have merged in the period
        if not raw.get("merged_at") or raw["merged_at"] < cutoff:
            continue
        number, head = raw["number"], raw["head"]["sha"]
        pulls.append({
            "number": number,
            "author": _user(raw.get("user")),
            "head_sha": head,
            "reviews": [
                {"user": _user(r.get("user")), "state": r.get("state"),
                 "commit_id": r.get("commit_id"), "submitted_at": r.get("submitted_at")}
                for r in _paged(session, f"{API}/repos/{repo}/pulls/{number}/reviews")
            ],
            "commits": [
                {"sha": c["sha"], "message": c["commit"]["message"],
                 "author_login": (c.get("author") or {}).get("login"),
                 "committer_login": (c.get("committer") or {}).get("login"),
                 "author_is_bot": (c.get("author") or {}).get("type") == "Bot"}
                for c in _paged(session, f"{API}/repos/{repo}/pulls/{number}/commits")
            ],
            "checks": _checks(session, repo, head),
        })
    default_commits = [
        {"sha": c["sha"],
         "has_pull": bool(_get(session, f"{API}/repos/{repo}/commits/{c['sha']}/pulls"))}
        for c in _paged(session, f"{API}/repos/{repo}/commits", sha=branch,
                        since=cutoff)
    ]
    return {"protection": _protection(session, repo, branch), "pulls": pulls,
            "default_commits": default_commits}


def main(argv: list[str] | None = None) -> int:
    import requests

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", action="append", required=True, help="owner/name; repeatable")
    parser.add_argument("--days", type=int, default=90, help="audit period, ending now")
    args = parser.parse_args(argv)

    session = requests.Session()
    session.headers.update({"Accept": "application/vnd.github+json",
                            "X-GitHub-Api-Version": "2022-11-28"})
    if token := os.environ.get("GITHUB_TOKEN"):
        session.headers["Authorization"] = f"Bearer {token}"
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    attributes = summarize(fetch(session, repo, since) for repo in args.repo)
    json.dump({"attributes": attributes}, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
