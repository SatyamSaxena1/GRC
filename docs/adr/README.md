# Architecture Decision Records

| ADR | Decision | Status |
|-----|----------|--------|
| [001](001-postgres-rls-tenancy.md) | PostgreSQL + RLS for tenant isolation | Accepted |
| [002](002-pgvector-before-vector-db.md) | pgvector before any external vector DB | Accepted (deferred build) |
| [003](003-s3-compatible-storage.md) | S3-compatible evidence storage behind an interface | Accepted |
| [004](004-deterministic-rules-before-llm.md) | Deterministic rules decide compliance; the LLM only extracts facts | Accepted |
| [005](005-ollama-model-gateway.md) | Local Ollama behind a ModelGateway interface | Accepted |
| [006](006-async-job-framework.md) | Background jobs: FastAPI BackgroundTasks now, Dramatiq when it stops fitting | Accepted |
| [007](007-modular-monolith.md) | Modular monolith, not microservices | Accepted |
| [008](008-native-extraction-before-vlm.md) | Native text extraction before any VLM call | Accepted |
| [009](009-domain-events-deferred.md) | Domain events / outbox deferred until a consumer exists | Accepted (deferred build) |
