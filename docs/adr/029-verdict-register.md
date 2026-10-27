# ADR-029: Verdict register: a locked verdict is reopened and replaced, never edited

> **Status:** Proposed. Implemented: `app/verdict_register.py`, model `VerdictRecord`, migration
> `a9b0c1d2e3f4`, endpoints in `app/routers/audit.py`, `scripts/verify_audit_export.py --register`,
> `tests/test_verdict_register.py`.

## Context
A control's verdict is the most sensitive record we hold, and until now it could be rewritten.
`_lock` overwrote `link.verdict`, and `unlock` overwrote `unlocked_at` and `unlock_reason`, so only
the latest reason survived and the original verdict, its replacement and the reasoning were never
kept together. The audit log held the before and after state, but as events, not as a record a
reviewer can read or query. That breaks our own promise: history is added to, never rewritten.

## Decision
Every verdict step is a row in `verdict_records`, immutable once written.

- **Chain.** A record has `seq` and `supersedes_id`. Unique constraints on `(link_id, seq)` and on
  `supersedes_id` make a fork impossible. The current state is the head, the row nothing supersedes.
  `link.verdict`, `auditor_verdict` and the lock columns remain as a cache of the head so existing
  screens and the CISO sync keep working. `unlocked_at` and `unlock_reason` are no longer written.
- **Two kinds.** `DECISION` (a verdict) and `REOPENED`. A replacement is `DECISION` -> `REOPENED` ->
  `DECISION`, written together by `POST /audit/links/{id}/supersede`; `POST .../unlock` writes only
  the `REOPENED`.
- **Reasons.** Reopening or replacing needs a reason code from a fixed list and free-text reasoning.
  Reasoning under 15 characters or 3 words, repeated characters, or a short list of boilerplate
  ("n/a", "see above", "test") is refused with 422. These thresholds are judgement calls, named
  constants in `verdict_register.py`. A first opinion or a lock is not a supersession and carries
  code `RECORDED` with whatever reason the auditor gave.
- **Who.** Same separation of duties as before (`_auditor_link`: the uploader cannot act), plus the
  requester of an exception on the same requirement cannot reopen or replace its verdict.
- **Replay.** Each record copies `engine_verdict`, `rule_hash`, `evaluation_hash` and
  `engine_version` from the link at the time (ADR-022). The register view flags
  `rules_changed_since_previous` when consecutive records were judged by different rules.
- **Anchoring.** `record_hash` covers every field of the record. The audit event
  `VERDICT_REGISTERED` carries that hash and the record's id; the record stores the event's
  `chain_seq` and `entry_hash`. The record is inserted once with both, never updated.
  `verify_audit_export.py --register` checks each record's hash, the supersession chain and the
  anchor against the exported audit chain.
- **Views.** `GET /audit/links/{id}/register` (human readable, per control) and
  `GET /audit/register.json` (machine readable, auditors only).

## Migration
Existing controls get a history from what the link row still holds: a `DECISION` for the verdict
and lock, and a `REOPENED` carrying the one surviving `unlock_reason`. Both are `origin=MIGRATED`,
actor "unknown (before the register)", and say so in their reasoning. The decision's time is
approximated (lock time, else the reopening, else the evaluation time) because the old columns
dropped it. Migrated records have no audit anchor; the audit log may hold the original events.

## Where SQLite and Postgres differ
On Postgres, `verdict_records` has an append-only trigger (as `audit_events` does) and row level
security. On SQLite neither exists, so immutability rests on application code and the hash chain:
a direct edit is detectable by `--register`, not prevented.

## Trade-offs
The link row keeps duplicate state (the cache), which must be kept in step with the head; every
write goes through the audit router. Two records per replacement is more rows, in return for a
chain that reads in order. Free-text checks stop lazy reasons, not dishonest ones.

## Not covered
- A UI for the register (the API and JSON export exist; the SPA has no panel yet).
- Signed checkpoints over the register itself: it is protected only through the audit chain.
- Verdicts set outside `routers/audit.py` (none known; the register does not enforce that).
- The Postgres backfill and trigger have not been run against a real Postgres in this change;
  the backfill logic is tested on SQLite.
- Evidence-version supersession (ADR-019) is separate and unchanged.
