# ADR-006: Background jobs — BackgroundTasks now, Dramatiq when it stops fitting

## Context
Document processing (parse, extract, evaluate) takes seconds to minutes and must not
block the upload request. The spec suggested Redis + Dramatiq or Redis + Celery.

## Decision
FastAPI `BackgroundTasks` for now, behind a single dispatch point
(`app/routers/evidence.py:_process_in_background`) that opens its own session and
receives tenant context explicitly. The upload endpoint returns `202` immediately, and
`GET /evidence/{id}/status` reports the lifecycle
(UPLOADED, SCANNING, STORED, EXTRACTING, ANALYZING, EVALUATING, READY, FAILED,
NEEDS_REVIEW).

**Dramatiq** is the chosen upgrade path when needed: simpler than Celery, fewer moving
parts, good Redis story. Redis is already in `docker-compose.yml` for it.

## Alternatives considered
- **Dramatiq/Celery now.** The correct end state, but it adds a broker and a worker
  process to run, deploy and monitor before anything needs them. The job function would
  be identical either way.
- **Synchronous processing.** What we had. Blocks the HTTP request for the whole model
  call — a minute or more on a local 7B model.

## Consequences
- **Honest limitation**: in-process tasks die with the process and have no retries or
  dead-letter handling. Acceptable while a failed document can simply be re-uploaded
  and its status says FAILED; not acceptable once processing is billable or SLA-bound.
- The migration is a decorator on the existing function plus a worker entrypoint,
  because the job already takes ids (not ORM objects) and manages its own session.
