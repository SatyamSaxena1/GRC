"""ReviewBench adapter (review-bench/ReviewBench, AGENT_CONTRACT.md): review one pull request
and write its findings file. Offline evaluation of the Phase 2 reviewer; nothing here touches
GRC's database or any tenant.

    RB_MODEL_BASE_URL=http://host.docker.internal:1234/v1  (LM Studio on the host)
    RB_CONFIG_MODEL=qwen/qwen3.8-27b                         (the model id LM Studio shows)
    RB_CONFIG_MODE=agent | rules | both                      (default agent)

Two producers, counted separately in the log so their contributions can be measured:
  grc-rules   the deterministic engine with the secure-development pack (high precision)
  grc-agent   the model reviewer with read-only repository tools (recall)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from app.review import agent, diff, engine, standards

PER_PR_SECONDS = 13 * 60   # the benchmark's limit is 15 minutes per pull request
# RB_CONFIG_PER_PR_SECONDS lifts it for an offline quality run; a portal run must keep the default.


def _rule_findings(files: list[diff.FileDiff]) -> list[dict]:
    pack = next(p for p in standards.packs() if p["id"] == "secure-development")
    result = engine.review(standards.parse(pack["yaml"]), files)
    return [{"file": f.path, "start_line": f.line, "end_line": f.end_line or f.line, "message": f.message,
             "producer": "grc-rules"} for f in result.findings if f.line and f.kind != "rule_error"]


def main() -> int:
    env = os.environ
    missing = [n for n in ("RB_NWO", "RB_PR_NUMBER", "RB_BASE", "RB_HEAD", "RB_OUT") if not env.get(n)]
    if missing:
        print(f"bench: missing {', '.join(missing)}", file=sys.stderr)
        return 2
    started = time.monotonic()
    diff_text = Path(env.get("RB_DIFF", "/work/pr/diff.patch")).read_text(encoding="utf-8", errors="replace")
    try:
        pr = json.loads(Path(env.get("RB_PR_JSON", "/work/pr/pr.json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pr = {}
    files = diff.parse(diff_text)
    # Agent alone by default: on the 25-PR test set the rules' only hits were credentials in test
    # fixtures, README examples and PEM header constants. Real policy hits, but not review
    # findings ReviewBench counts. Run `rules` or `both` as an ablation.
    mode = env.get("RB_CONFIG_MODE", "agent")
    findings = _rule_findings(files) if mode in ("rules", "both") else []
    if mode in ("agent", "both"):
        model = agent.from_env()
        print(f"model={model.model} base_url={model.base_url} mode={mode} prompt={agent.PROMPT_VERSION}",
              file=sys.stderr)
        reviewed, stats = agent.review(model, agent.RepoTools(env.get("RB_REPO", "/work/repo")), diff_text, files,
                                       pr.get("title", ""), pr.get("body", ""), deadline=started + float(env.get("RB_CONFIG_PER_PR_SECONDS") or PER_PR_SECONDS))
        print(f"chunks={stats.chunks} calls={stats.calls} tool_calls={stats.tool_calls} "
              f"kept={len(reviewed)} dropped={len(stats.dropped)}", file=sys.stderr)
        taken = {(f["file"], f["start_line"]) for f in findings}
        findings += [{"file": f.file, "start_line": f.start_line, "end_line": f.end_line, "message": f.message,
                      "producer": "grc-agent"} for f in reviewed if (f.file, f.start_line) not in taken]
    # The contract wants `producer` to be the registered agent name; the split between the two
    # producers goes to the log, where an ablation can read it.
    agent_name = env.get("RB_AGENT", "grc-reviewer")
    split = {p: sum(f["producer"] == p for f in findings) for p in ("grc-rules", "grc-agent")}
    out = {"pr": {"repo": f"https://github.com/{env['RB_NWO']}", "pr_number": int(env["RB_PR_NUMBER"]),
                  "base": env["RB_BASE"], "head": env["RB_HEAD"]},
           "agent": agent_name,
           "findings": [{**f, "producer": agent_name} for f in findings]}
    Path(env["RB_OUT"]).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"findings={len(findings)} rules={split['grc-rules']} agent={split['grc-agent']} "
          f"seconds={time.monotonic() - started:.0f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
