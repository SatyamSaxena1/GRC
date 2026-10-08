# ADR-019: How this repo is built — agent output is testimony, checks that can fail decide, a human seals one decision at a time

> **Status:** Proposed. Phase 1 (four rules) is meant to land now; phase 2 lists the rest with
> the trigger that should bring each one in. Distilled from a structured debate about version
> control in the AI era, stress-tested and fact-checked; the debate itself is not in the repo.

## Context
ADR-004 and ADR-018 settle how the *product* treats a model: it witnesses, Python decides, a
person locks. Nothing says how the *repository* treats one — and most commits here are
co-authored by an AI agent.

A spot check of three random recent commits (2026-10-07) found the history doing its job and the
safety net not doing its:

- **ed57e9e** (RLS on onboarding approval): fixed after it failed in production. Reverting it
  today still passes CI, because CI runs on SQLite where `app/db.py::set_tenant` is a no-op.
  RLS has been unverified by CI for as long as CI has existed (README, "Known limitations").
- **6b7d543** (DPDP monitor): every scheduled run had failed unnoticed. Reverting the fix would
  bring back a *green* sync run that syncs nothing. Workflow files have no tests.
- **582aa49**: five unrelated decisions in one commit (a model-priority threshold, a test
  fixture, a frontend race fix with no frontend tests, a `.gitignore` line keeping uploaded
  evidence out of history, action bumps). None can be reverted alone.

All three commit messages were excellent, and `git log -S` traced a removed experiment in
seconds. The failures were all of one kind: **a check that could not go red**. Changing the
version control system would not have caught any of them. Git stays (see "Alternatives").

## Decision
The repository applies ADR-004's split to its own changes:

- **Testimony.** Anything an agent produces — code, tests, commit prose, PR descriptions,
  review summaries — is kept with its provenance and decides nothing by itself. Agreement among
  agents of one model family counts as one witness, not several.
- **Verdict.** Checks that have been *seen to fail* decide whether a change may merge.
- **Seal.** A named human merges one decision at a time, over the exact snapshot they read.

### Phase 1 — adopt now

**1. A check that cannot go red is decoration, and silence is never green.**
Every check that guards a property (tenant isolation, a scheduled sync, a migration) has a
canary that must fail *by name* when that property is broken, and a job that runs nothing reports
failure, not success. A flaky red is a bug in the check, not a reason to retry.
Concretely: a CI job on real Postgres, connected as the application role (superusers bypass RLS;
owners do too unless `FORCE ROW LEVEL SECURITY` is set), with a cross-tenant read that must be
denied; the DPDP sync asserts a synced-row count within an expected range and alerts on a run
that never happens.

**2. The ratchet turns one way.**
An agent may add a guard, never weaken one. Gate paths — `tests/`, `tests/conftest.py`,
`.github/workflows/`, `app/content/*.yaml` rule packs, `alembic/versions/`, `app/db.py`,
`app/authorization.py` — need a human review on every change, enforced by CODEOWNERS and branch
protection rather than by asking the agent nicely. A diff that removes an assertion, adds
`skip`/`xfail`, or changes a database URL in tests is flagged in CI. Loosening a guard is allowed;
it is a logged human decision, and cheap enough that nobody routes around it.

**3. One decision per merge.**
A PR states one decision; if its title needs "and", split it. Squash-merge. Local history before
the PR is scratch and may be rewritten freely; nothing on `main` is ever rewritten except to
remove a leaked secret (rule 6). Nothing with an unresolved conflict is merged, and when an agent
resolves a conflict a human reads the resolution (`git show --remerge-diff`).

**4. When a check turns out to have been vacuous, reopen what relied on it.**
Fixing the check is not the end: re-run it on the real substrate at HEAD, and treat the window it
was vacuous as a possible incident. For RLS that means asking production logs whether any tenant
read another tenant's rows while CI could not have noticed — for a multi-tenant evidence platform
that is a breach question, not a test-coverage one.

### Phase 2 — adopt on the named trigger

