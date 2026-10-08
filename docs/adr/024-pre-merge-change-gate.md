# ADR-024: A pre-merge change-control gate that runs the audit's own rules in the client's CI

> **Status:** Proposed. The CI-gate idea from the earlier Trishul attempt, fixed so that a
> broken gate can never report green.

## Context
The change-control product (ADR-020) judges merges after the fact. A client that wants to use
coding agents and still pass SOC 2 currently learns at audit time which merges broke the rules.
The useful version of that answer comes before the merge.

Trishul shipped a CI gate with a clean exit-code contract and a warn-only rollout mode. But
warn-only turned *every* non-zero exit into success, including "the gate could not run", so a
misconfigured gate went silently green: decoration (ADR-019 rule 1). Its gate also needed a
service-account token to call the platform.

## Decision
`python -m app.change_gate` (and the composite action `.github/actions/change-control-gate`)
judges one open pull request:

- **Same facts, same rules.** It reads the PR with the period collector's own `pull_facts()`,
  treats it as merged now, and puts it through the same `summarize()` and the same content
  packs. It reports the per-merge rules the change would break, and which clauses each one
  fails:
  - no independent approval of the head commit;
  - failing or missing checks;
  - an AI-assisted change approved only by its prompter;
  - a gate-path change with fewer than two independent approvals.

  A test runs the gate and the collector on the same pull requests and requires them to agree.
- **Unknown is not a pass.** Repository settings the Actions token cannot read (classic branch
  protection) are listed as not evaluated, never as passing. The period audit judges them.
- **Exit codes.**

  | Code | Meaning |
  |---|---|
  | 0 | no gap |
  | 1 | merging now would add a gap |
  | 3 | other checks still running after `--wait` |
  | 4 | the gate could not run |

  `--warn-only` turns 1 and 3 into 0 with a warning annotation. **It never hides 4.** The gate
  excludes its own check by name, so it does not wait for itself.
- **Output.** A markdown table in the GitHub step summary (or JSON), with each rule, its
  clauses, why it failed and what fixes it. No source code or diff content is printed.
- **Read-only, standalone.** It needs read access to contents, pull requests and checks, and
  installs with `--no-deps` plus pyyaml, pydantic and requests. It never calls the platform.
- **Independence.** The platform never reads the gate's result. The gate is the client's own
  preventive control; the audit still reads Git independently afterwards (ADR-020). A green gate
  is testimony, not evidence.
- This repository runs the gate on its own pull requests in warn-only mode
  (`.github/workflows/change-gate.yml`).

## Consequences
- Clients can make the gate a required check to stop a gap at the source, and roll it out
  warn-only first.
- The gate judges the head at the moment it runs. An approval dismissed afterwards, or a push
  after the gate passed, is caught by the next run (it re-runs on reviews) and by the period
  audit.
- Only GitHub for now. GitLab and Bitbucket would need their own `pull_facts`.
