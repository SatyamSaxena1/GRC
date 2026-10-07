"""Change-control facts from a client's GitHub repositories (ADR-020).

Read-only and metadata-only: branch protection, pull requests, reviews, commit
authorship and check results. Never source code, never a write. The output is the
collector contract app/routers/connectors.py expects — {"attributes": {...}}, plus the
per-merge "exceptions" rows behind the counts — and the content packs decide what those facts mean for SOC 2 CC8.1, ISO 27001 A.8.32 and
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
import fnmatch
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

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
    "gate_path_merges",
    "gate_path_merges_without_two_independent_approvals",
    "gate_files_removed",
    "production_deployments",
    "deployments_not_from_default_branch",
    "deployments_of_unreviewed_changes",
    "gate_checks_observed",
    "gate_checks_never_seen_failing",
)

PASSING_CONCLUSIONS = {"success", "neutral", "skipped"}
# What counts as the gate going red. Cancelled or skipped runs prove nothing either way.
FAILING_CONCLUSIONS = {"failure", "timed_out", "error"}

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


def _review_outcome(pr: dict) -> tuple[list[str], list[str]]:
    """(independent approvers, why each other review did not count).

    An approval counts only if it is a human's latest review, it approves the exact
    commit that was merged (an approval of an earlier push says nothing about what
    shipped), and the approver contributed nothing to the change."""
    contributors = _contributors(pr)
    latest: dict[str, dict] = {}
    bot_approvers = set()
    for review in sorted(pr.get("reviews", []), key=lambda r: r.get("submitted_at") or ""):
        user = review.get("user")
        if _is_bot(user):
            if review.get("state") == "APPROVED":
                bot_approvers.add(str((user or {}).get("login") or "unknown"))
            continue
        if review.get("state") in {"COMMENTED", "PENDING"}:
            continue  # a comment neither grants nor withdraws approval
        latest[str(user["login"]).lower()] = review

    approvers, reasons = [], []
    for login, review in sorted(latest.items()):
        if review.get("state") != "APPROVED":
            reasons.append(f"{login}'s latest review was {str(review.get('state')).lower().replace('_', ' ')}")
        elif review.get("commit_id") != pr.get("head_sha"):
            reasons.append(f"{login} approved an earlier push, not the merged commit")
        elif login in contributors or (review.get("user") or {}).get("contributed"):
            reasons.append(f"{login} approved but wrote or committed part of the change")
        else:
            approvers.append(login)
    reasons += [f"{login} is a bot; bot approvals do not count" for login in sorted(bot_approvers)]
    return approvers, reasons


def independent_approvers(pr: dict) -> list[str]:
    return _review_outcome(pr)[0]


def approval_finding(pr: dict) -> str | None:
    """None when the change has an independent approval, else why it does not — in
    words an auditor can check against the PR itself."""
    approvers, reasons = _review_outcome(pr)
    return None if approvers else ("; ".join(reasons) or "no approving review")


def has_independent_approval(pr: dict) -> bool:
    return approval_finding(pr) is None


def checks_passed(pr: dict) -> bool:
    """At least one check ran on the merged commit, and none of them failed. No checks
    at all is not a pass: a gate that never ran cannot have stopped anything."""
    checks = pr.get("checks", [])
    return bool(checks) and all(
        str(c.get("conclusion") or "").lower() in PASSING_CONCLUSIONS for c in checks
    )


# Files that change the gate itself: CI definitions, tests, ownership and hook config. A
# change here can weaken every later check, so it needs more than one reviewer (ADR-019
# rule 2, applied to clients). fnmatch's "*" also matches "/", so "tests/*" covers subfolders.
GATE_PATTERNS = (
    ".github/workflows/*", ".github/actions/*", "CODEOWNERS", ".github/CODEOWNERS",
    "docs/CODEOWNERS", ".gitlab-ci.yml", ".gitlab/*", "bitbucket-pipelines.yml", ".circleci/*",
    "azure-pipelines.yml", "Jenkinsfile",
    ".pre-commit-config.yaml", "tests/*", "test/*", "*/tests/*", "*/test/*", "*conftest.py",
    "test_*.py", "*/test_*.py", "*_test.*", "*.test.*", "*.spec.*",
)
GATE_PATH_MIN_APPROVALS = 2


def gate_paths(pr: dict, patterns: Iterable[str] = GATE_PATTERNS) -> list[str]:
    """The gate files a PR changed, renamed away or removed — file names only, from the
    PR's file list (never its diff)."""
    patterns = tuple(patterns)
    hits = set()
    for f in pr.get("files", []):
        for name in (f.get("filename"), f.get("previous_filename")):
            if name and any(fnmatch.fnmatchcase(name, p) for p in patterns):
                hits.add(name)
    return sorted(hits)


