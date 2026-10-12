# Work summary: what was built, October 2026

This covers pull requests #14 to #29: what each one added, where it lives, how it was checked,
and what still waits on a person. Everything below is merged to `main` and deployed to both
Render services, `grc` and `grc-demo`, unless it says otherwise.

## At a glance

| PR | What | ADR | Live |
|---|---|---|---|
| #14 | Verdict provenance and replay | 022 | 9 Oct |
| #15 | OSCAL 1.2.3 assessment-results export | — | 9 Oct |
| #16 | Per-tenant audit chains, append-only in the database | — | 9 Oct |
| #17 | Rules with repeated exceptions flagged as possibly miscalibrated | — | 9 Oct |
| #18 | Auditor-held signed audit checkpoints, verifiable offline | 023 | 9 Oct |
| #19 | Pre-merge change-control gate | 024 | 9 Oct |
| #20 | Fixes from review of the OSCAL export, exception pressure and checkpoints | — | 9 Oct |
| #21 | Dev-server proxy fix for `/exceptions` (another session's PR) | — | 9 Oct |
| #22 | The scheduled connector sync evaluates what it collects | — | 9 Oct |
| #23 | AI policies must commit to fairness (NIST AI RMF GOVERN 1.2) | 016 amended | 9 Oct |
| #25 | Scheduled GitHub change-control collection, scoped to named organisations | — | 9 Oct (see note) |
| #26 | Typed decisions on a dedicated Jev-class model, with a local benchmark | 025 | 9 Oct |
| #27 | Typed decisions hashed, chained, exported and monitored | 025 | 9 Oct |
| #28 | AI code review as change-control evidence, never approval | 026 | 12 Oct |
| #29 | Review Standards, policy packs, deterministic review engine; GitHub App spec; ReviewBench adapter | 027, 028 | 12 Oct |

The #25 deploy timed out on Render's side: the instance took 11 minutes to start. Its code went
live with the #26 deploy. The scheduled collection it added runs in GitHub Actions, so it was
never affected.

## What exists now

### Evidence you can trust later
- **Verdict provenance.**
  - Every computed verdict records the rule's hash, the engine version, the build and the exact
    inputs it used.
  - **Replay** re-runs the rule and shows the same verdict.
  - Code: `app/provenance.py`; UI: `VerdictProvenance.tsx`.
- **Audit chain.**
  - Each organisation's audit log is a hash chain: version 2 hashes include the chain name,
    sequence number and timestamp.
  - A Postgres trigger refuses UPDATE and DELETE on it, and the nightly monitor verifies it.
  - Code: `app/audit_log.py`.
- **Signed checkpoints.**
  - An auditor takes an Ed25519-signed checkpoint and keeps it.
  - `scripts/verify_audit_export.py` proves, offline, that nothing at or before the checkpoint
    changed.
  - Code: `app/checkpoints.py`; endpoints under `/audit/checkpoints`.
- **OSCAL export.**
  - A deterministic OSCAL 1.2.3 assessment-results file, validated against NIST's schema.
  - Gaps become risks; exceptions become requested or approved deviations.
  - Code: `app/oscal.py`; endpoint `/export/oscal/assessment-results.json`.

### Rules that stay honest
- **Exception pressure.** A rule that collects three or more exceptions is reported nightly as
  possibly miscalibrated. Code: `app/exceptions.py`, `app/monitor.py`.
- **Fairness.** NIST AI RMF GOVERN 1.2 now requires an AI policy to address fairness, in
  `app/content/nist-ai-rmf-1.0.yaml`.

### Change control
- **Pre-merge gate.**
  - The audit's own rules run on an open pull request, in the client's CI.
  - Exit codes: 0 pass, 1 would add a gap, 3 pending, 4 could not run. Warn-only mode never
    hides a broken gate (exit 4).
  - Code: `app/change_gate.py`, `.github/actions/change-control-gate`.
- **Scheduled collection.** Every six hours, GitHub Actions collects change-control evidence
  for the organisations you name (`CHANGE_CONTROL_REPOS`, `CHANGE_CONTROL_ORG_IDS`). It runs
  for Acme Corp.
- **AI code review as evidence.**
  - What Qodo, PR-Agent, CodeRabbit, Copilot, Codex and others did is recorded: reviewed or
    not, unresolved findings, linked ticket.
  - These facts are advisory: they never change a verdict, and an AI review is never the
    independent approval.
  - Facts that could not be read are reported as unknown, never as "no".
  - Code: `app/collectors/github_change_control.py`.

### AI decisions with a paper trail
- **A dedicated decision model.** The typed decisions can run on their own self-hosted
  Jev-class model, set with `LLM_DECISION_MODEL`. These are the wrong-document guard, the
  quote check and the rights-request suggestion.
  - An answer that changes with the order of the options is discarded.
  - Code: `app/ai/decision.py`, `app/ai/provider.py`.
- **Local benchmark.** `python -m evaluation.decisions` compares models on our own cases:
  accuracy, Brier score and ECE, speed, and whether answers depend on option order.
