# ADR-007: Modular monolith, not microservices

## Context
The domain spans identity, tenancy, frameworks, controls, evidence, AI, gaps, tasks,
engagements and audit logging. That decomposes naturally into services — and
prematurely.

## Decision
One FastAPI application with module boundaries expressed in the package layout
(`app/ai/`, `app/routers/`, `app/authorization.py`, `app/service.py`, `app/storage.py`,
`app/documents.py`). Workers run as separate processes sharing the same domain code,
not as separate deployable services.

## Alternatives considered
- **Microservices now.** Distributed transactions across evidence to links to gaps, for
  a system with no scale pressure and one team.
- **Single-file app.** No seams at all; the extraction/evaluation split that ADR-004
  depends on would erode under the first deadline.

## Consequences
- Cross-module calls are function calls, so refactoring stays cheap while the domain
  model is still moving.
- The seam most likely to become a real service first is document processing: it has a
  different scaling profile (GPU, long-running) and its dependencies are already narrow
  (`documents.py` + `ai/` + one storage read).
- One deployment, one database, one place to enforce tenant isolation.