def removed_gate_files(pr: dict, patterns: Iterable[str] = GATE_PATTERNS) -> list[str]:
    patterns = tuple(patterns)
    return sorted(f["filename"] for f in pr.get("files", [])
                  if f.get("status") == "removed" and f.get("filename")
                  and any(fnmatch.fnmatchcase(f["filename"], p) for p in patterns))


def gate_path_under_reviewed(pr: dict, patterns: Iterable[str] = GATE_PATTERNS) -> bool:
    return bool(gate_paths(pr, patterns)) and len(independent_approvers(pr)) < GATE_PATH_MIN_APPROVALS


def gate_liveness(repo: dict) -> list[dict]:
    """[{"check", "runs", "failures"}] for each gate check of one repository.

    The gate is the branch's required checks when protection names any, else every check
    that ran on a merged commit. Runs are counted over every commit of every PR merged in
    the period, not just the merged heads: the merged head is green by construction, so a
    gate is only ever seen failing on the pushes before it. A check with no failure at all
    is not proven broken — a careful team can stay green — but it is not proven able to
    fail either, which is what an auditor relying on it needs (ADR-019 rule 1)."""
    pulls = repo.get("pulls", [])
    required = (repo.get("protection") or {}).get("required_checks") or []
    gate = set(required) or {c.get("name") for pr in pulls for c in pr.get("checks", [])}
    runs: dict[str, int] = dict.fromkeys(gate, 0)
    failures: dict[str, int] = dict.fromkeys(gate, 0)
    for pr in pulls:
        for check in pr.get("commit_checks") or pr.get("checks", []):
            name = check.get("name")
            if name in runs:
                runs[name] += 1
                failures[name] += str(check.get("conclusion") or "").lower() in FAILING_CONCLUSIONS
    return [{"check": name, "runs": runs[name], "failures": failures[name]}
            for name in sorted(gate, key=str) if name is not None]


def deployment_finding(deployment: dict, repo: dict) -> tuple[str, str] | None:
    """(rule, why) when a production deployment shipped something that did not come
    through review, else None.

    Reconciles what ran against what was approved: a deployment of a commit that is not
    in the default branch's history either skipped the gate (deployed from another branch)
    or was erased from the record afterwards (a force push) — the snapshot cannot tell
    which, and both are findings; one of a direct push, or of a PR
    merged without an independent approval, shipped an unreviewed change. A commit from
    before the period, which this snapshot cannot judge, is not flagged."""
    sha = deployment.get("sha")
    if not deployment.get("on_default"):
        return ("DEPLOY_NOT_FROM_DEFAULT",
                "deployed a commit that is not in the default branch's history: shipped from another "
                "branch, or removed from the default branch afterwards by a force push")
    if sha in {c.get("sha") for c in repo.get("default_commits", []) if not c.get("has_pull")}:
        return ("DEPLOY_OF_UNREVIEWED_CHANGE", "deployed a direct push to the default branch")
    for pr in repo.get("pulls", []):
        if sha in (pr.get("merge_commit_sha"), pr.get("head_sha")) and not has_independent_approval(pr):
            return ("DEPLOY_OF_UNREVIEWED_CHANGE",
                    f"deployed #{pr.get('number')}, merged without an independent approval")
    return None


