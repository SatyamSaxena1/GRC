# ADR-026: AI code review is evidence, not approval

> **Status:** Proposed. Extends ADR-020 (change-control evidence) and keeps ADR-018 (the model
> may witness, doubt, suggest or narrate, never decide).

## Context
Clients increasingly run an AI code reviewer on every pull request: Qodo Merge, PR-Agent,
CodeRabbit, Copilot review or Codex. Some of these tools also check a PR against its ticket.
The collector already discarded bot reviews when deciding who approved a change, and that is
right. But it also threw away what those reviewers did. An auditor reasonably asks three
things:
- Did anything review this change?
- Were the reviewer's findings handled, or merged over?
- What authorised the work?

## Decision
- **Recognise AI reviewers by bot login.** The allowlist has the common reviewers by default,
  extended per run with `--ai-reviewer` or `CHANGE_CONTROL_AI_REVIEWERS`. Logins are compared
  without the `[bot]` suffix, which GraphQL omits.
- **Read structure, not prose.** The collector reads who opened each review thread and
  whether it is resolved (GraphQL `reviewThreads`), the issues the PR closes, and ticket keys
  in the title and branch. It never parses a vendor's comment format and never keeps comment
  text, titles or branch names, only logins, flags and keys. Text formats change, and storing
  them would break data minimisation (ADR-020).
- **Unknown is not clean.** A GraphQL failure, or more than 100 threads, reports the facts as
  unknown, never as zero findings.
- **Advisory first.** Four attributes, plus `PULL_REQUEST_ADVISORY` rows and a line in the
  pre-merge gate's summary. No content pack fails a clause on them and the gate's exit code
  is unchanged. `_review_outcome` still discards every bot, so an AI review can never be the
  independent approval.

## Consequences
- **Resolution is read at collection time, not at merge.** A thread resolved after the merge
  reads as resolved. That is acceptable for an advisory fact, and the auditor can still open
  the PR.
- **Ticket keys are a heuristic.** Look-alikes such as `SHA-256` and `CVE-…` are excluded by
  name.
- **Making these facts count is a separate decision.** Turning "unresolved AI findings = 0" or
  "a linked ticket" into failing conditions changes verdicts, so it belongs in a content-pack
  change once clients have data.
- **Benchmarking reviewers is a separate step too.** Deciding which AI reviewers deserve weight
  (for example from review-bench) fits the `evaluation/` harness, as ADR-025 did for decision
  models.
