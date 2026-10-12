# ADR-027: GRC reviews code — Review Standards, a rule engine, and what it may read and keep

> **Status:** Proposed.
> - **Supersedes:** ADR-020's "metadata only, never source code", but only for repositories
>   whose owner installs the GRC code-review App. Everywhere else ADR-020 still holds: the
>   change-control collector, and ADR-026's AI-review evidence, read metadata only.
> - **Keeps:** ADR-018 (a model may advise, never decide).

## Context
Clients want code review governed the way Qodo governs it: organisation-wide standards,
enforced rules, and evidence of how review is working. GRC already has the parts a review
product lacks:
- versioned, hashed rules (ADR-022);
- a tamper-evident audit chain (ADR-023);
- change-control evidence mapped to SOC 2, ISO 27001 and PCI DSS (ADR-020, ADR-026).

Reviewing code means reading diffs. The owner chose to review **on the platform**, through a
GitHub App (ADR-028), rather than in the client's CI.

## Decision

### Standards are data
- **Format and validation.** A Review Standard is YAML (`app/review/standards.py`, `schema_version: 1`). It is validated strictly, with line numbers:
  - unknown keys;
  - unknown framework clauses;
  - regexes that do not compile, or are longer than 500 characters;
  - more than 200 rules;
  - documents over 200 kB.
- **Versions.** Each published version is immutable and identified by the canonical hash of
  its parsed body, not its formatting. The database allows one active version per organisation
  (a partial unique index). Publishing and activating:
  - are optimistic: a stale `expected_active_version` gets a 409, never a silent overwrite;
  - are transactional;
  - are audit events in the tenant's chain.
- **Owner.** A standard names its `owner`.
- **Starting points.** Built-in policy packs (secure development, dependency controls, testing,
  change management) are where an organisation starts. It copies, edits and publishes one as
  its own. Until it publishes, a built-in default applies, and nothing in it blocks.
- **Scope.** One active standard per organisation for now. Per-repository standards are a later
  extension: a standard would gain `repositories` globs, and the run would record which applied.

### Severity, action and outcome are separate
- **Severity** (low, medium, high, critical) is how bad a finding is.
- **Action** (block, warn, info) is what policy does about it. A critical finding need not
  block. `judged` (model-checked) and `max_change` rules can never be `block`; a standard
  that tries is rejected.
- **Every rule ends in an outcome:** `pass`, `violation`, `not_evaluated` or `error`, plus how
  many in-scope files it could not read.
- **The review ends in one outcome:** `passed`, `violated`, `incomplete` or `error`.
  - `violated`: a blocking finding exists.
  - `error` or `incomplete`: a *blocking* rule failed or could not read everything.
  - An advisory rule that could not finish makes nothing incomplete.
- **Whether an incomplete or errored review stops a merge** is the standard's `on_incomplete`
  (`block` or `warn`, default `warn`). That is an availability trade-off people make
  deliberately: a mandatory check that cannot finish blocks merging if it is a required check.

### Unknown is never a pass
- **Unread files.** Files the source did not include are marked, never dropped:
  - too large (GitHub omits patches for very large diffs);
  - past the review's 200,000 added-line cap;
  - binary, a symlink, or a combined merge diff.

  A rule that needed their content reports them as skipped.
- **Budgets.** An organisation's regex runs with a per-line timeout (0.25 s) and a review-wide
  budget (10 s). Exceeding either is a rule `error`, shown at the line where it happened.
- **Parser edge cases.** CRLF, quoted and octal-escaped file names, renames and mode-only
  changes are handled and tested.

### Source-data handling
| Stage | What happens to code |
|---|---|
| Ingestion | Diffs come from GitHub per pull request over TLS, only for installed repositories (ADR-028). |
| Processing | In memory, inside the review job; never written to the database, the job queue, storage or the filesystem. |
| Findings | Rule, file, line range, severity, category, action, message. Messages are written by the engine and never quote the code. |
| Fingerprints | A keyed HMAC of the matched lines (`REVIEW_FINGERPRINT_KEY`); no fingerprint without a key, never a plain hash. **Secret findings carry no fingerprint at all**, only the detector name and location. |
| Check annotations | The same fields as findings: never the matched text, never a secret. |
| Logs, errors, telemetry | Diff text and patch bodies are never logged. Exceptions in the review job are logged by type and location only (enforced in ADR-028's job runner and tested). |
| Model inference (Phase 2) | Self-hosted only (ADR-025's gateway); no third-party inference without an organisation's explicit opt-in. |
| Retention | Nothing to retain: no code is kept. Findings and runs follow the tenant's audit retention. |
| Try-it box | A pasted diff is processed and discarded; nothing is stored or recorded. |

### Threat model
| Threat | Mitigation |
|---|---|
| A crafted regex stalls the reviewer (ReDoS) | Per-line timeout, review budget, pattern length cap; timeout is an `error`, not a pass |
| A huge or malformed diff exhausts memory | 200,000-line cap, 2,000-character line cap, payload limits; overflow is `incomplete` |
| A finding leaks a credential | Secret findings carry detector and location only; no fingerprint; tested |
| A fingerprint is reversed by guessing short lines | Keyed HMAC only; none without a key |
| One tenant reads another's standards or findings | Strict tenant RLS on every table; installation-to-tenant binding is server-side (ADR-028) |
| A forged webhook or a replayed delivery | HMAC signature, delivery-id uniqueness, idempotent jobs (ADR-028) |
| Repository content steers a model (Phase 2) | The model only advises; tools are read-only and scoped to the PR's repository; no tool can change a check's conclusion |
| An admin silently weakens a standard | Every publish and activation is an audit event with old and new versions and hashes |

### Audit verification, not guaranteed replay
Because diffs are not kept, GRC promises **audit verification**. Every recorded review names:
- the standard version and its hash;
- the engine version;
- the repository, PR, base and head commits;
- the findings hash.

All of these are in the tamper-evident chain. **Deterministic replay** means re-running the
same engine on the same commits. It is possible while those commits remain readable, but not
guaranteed: a deleted repository, rewritten history or revoked access ends it.

### Exceptions (designed now, built in Phase 3)
A code-review exception will reference:
- `(org, repo, rule_id, standard body_hash, finding fingerprint or path and line range)`;
- the approver (never the requester, as in ADR-021), the reason, an expiry and evidence links.

It is bound to the standard's hash, so editing the rule retires the exception, the same way
ADR-021 binds gap exceptions to rule hashes. Phase 1 findings already carry everything this
key needs.

## Consequences
- **What the GitHub App needs** (ADR-028): code read on the repositories an organisation
  chooses, and check-run write. Clients who will not grant code read keep everything ADR-020
  gave them.
- **Benchmark compatibility.** The finding shape follows ReviewBench's agent contract (one
  finding per logical issue, file, start and end line, message, producer) and its category
  taxonomy. A benchmark export maps `critical` to `high`, since ReviewBench has three levels.
- **Secret coverage.** The built-in secret detectors are a floor, not production coverage. A
  maintained scanner with verification is a later step, behind the same `secret_scan` kind.