def _patterns(repo: dict) -> tuple[str, ...]:
    """The repo's gate patterns: the defaults plus any the client added (--gate-path)."""
    return GATE_PATTERNS + tuple(repo.get("extra_gate_patterns") or ())


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
    gates = [g for r in repos for g in gate_liveness(r) if g["runs"]]
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
        "production_deployments": sum(len(r.get("deployments", [])) for r in repos),
        "deployments_not_from_default_branch": sum(
            (deployment_finding(d, r) or ("",))[0] == "DEPLOY_NOT_FROM_DEFAULT"
            for r in repos for d in r.get("deployments", [])),
        "deployments_of_unreviewed_changes": sum(
            (deployment_finding(d, r) or ("",))[0] == "DEPLOY_OF_UNREVIEWED_CHANGE"
            for r in repos for d in r.get("deployments", [])),
        "gate_path_merges": sum(bool(gate_paths(pr, _patterns(r))) for r in repos for pr in r.get("pulls", [])),
        "gate_path_merges_without_two_independent_approvals": sum(
            gate_path_under_reviewed(pr, _patterns(r)) for r in repos for pr in r.get("pulls", [])),
        # Advisory, like the two below: listed for the auditor, never a failed condition.
        "gate_files_removed": sum(
            len(removed_gate_files(pr, _patterns(r))) for r in repos for pr in r.get("pulls", [])),
        # Advisory: no content pack fails a clause on these (ADR-020). They are listed as
        # GATE_CHECK rows for the auditor to ask for a canary.
        "gate_checks_observed": len(gates),
        "gate_checks_never_seen_failing": sum(not g["failures"] for g in gates),
    }


# Per-merge detail for the auditor. Capped so one noisy repository cannot push the
# snapshot past the connector's size limit; the counts above are never capped.
MAX_EXCEPTIONS = 500


def exceptions(repos: Iterable[dict], limit: int = MAX_EXCEPTIONS) -> tuple[list[dict], int]:
    """(exceptions, how many were left out) — one row per merge or push that fails a
    rule, naming every rule it fails. The same functions decide the counts, so a row
    exists exactly when that merge was counted.

    Rows carry identifiers, links and logins, never titles or diffs: the auditor opens
    the PR on GitHub for the content (ADR-020, data minimisation)."""
    repos = list(repos)
    rows = []
    for repo in repos:
        name = repo.get("repo")
        for pr in repo.get("pulls", []):
            reasons = []
            if (finding := approval_finding(pr)) is not None:
                reasons.append({"rule": "NO_INDEPENDENT_APPROVAL", "detail": finding})
            if gate_path_under_reviewed(pr, _patterns(repo)):
                touched = gate_paths(pr, _patterns(repo))
                shown = ", ".join(touched[:3]) + (f" (+{len(touched) - 3} more)" if len(touched) > 3 else "")
                n = len(independent_approvers(pr))
                reasons.append({"rule": "GATE_PATH_UNDER_REVIEWED",
                                "detail": f"changed {shown}; {n} independent approval{'s' if n != 1 else ''}, "
                                          f"{GATE_PATH_MIN_APPROVALS} required for gate files"})
            if removed := removed_gate_files(pr, _patterns(repo)):
                reasons.append({"rule": "GATE_FILE_REMOVED",
                                "detail": "removed " + ", ".join(removed[:3])
                                          + (f" (+{len(removed) - 3} more)" if len(removed) > 3 else "")
                                          + "; check nothing it guarded went unguarded"})
            if not checks_passed(pr):
                failing = [c.get("name") for c in pr.get("checks", [])
                           if str(c.get("conclusion") or "").lower() not in PASSING_CONCLUSIONS]
                reasons.append({"rule": "CHECKS_FAILED_OR_MISSING",
                                "detail": ("failed: " + ", ".join(map(str, failing))) if failing
                                else "no checks ran on the merged commit"})
            if reasons:
                rows.append({
                    "kind": "PULL_REQUEST", "repo": name, "ref": f"#{pr.get('number')}",
                    "url": pr.get("url"), "at": pr.get("merged_at"),
                    "author": (pr.get("author") or {}).get("login"),
                    "ai_assisted": is_ai_assisted(pr), "reasons": reasons,
                })
        for commit in repo.get("default_commits", []):
            if not commit.get("has_pull"):
                rows.append({
                    "kind": "DIRECT_PUSH", "repo": name, "ref": str(commit.get("sha", ""))[:12],
                    "url": commit.get("url"), "at": commit.get("date"),
                    "author": commit.get("author_login"), "ai_assisted": None,
                    "reasons": [{"rule": "DIRECT_PUSH",
                                 "detail": "committed to the default branch without a pull request"}],
                })
        for d in repo.get("deployments", []):
            if finding := deployment_finding(d, repo):
                rows.append({
                    "kind": "DEPLOYMENT", "repo": name, "ref": str(d.get("sha", ""))[:12],
                    "url": d.get("url"), "at": d.get("at"), "author": d.get("by"),
                    "ai_assisted": None,
                    "reasons": [{"rule": finding[0],
                                 "detail": f"{finding[1]} ({d.get('environment')})"}],
                })
    rows.sort(key=lambda r: r.get("at") or "", reverse=True)
    # Gate rows are few and undated; they go last, but never fall off the cap.
    gate_rows = [
        {"kind": "GATE_CHECK", "repo": repo.get("repo"), "ref": g["check"], "url": None,
         "at": None, "author": None, "ai_assisted": None,
         "reasons": [{"rule": "GATE_NEVER_FAILED",
                      "detail": f"ran {g['runs']} time{'s' if g['runs'] != 1 else ''} in the period "
                                "and never failed; ask for a canary run that shows it can"}]}
        for repo in repos for g in gate_liveness(repo) if g["runs"] and not g["failures"]
    ][:limit]
    kept = rows[:max(0, limit - len(gate_rows))]
    return kept + gate_rows, len(rows) - len(kept)