- **Decision hashes.**
  - Every decision is hashed over its question, options, state digest, model and answer.
  - The hash goes into the audit chain and the OSCAL export.
  - A nightly report shows how often suggestions turned out right, per model.

### Code governance (new)
- **Review Standards.**
  - Each organisation's code-review rules are YAML: versioned, hashed, one active version
    enforced by the database, optimistic concurrency, and audited publish and activate.
  - Four built-in policy packs: secure development, dependency controls, testing and change
    management.
  - Code: `app/review/standards.py`, `app/review/packs/`.
- **Deterministic engine.**
  - Rule kinds: forbidden patterns, code-needs-tests, banned dependencies, secrets, a size
    limit, and plain-language rules for the model later.
  - Severity, action and outcome are separate.
  - Every rule ends `pass`, `violation`, `not_evaluated` or `error`; every review ends `passed`,
    `violated`, `incomplete` or `error`.
  - Nothing it could not read counts as a pass.
  - No code is ever stored: secrets get no fingerprint at all.
  - Code: `app/review/engine.py`, `app/review/diff.py`.
- **Code review page.** Start from a pack, edit, publish, roll back, and try a pasted diff
  (nothing stored). Frontend: `CodeReview.tsx`; API under `/review`.
- **The GitHub App is specified, not built.** ADR-028 settles:
  - tenant binding through a confirmed installation and a trusted server-side lookup;
  - durable jobs run by a separate worker;
  - what each review outcome means for the check run;
  - five delivery milestones, each with a production-readiness gate.
- **ReviewBench adapter.**
  - `bench/reviewbench/` packages the reviewer as a ReviewBench agent: deterministic rules plus
    a Qwen agent with read-only repository tools. Code: `app/review/agent.py`,
    `app/review/bench.py`.
  - Checked with ReviewBench's own runner: rules mode passed 25 of 25 test PRs.
  - Offline evaluation only; nothing in production calls a model.

## How it was checked
- Every PR went through CI (backend, Postgres RLS, frontend, change-control gate) before
  merging.
- **Codex review:**
  - #15, #17 and #18 were merged before their Codex reviews arrived; those findings were fixed
    in #20.
  - Every PR since then waited for its review before merging.
  - Findings were fixed and their threads answered on #26, #27, #28 and #29 (2, 2, 2 and 5
    findings).
- At the last merge: **766 backend tests** and **15 Postgres row-level-security tests** pass,
  and the frontend builds.
- After each merge the Render deploy was checked:
  - the migration was logged;
  - "Application startup complete" appeared;
  - the health checks returned 200.

  The #29 deploy (`0210086`) went live at 07:48 UTC on 12 Oct on both services, after
  migration `e2f3a4b5c6d7 → f3a4b5c6d7e8`.

## Learned along the way
- **A Codex review can arrive after a merge.** Early on, three PRs were merged before their
  reviews landed, and the findings were fixed in #20. Since then, each merge has waited for
  the review.
- **Render can time out a healthy deploy.** With a slow instance start, a deploy shows
  `update_failed` / "Timed Out". The next deploy, or a manual redeploy, carries the code.
- **ReviewBench rules-only baseline.** The deterministic rules found 5 things across the 25 test
  PRs, all likely false positives for code review: credentials in test fixtures, a README
  example, and PEM header constants in a key parser. That is why the benchmark adapter runs the
  model agent by default.
- **Measure before trusting a benchmark.** The ReviewBench leaderboard lists only hosted
  products. Offline scores with a different judge are not comparable with it; only grounded
  metrics, with the same judge, are.

## Waiting on you
1. **Database:** upgrade `grc-db` before **22 October 2026**, when the free plan expires.
2. **Checkpoints:** set `AUDIT_CHECKPOINT_SIGNING_KEY` on both Render services. Until then,
   checkpoint endpoints answer 503.
3. **ReviewBench:** run the judge on your machine. The commands are in
   `bench/reviewbench/README.md`, and the API key goes in your own shell, never in a file.
   Send `results.json` back for tuning.
4. **Decision model:** run `python -m evaluation.decisions` against your local model, then set
   `LLM_DECISION_MODEL` if it wins.
5. **Decisions for code governance:**
   - approve ADR-028;
   - one standard per organisation, or per repository;
   - a Render background worker for the review queue, which is a second service.
6. **Optional:** set `REVIEW_FINGERPRINT_KEY` so findings carry keyed fingerprints.

## What comes next
ADR-028's milestones:
1. **Milestone 3:** the GitHub App and durable ingestion.
2. **Milestone 4:** check runs and audit evidence.
3. **Milestone 5:** dogfood on this repository and hardening, ending in the end-to-end
   demonstration. A policy is published, a PR violates it, the required check fails, the fix
   passes, and an auditor verifies both from the audit chain.

After that comes the Phase 2 model reviewer, which reaches production only once it meets the
acceptance criteria in `docs/product/code-review.md`.