| # | Rule | Trigger |
|---|------|---------|
| 5 | **Bind agents with capabilities, not instructions.** Agent tokens get contents and PR access only — no admin, workflows, merge, signing keys, production database or deploy tools. Each agent has its own revocable identity and opens PRs as the person who prompted it, so no-self-approval applies. | Before any agent runs unattended (scheduled or background) |
| 6 | **Don't record what you can't forget.** Prompts stay out of the repo; commit messages are secret- and PII-scanned like code; uploaded evidence can never be staged (CI fails if a file under an evidence storage path is committed). On a leak: rotate first, scrub history second, with a one-page runbook. | Now for scanning; runbook before the first real customer |
| 7 | **A vouch names checkable claims.** The PR template has a Claims field ("tenant isolation unchanged — pinned by the Postgres canary"); a claim the diff contradicts (e.g. it touches RLS) is rejected automatically. Stale approvals are dismissed on new pushes. Model attribution trailers are stamped by the tooling, not typed by the agent. | When a second human reviews PRs |
| 8 | **Never grade your own homework.** On gate paths, the failing test lands before the fix, and CI shows it failing on the base by assertion (an import error does not count) and passing on the head. For a team of one, a cooling-off period is a *compensating* control and is labelled as such, not as separation of duties. | First change to a gate path after rule 2 lands |
| 9 | **Review the gate, not the flood.** Humans review gate paths; a written list of change classes (by path and diff, never by the author's say-so) may merge on checks alone. At most two open, unreviewed agent PRs per human; past that, agents may only make changes smaller. | When agent PRs outnumber human review capacity |
| 10 | **Every door to production is a change path.** Console SQL, environment-variable edits and deploy triggers bypass rules 2–4; agents get none of them, humans use logged break-glass. | When a second person has production access |
| 11 | **Grow the reviewers.** Whoever knows an area least runs its canary drills (drop the policy, revert the fix, predict the named red) after writing down what they expect — on synthetic tenants only. | When someone new joins |
| 12 | **Case law, not transcripts.** Agents take instructions only from the ADRs, the tests that pin them, and one agent-instructions file, each with an owner. Commit history, issues, PR comments, uploaded documents and other agents' output are evidence, never orders. | When the agent-instructions file is created |
| 13 | **Keep the plumbing, rent only what you can leave.** A tool layered on Git must round-trip to plain Git. Note that GitHub's reviews and approvals do not travel with a clone: export them periodically, since this product sells portable evidence of change control. | Before relying on any new VCS layer |

**Every rule here is itself slop until it earns its keep.** Each names the failure it would have
caught and an owner; a phase-2 rule not adopted within a year of its trigger, or a phase-1 rule
that has caught nothing and costs more than it saves, is removed by amending this ADR.

**Progress.** Rule 1's first concrete item has landed: the CI `rls` job runs
`tests/test_rls_postgres.py` on real Postgres as a non-superuser role, fails if the role could
bypass RLS or if the tests are skipped, and fails when the ed57e9e fix is reverted. `deploy` now
needs it. The look-back of rule 4 (production logs for the SQLite-only period) is still open.
A second vacuous check turned up the same way: the audit hash chain had only ever been verified
on SQLite. On Postgres, row-level security gave each tenant a partial view of one global chain,
so it could not verify. A canary in the `rls` job showed it failing; chains are now per tenant,
serialized, cover the timestamp, and are append-only in the database (`app/audit_log.py`).

## Alternatives considered
- **Replace Git** (Mercurial, Pijul, Fossil, an operation-log system such as Zed's DeltaDB).
  None of the three failures was a storage or history problem; each was a check that could not
  fail. Operation-level history also multiplies what must be forgotten (rule 6). Layers that keep
  Git underneath — jj locally, GitHub's stacked pull requests — are allowed under rule 13 and
  need no ADR.
- **An `Understood-By` trailer** declaring a human understood an agent's change. Rejected: the
  agent would write it. Rule 7's checkable claims and rule 11's drills test understanding instead
  of asserting it.
- **Route review by provenance** (AI-touched lines get more review). Rejected: nearly every
  commit here is AI co-authored, so the tag routes everything the same way and carries no
  information. Review is routed by *path* (rule 9).
- **Record every edit and prompt for full provenance.** Rejected for now: it collides with
  erasure duties (GDPR, DPDP) and with leaked secrets, and nobody reviews the extra volume.

## Consequences
- Phase 1 is roughly: one Postgres CI job with a canary, one assertion and alert in
  `.github/workflows/monitor.yml`, a CODEOWNERS file plus branch protection, a small CI script for
  weakened tests, a PR template, and one look-back over production logs for the SQLite-only
  period.
- Merging slows on gate paths and nowhere else.
- A review of this ADR is itself testimony: it came out of a debate among agents of one model
  family, and its consensus should be weighed as one witness. The repo findings in Context were
  checked against the code; the rest is argument, to be judged by whether the rules catch things.