# --- GitHub REST -> the dicts above -------------------------------------------------

API = "https://api.github.com"
MAX_COMMITS_CHECKED = 30


def _get(session, url: str, **params) -> Any:
    response = session.get(url, params=params or None, timeout=30)
    response.raise_for_status()
    return response.json()


def _paged(session, url: str, _key: str | None = None, **params) -> Iterable[dict]:
    """Every item across pages. `_key` names the list inside an envelope object, for the
    endpoints (Actions runs) that return {"total_count", "<key>": [...]}."""
    params = {**params, "per_page": params.get("per_page", 100), "page": 1}
    while True:
        response = session.get(url, params=params, timeout=30)
        response.raise_for_status()
        body = response.json()
        yield from (body.get(_key, []) if _key else body)
        # Follow only the page number: GitHub's next links use /repositories/<id>/ paths,
        # which some proxies refuse, while the /repos/<owner>/<name> URL always works.
        next_url = getattr(response, "links", {}).get("next", {}).get("url")
        page = parse_qs(urlparse(next_url).query).get("page", [None])[0] if next_url else None
        if not page:
            return
        params = {**params, "page": int(page)}


def _user(raw: dict | None) -> dict | None:
    if not raw:
        return None
    return {"login": raw.get("login"), "is_bot": raw.get("type") == "Bot"}


def _classic_protection(session, repo: str, branch: str) -> dict:
    """Classic branch protection. GitHub answers 404 both for "none" and for a token
    without administration read, so a 404 reads as unprotected: a possible false gap,
    never a false pass (ADR-020)."""
    response = session.get(f"{API}/repos/{repo}/branches/{branch}/protection", timeout=30)
    if response.status_code == 404:
        return {"enabled": False}
    response.raise_for_status()
    raw = response.json()
    reviews = raw.get("required_pull_request_reviews") or {}
    checks = raw.get("required_status_checks") or {}
    return {
        "enabled": True,
        "required_approving_reviews": reviews.get("required_approving_review_count", 0),
        "dismiss_stale_reviews": bool(reviews.get("dismiss_stale_reviews")),
        "enforce_admins": bool((raw.get("enforce_admins") or {}).get("enabled")),
        "allow_force_pushes": bool((raw.get("allow_force_pushes") or {}).get("enabled")),
        "required_checks": sorted(
            {c.get("context") for c in checks.get("checks", [])}
            | set(checks.get("contexts", [])) - {None}),
    }


def _rulesets(session, repo: str, branch: str) -> list[dict]:
    """Active rulesets that apply to the branch, repository- and organisation-level,
    as [{"id", "name", "rules": {type: parameters}, "bypass_actors": list | None}].

    The rules endpoint needs only read access. Bypass actors live on the ruleset itself
    and GitHub shows them only to callers who can edit it; when they are hidden,
    `bypass_actors` is None and the ruleset is treated as bypassable."""
    rulesets: dict[int, dict] = {}
    for rule in _paged(session, f"{API}/repos/{repo}/rules/branches/{branch}"):
        ruleset_id = rule.get("ruleset_id")
        entry = rulesets.setdefault(ruleset_id, {"id": ruleset_id, "name": None, "rules": {},
                                                 "bypass_actors": None})
        entry["rules"][rule.get("type")] = rule.get("parameters") or {}
    for ruleset_id, entry in rulesets.items():
        response = session.get(f"{API}/repos/{repo}/rulesets/{ruleset_id}",
                               params={"includes_parents": "true"}, timeout=30)
        if response.status_code in (403, 404):
            continue  # not visible to this token: bypass stays unknown
        response.raise_for_status()
        raw = response.json()
        entry["name"] = raw.get("name")
        if "bypass_actors" in raw:
            entry["bypass_actors"] = raw.get("bypass_actors") or []
    return list(rulesets.values())


