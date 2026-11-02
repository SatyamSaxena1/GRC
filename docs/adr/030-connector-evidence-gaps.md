# ADR-030: Connector evidence gaps: "could not collect" is not "found nothing"

> **Status:** Proposed. Implemented: `app/collection.py`, model `CollectionRun`, migration
> `b0c1d2e3f4a5`, `app/routers/connectors.py::sync_connector_for_org`, the GitLab collector's error
> signal, `tests/test_collection_runs.py`.

## Context
A monitoring tool with a blind spot fails silently. A collector that returns a truncated page
list, loses access to a repository, or hits a rate limit used to produce a snapshot that looked
like any other, and its counts ("0 merges without approval") were judged as facts. A failed sync
raised a 502 and left no record, with the previous evidence still CURRENT.

## Decision
Every run of `sync_connector_for_org` (button and cron) writes a `collection_runs` row and a
`CONNECTOR_RUN` audit event, whatever it found:

- **Status.** `COMPLETE`, `PARTIAL` or `FAILED`, with `signals` in words saying why.
- **What it was judged against (`expectation`).**
  - `REPORTED`: the collector declared a `collection` block (`complete`, `truncated`, `rate_limited`,
    `errors`, `pages_fetched`/`pages_expected`, `total_returned`/`total_expected`).
  - `HISTORY`: compared with the last COMPLETE run for the same source: attributes that vanished,
    `repositories_in_scope` that fell, `merges_in_period` that dropped to zero from a non-zero count.
  - `NONE`: nothing to compare with. A first run from a collector that declares nothing is `COMPLETE`
    only in the sense that nothing indicated otherwise. The run row says so rather than guessing.
- **PARTIAL never passes.** The snapshot's attributes are withheld from evaluation (stored under
  `unverified_attributes`, `attributes` left empty), so every requirement reads as missing evidence,
  not as zero. The evidence description says why. Re-collecting is the fix.
- **FAILED is recorded, then raised.** The earlier evidence stays CURRENT, but `GET /connectors`
  returns `collection.status = FAILED` for the source, so the connector cannot read as healthy.
- **Baseline.** Only COMPLETE runs are baselines, so a partial run cannot lower the bar.

## Collectors
GitLab now reports `collection.errors` when the token cannot see deployments, which was previously
a stderr warning and a silent zero. GitHub and Bitbucket declare nothing yet; they are covered by
the history checks only.

## Trade-offs
- Withholding all attributes on any signal is blunt: a partial run loses its good values from
  evaluation (they remain in the stored snapshot). Judging per attribute needs each collector to say
  which attributes a signal affects.
- The history checks can false-alarm (a repository genuinely removed from scope, a quiet quarter).
  A false alarm costs a re-collect; a missed truncation costs a wrong pass.
- The first run of any source, and any source whose collector declares nothing, has no expectation.

## Not covered
- Collector-side signals for GitHub and Bitbucket (pages fetched, rate-limit headers, hidden paths).
- AWS, M365, Google Workspace and HRMS return flat attributes with no totals: only the history
  checks apply, and only from the second run.
- Per-attribute withholding; a UI for run history (the status endpoint and audit log carry it).
- The run row is not hash-anchored like verdict records (ADR-029); it is covered by its
  `CONNECTOR_RUN` audit event.
- Not run against a real Postgres.
