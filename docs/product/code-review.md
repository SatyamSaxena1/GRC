# Code review and governance

GRC reviews pull requests against an organisation's **Review Standard** and turns the result into
audit evidence. What sets it apart:
- every standard version is hashed;
- every review records which standard and engine version produced it, in the tamper-evident
  audit chain, so an auditor can verify it (ADR-027);
- rules map to framework clauses.

## Phases
| Milestone | What | Status |
|---|---|---|
| 1 | AI code review as change-control evidence (ADR-026) | merged |
| 2 | Review Standards, policy packs, the deterministic engine with explicit outcomes, the Code review page (ADR-027) | this change |
| 3 | GitHub App and durable ingestion: connect flow, trusted tenant lookup, webhook, job queue, worker (ADR-028) | specified, not started |
| 4 | Check runs and evidence: "GRC code review" check, annotations, superseding, review runs in the audit chain | specified |
| 5 | Dogfood on this repository and production hardening | specified |
| later | Model reviewer (`judged` rules, advisory), findings analytics, exceptions UI, PR triage | planned |

## Writing a standard
```yaml
schema_version: 1
name: Acme engineering
owner: Platform security
on_incomplete: warn            # what a review that could not read everything does to a merge
rules:
  - id: no-secrets
    title: No credentials in code
    kind: secret_scan          # aws_access_key, github_token, private_key, slack_token, password_literal
    severity: critical         # how bad
    action: block              # what policy does: block | warn | info
    clauses: ["SOC-2 CC8.1"]
  - id: no-print
    title: No print debugging in the app
    kind: forbid_added
    pattern: '^\s*print\('
    paths: ["app/*.py"]        # fnmatch; * crosses directories
    exclude: ["app/scripts/*"]
  - id: tests-with-code
    title: Code changes come with tests
    kind: require_companion    # companions default to the gate's test globs
    paths: ["app/*"]
  - id: banned-packages
    title: Banned dependencies
    kind: forbid_dependency    # requirements*.txt, pyproject.toml, package.json
    packages: [left-pad]
  - id: small-changes
    title: Keep changes reviewable
    kind: max_change           # never blocks
    max_added_lines: 800
  - id: clear-errors
    title: Errors say what to do next
    kind: judged               # checked by the model reviewer (Phase 2); never blocks
    text: An error message tells the user what went wrong and what to do about it.
```
Each rule takes an optional `severity` (low, medium, high or critical), `action` (block, warn or
info, default warn), `category` (ReviewBench's taxonomy) and `rationale`.

On the **Code review** page:
- an admin starts from a built-in pack (secure development, dependency controls, testing,
  change management), publishes a new version, or makes an older one active again;
- anyone can paste a `git diff` into **Try it**; nothing is stored.

A review ends `passed`, `violated`, `incomplete` or `error`. Nothing the engine could not read
counts as a pass.

## Phase 2 model: acceptance criteria before production
The candidate is Qwen3.8-27B, self-hosted. Coding-benchmark strength does not establish
code-review precision or recall, and fitting Q4 weights on 24 GB is not the same as serving
large-repository reviews: KV cache, context and concurrency all matter. So it ships only when:

| Metric | Criterion |
|---|---|
| Valid output | 99%+ of reviews produce schema-valid findings (an engineering target) |
| Coverage | every skipped file and truncated context is recorded |
| False positives | a representative sample is adjudicated by hand |
| Recall | measured on ReviewBench's public corpus and on held-out PRs of our own; ReviewBench numbers inform model choice, but are not assumed comparable with its leaderboard |
| Latency | p50 and p95 per PR size band |
| Cost | GPU time per completed review |
| Security | repository text cannot trigger an unauthorised tool call |
| Traceability | model, prompt and tool configuration versions are recorded per finding |

## What ReviewBench's methodology tells us to build next
GitHub's ReviewBench (`review-bench/reviewbench`, `docs/METHODOLOGY.md`) scores reviewers on 219
public PRs. On its leaderboard every product sits at roughly 85–88% precision, and **recall
(10–35%) is what separates them**. The methodology suggests:

1. **Speak its finding format** (done in 1a). One finding per logical issue with file,
   start and end line, message and producer, categories from its taxonomy. Phase 2 wraps the
   reviewer in its agent contract: a container that reads `/work/pr/diff.patch` and writes
   `findings.json`. Our self-hosted model can then be scored on the public corpus.
2. **Compare on grounded recall.** Augmented recall's denominator depends on the agent, so the
   methodology warns against ranking on it. Report grounded precision and recall, stratified by
   severity and category, as the mean of three runs with their spread, with review duration
   measured around the review only.
3. **Context is the recall lever.** Its "context required" axis, and the augmented-over-grounded
   gap on the leaderboard, say that findings needing related files are where reviewers miss.
   The Phase 2 agent reads related code through tools (`complete_with_tools` on Qwen3.8-27B)
   rather than seeing the diff alone.
4. **Prompt against the known false-positive modes.** These are incorrect claims, unverifiable
   claims, off-scope observations, duplicates, sub-threshold nits and advice that would make the
   change worse. They become the Phase 2 reviewer's instructions. Rule findings and model
   findings are deduplicated before posting.
5. **Online signal is the real target.** The methodology treats offline TP/FP as a proxy for
   whether a human acts on a finding. Phase 3 measures that directly per rule and per model:
   resolved by a code change, dismissed with a reason, or ignored. Its dispute loop is our
   dismissal-with-reason flow. A rule people keep dismissing is flagged for review, like
   exception pressure (ADR-021).
6. **Record what a re-run needs.** For every review run: standard hash, engine version, model
   and prompt version (decision hash, ADR-025), head and base commits, and the findings hash.
   1b stores these on each run and in the audit chain.