def effective_protection(classic: dict, rulesets: list[dict]) -> dict:
    """What actually guards the branch: classic protection and every active ruleset,
    combined the way GitHub enforces them — all layers apply at once, so the strictest
    setting wins, and a person can bypass the gate only if every layer that binds the
    change lets them through.

    Same shape as `_classic_protection`, plus `sources` naming the layers, so
    summarize() needs no knowledge of where a setting came from."""
    classic = classic or {}
    layers = [r for r in rulesets if r.get("rules")]
    pull_rules = [r["rules"]["pull_request"] for r in layers if "pull_request" in r["rules"]]
    check_rules = [r["rules"]["required_status_checks"] for r in layers
                   if "required_status_checks" in r["rules"]]
    blocks_force_push = any("non_fast_forward" in r["rules"] for r in layers)
    enabled = bool(classic.get("enabled")) or bool(layers)

    # A layer binds administrators when it requires review and nobody may skip it: classic
    # protection with "include administrators", or a ruleset known to have no bypass list.
    binds_admins = (bool(classic.get("enabled")) and bool(classic.get("enforce_admins"))) or any(
        "pull_request" in r["rules"] and r.get("bypass_actors") == [] for r in layers)

    classic_allows_force = bool(classic.get("allow_force_pushes")) or not classic.get("enabled")
    return {
        "enabled": enabled,
        "required_approving_reviews": max(
            [int(classic.get("required_approving_reviews") or 0) if classic.get("enabled") else 0]
            + [int(p.get("required_approving_review_count") or 0) for p in pull_rules]),
        "dismiss_stale_reviews": (bool(classic.get("enabled")) and bool(classic.get("dismiss_stale_reviews")))
        or any(p.get("dismiss_stale_reviews_on_push") for p in pull_rules),
        "enforce_admins": binds_admins,
        "allow_force_pushes": classic_allows_force and not blocks_force_push,
        "required_checks": sorted(
            set(classic.get("required_checks") or [])
            | {c.get("context") for p in check_rules for c in p.get("required_status_checks", [])}
            - {None}),
        "sources": (["classic"] if classic.get("enabled") else [])
        + [f"ruleset:{r.get('name') or r.get('id')}" for r in layers],
    }


def _checks(session, repo: str, sha: str) -> list[dict]:
    # Both endpoints page at 100; reading only the first page could miss a failed run and
    # record the merge as clean.
    checks = [{"name": r["name"], "conclusion": r.get("conclusion") or r.get("status")}
              for r in _paged(session, f"{API}/repos/{repo}/commits/{sha}/check-runs", "check_runs")]
    checks += [{"name": s["context"], "conclusion": s["state"]}
               for s in _paged(session, f"{API}/repos/{repo}/commits/{sha}/status", "statuses")]
    return checks


MAX_DEPLOY_RUNS = 200


def _deployments(session, repo: str, cutoff: str, environments: Iterable[str]) -> list[dict]:
    """Successful deployments recorded through GitHub's Deployments API."""
    out = []
    for env in environments:
        for d in _paged(session, f"{API}/repos/{repo}/deployments", environment=env):
            if d.get("created_at", "") < cutoff:
                break  # newest first
            statuses = _get(session, f"{API}/repos/{repo}/deployments/{d['id']}/statuses", per_page=1)
            if statuses and statuses[0].get("state") == "success":
                out.append({"sha": d.get("sha"), "at": d.get("created_at"), "environment": env,
                            "by": (d.get("creator") or {}).get("login"),
                            "url": statuses[0].get("target_url") or statuses[0].get("log_url")})
    return out


