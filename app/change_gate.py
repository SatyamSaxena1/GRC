"""Pre-merge change-control gate (ADR-024): the audit's own rules, run on one open pull request
before it merges, in the client's CI.

    GITHUB_TOKEN=... python -m app.change_gate --repo owner/name --pr 123 --framework SOC-2

It reads the pull request exactly as the period collector does (`pull_facts`), treats it as if
it merged now, and puts it through the same `summarize()` and the same content packs. It
reports the per-merge rules this change would break: no independent approval of the head
commit, failing or missing checks, an AI-assisted change approved only by its author, a
change to CI, tests or ownership with fewer than two independent approvals. A merge the gate
passes cannot later fail the audit on those rules.

Repository settings (branch protection, force pushes, admin bypass) are not judged here: the
Actions token usually cannot read them, and unknown is not a pass. They are listed as not
evaluated, and the period audit judges them.

Exit codes:
  0  this change adds no gap
  1  merging it now would add a gap
  3  other checks are still running after --wait seconds, so it cannot be judged yet
  4  the gate could not run (token, API, arguments)

--warn-only turns 1 and 3 into 0 for a rollout. It never hides 4: a gate that cannot run is
broken, and a broken gate reporting green is decoration (ADR-019 rule 1).

The platform never reads the gate's result: it is the client's own preventive control. The
audit still reads Git independently afterwards (ADR-020).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

from app.collectors import github_change_control as gcc
from app.content.load import load as load_content
from app.evaluate import evaluate

PASS, WOULD_ADD_GAP, PENDING, ERROR = 0, 1, 3, 4

# The rules one merge can break. Everything else in the snapshot is about the repository.
PER_MERGE = {
    "merges_without_independent_approval": "needs an approval of the head commit from someone who wrote none of it",
    "merges_with_failing_or_missing_checks": "needs every check on the head commit to pass (and at least one to run)",
    "ai_assisted_merges_without_independent_approval":
        "AI-assisted: needs an approval from someone other than the person who prompted the agent",
    "gate_path_merges_without_two_independent_approvals":
        "changes CI, tests or ownership: needs two independent approvals",
}
NOT_EVALUATED = ("default_branch_protected", "required_approving_reviews", "stale_reviews_dismissed",
                 "admins_can_bypass", "force_push_allowed_on_default")
_PENDING_STATES = {"queued", "in_progress", "pending", "requested", "waiting", "expected"}


def judge(pr: dict, frameworks: list[str], self_checks: set[str], extra_gate_patterns=(),
          content=None) -> dict:
    """Pure: the gate's verdict on one pull request's facts."""
    content = content or load_content()
    checks = [c for c in pr.get("checks", []) if c.get("name") not in self_checks]
    pending = sorted(c["name"] for c in checks if str(c.get("conclusion") or "").lower() in _PENDING_STATES)
    pr = {**pr, "checks": checks}
    attributes = gcc.summarize([{"protection": None, "pulls": [pr], "default_commits": [],
                                 "deployments": [], "extra_gate_patterns": list(extra_gate_patterns)}])
    findings: dict[str, dict] = {}
    for link in evaluate(attributes, "CHANGE_CONTROL_SNAPSHOT", frameworks, content):
        for gap in link.gaps:
            if gap.attribute in PER_MERGE:
                finding = findings.setdefault(gap.attribute, {"rule": gap.attribute, "fix": PER_MERGE[gap.attribute],
                                                              "clauses": []})
                finding["clauses"].append(f"{link.framework} {link.clause}")
    if "merges_without_independent_approval" in findings:
        findings["merges_without_independent_approval"]["why"] = gcc.approval_finding(pr)
    if "gate_path_merges_without_two_independent_approvals" in findings:
        findings["gate_path_merges_without_two_independent_approvals"]["why"] = \
            "gate files: " + ", ".join(gcc.gate_paths(pr, gcc.GATE_PATTERNS + tuple(extra_gate_patterns)))
    if pending:
        status = PENDING
    else:
        status = WOULD_ADD_GAP if findings else PASS
    return {"status": status, "pull_request": pr.get("number"), "head_sha": pr.get("head_sha"),
            "frameworks": frameworks, "findings": list(findings.values()), "pending_checks": pending,
            "independent_approvers": gcc.independent_approvers(pr),
            "ai_assisted": gcc.is_ai_assisted(pr), "not_evaluated": list(NOT_EVALUATED)}


_HEADLINE = {PASS: "✅ Merging this adds no change-control gap",
             WOULD_ADD_GAP: "❌ Merging this now would add a change-control gap",
             PENDING: "⏳ Other checks are still running; not judged yet",
             ERROR: "⚠️ The change-control gate could not run"}


def markdown(result: dict) -> str:
    lines = [f"### {_HEADLINE[result['status']]}", "",
             f"PR #{result['pull_request']} at `{str(result['head_sha'])[:12]}`, judged against "
             f"{', '.join(result['frameworks'])} with the audit's own rules.", ""]
    if result["findings"]:
        lines += ["| Rule | Clauses | Why | To fix |", "|---|---|---|---|"]
        for f in result["findings"]:
            lines.append(f"| `{f['rule']}` | {', '.join(f['clauses'])} | {f.get('why', '')} | {f['fix']} |")
        lines.append("")
    if result["pending_checks"]:
        lines += [f"Still running: {', '.join(result['pending_checks'])}.", ""]
    lines += [f"Independent approvers: {', '.join(result['independent_approvers']) or 'none'}"
              + (" · AI-assisted" if result["ai_assisted"] else ""), "",
              "Not evaluated here (repository settings, judged by the period audit): "
              + ", ".join(f"`{a}`" for a in result["not_evaluated"]) + "."]
    return "\n".join(lines) + "\n"


def _session(token: str | None):
    import requests

    session = requests.Session()
    session.headers.update({"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    return session


def run(args: argparse.Namespace, session=None) -> tuple[int, dict | str]:
    session = session or _session(os.environ.get("GITHUB_TOKEN"))
    deadline = time.monotonic() + args.wait
    raw = gcc._get(session, f"{gcc.API}/repos/{args.repo}/pulls/{args.pr}")
    pr = gcc.pull_facts(session, args.repo, raw)  # reviews, commits, files: read once
    while True:
        result = judge(pr, args.framework, set(args.self_check), args.gate_path)
        if result["status"] != PENDING or time.monotonic() >= deadline:
            return result["status"], result
        time.sleep(min(args.poll, max(0.0, deadline - time.monotonic())))
        # Only the head commit's checks change while waiting; re-reading the whole pull
        # request on every poll could exhaust the token's API allowance.
        pr = {**pr, "checks": gcc._checks(session, args.repo, pr["head_sha"])}


def main(argv: list[str] | None = None, session=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--pr", required=True, type=int, help="pull request number")
    parser.add_argument("--framework", action="append", default=None,
                        help="SOC-2, ISO-27001 or PCI-DSS; repeatable (default: SOC-2)")
    parser.add_argument("--self-check", action="append", default=["change-control gate"],
                        help="this gate's own check name, so it does not wait for itself; repeatable")
    parser.add_argument("--gate-path", action="append", default=[], help="extra gate file pattern; repeatable")
    parser.add_argument("--wait", type=float, default=0, help="seconds to wait for other checks to finish")
    parser.add_argument("--poll", type=float, default=15, help="seconds between polls while waiting")
    parser.add_argument("--warn-only", action="store_true",
                        help="report gaps and pending checks without failing (errors still fail)")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)
    args.framework = args.framework or ["SOC-2"]

    try:
        status, result = run(args, session)
    except Exception as exc:  # noqa: BLE001 — any failure to run is exit 4, never a pass
        status, result = ERROR, f"{type(exc).__name__}: {exc}"
    if isinstance(result, str):
        text = f"### {_HEADLINE[ERROR]}\n\n{result}\n"
        print(json.dumps({"status": ERROR, "error": result}) if args.json else text)
    else:
        text = markdown(result)
        print(json.dumps(result, indent=2) if args.json else text)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text)
    if args.warn_only and status in (WOULD_ADD_GAP, PENDING):
        print(f"::warning::change-control gate: {_HEADLINE[status]} (warn-only, not failing)", file=sys.stderr)
        return PASS
    return status


if __name__ == "__main__":
    raise SystemExit(main())
