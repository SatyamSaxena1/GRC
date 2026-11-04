# ADR-046: A person may accept a smaller repository scope

Status: accepted. Builds on ADR-030 (partial runs) and ADR-045 (GitHub connection).

## Context
A run is marked PARTIAL when it covers fewer repositories than the last COMPLETE run, so a shrinking scope can
never read as a pass. Found live: a one-off demo run had covered 3 repositories, the standing setup covers 1, and
every later run stayed PARTIAL with no way out. The guard was right; the missing piece was a deliberate way for a
person to say "fewer is correct".

## Decision
- An organisation admin may accept a smaller scope with a written reason (at least 6 words).
- It only applies when every signal on the last run is "repositories in scope fell". If the collector itself reported
  a problem (incomplete, truncated, rate limited, errors) or any other signal is present, it is refused (409).
- Runs stay insert-only (ADR-030). Acceptance inserts a new COMPLETE run, expectation `ACCEPTED`, carrying the last
  run's figures and the reason. It becomes the baseline, so the next collection is judged against the smaller scope.
  The stored evidence is never edited.
- The page then collects again, so verdicts update from a fresh, complete run.
- Audit event `CONNECTOR_SCOPE_ACCEPTED` records who, why and which run was accepted.

## Consequences
- Only repository-scope reductions can be accepted this way; lost attributes or zero merges still need a clean run.
- A careless admin can narrow scope. The reason and the audit event make that visible, not impossible.