def _deploy_jobs(session, repo: str, cutoff: str, job_names: Iterable[str]) -> list[dict]:
    """Successful runs of CI jobs that deploy (e.g. one that calls a hosting deploy hook),
    for teams that never record a GitHub Deployment. Newest MAX_DEPLOY_RUNS runs only."""
    names = set(job_names)
    if not names:
        return []
    out, seen = [], 0
    for run in _paged(session, f"{API}/repos/{repo}/actions/runs", "workflow_runs",
                      created=f">={cutoff[:10]}"):
        seen += 1
        if seen > MAX_DEPLOY_RUNS:
            break
        jobs = _get(session, f"{API}/repos/{repo}/actions/runs/{run['id']}/jobs").get("jobs", [])
        for job in jobs:
            if job.get("name") in names and job.get("conclusion") == "success":
                out.append({"sha": run.get("head_sha"), "at": job.get("completed_at"),
                            "environment": f"job:{job['name']}",
                            "by": (run.get("actor") or {}).get("login"), "url": job.get("html_url")})
    return out


def _on_default(session, repo: str, branch: str, sha: str, cache: dict) -> bool:
    """Is `sha` contained in the default branch? compare(sha...branch) is "ahead" or
    "identical" exactly when the branch has the commit."""
    if sha not in cache:
        response = session.get(f"{API}/repos/{repo}/compare/{sha}...{branch}", timeout=30)
        cache[sha] = response.status_code == 200 and \
            response.json().get("status") in ("ahead", "identical")
    return cache[sha]


def fetch(session, repo: str, since: datetime, environments: Iterable[str] = ("production",),
          deploy_jobs: Iterable[str] = ()) -> dict:
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
        commits = list(_paged(session, f"{API}/repos/{repo}/pulls/{number}/commits"))
        head_checks = _checks(session, repo, head)
        pulls.append({
            "number": number,
            "url": raw.get("html_url"),
            "merged_at": raw.get("merged_at"),
            "merge_commit_sha": raw.get("merge_commit_sha"),
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
                for c in commits
            ],
            "checks": head_checks,
            "files": [
                {"filename": f.get("filename"), "status": f.get("status"),
                 "previous_filename": f.get("previous_filename")}
                for f in _paged(session, f"{API}/repos/{repo}/pulls/{number}/files")
            ],
            # Every push, for gate liveness. The newest MAX_COMMITS_CHECKED only: two calls
            # per commit, and a long-lived PR should not dominate the API budget.
            "commit_checks": head_checks + [
                check for c in commits[-MAX_COMMITS_CHECKED:] if c["sha"] != head
                for check in _checks(session, repo, c["sha"])],
        })
    default_commits = [
        {"sha": c["sha"], "url": c.get("html_url"),
         "date": ((c.get("commit") or {}).get("committer") or {}).get("date"),
         "author_login": (c.get("author") or {}).get("login"),
         "has_pull": bool(_get(session, f"{API}/repos/{repo}/commits/{c['sha']}/pulls"))}
        for c in _paged(session, f"{API}/repos/{repo}/commits", sha=branch,
                        since=cutoff)
    ]
    protection = effective_protection(_classic_protection(session, repo, branch),
                                      _rulesets(session, repo, branch))
    cache: dict[str, bool] = {}
    deployments = [
        dict(d, on_default=_on_default(session, repo, branch, d["sha"], cache))
        for d in _deployments(session, repo, cutoff, environments)
        + _deploy_jobs(session, repo, cutoff, deploy_jobs) if d.get("sha")
    ]
    return {"repo": repo, "protection": protection, "pulls": pulls, "deployments": deployments,
            "default_commits": default_commits}


def main(argv: list[str] | None = None) -> int:
    import requests

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", action="append", required=True, help="owner/name; repeatable")
    parser.add_argument("--days", type=int, default=90, help="audit period, ending now")
    parser.add_argument("--environment", action="append", default=None,
                        help="GitHub Deployments environment that is production (default: production); repeatable")
    parser.add_argument("--deploy-job", action="append", default=[],
                        help="name of a CI job whose successful run deploys to production; repeatable")
    parser.add_argument("--gate-path", action="append", default=[],
                        help="extra gate file pattern (fnmatch), added to the defaults; repeatable")
    args = parser.parse_args(argv)

    session = requests.Session()
    session.headers.update({"Accept": "application/vnd.github+json",
                            "X-GitHub-Api-Version": "2022-11-28"})
    if token := os.environ.get("GITHUB_TOKEN"):
        session.headers["Authorization"] = f"Bearer {token}"
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    repos = [dict(fetch(session, repo, since, args.environment or ["production"], args.deploy_job),
                  extra_gate_patterns=args.gate_path)
             for repo in args.repo]
    rows, left_out = exceptions(repos)
    json.dump({"attributes": summarize(repos), "exceptions": rows,
               "exceptions_left_out": left_out}, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
