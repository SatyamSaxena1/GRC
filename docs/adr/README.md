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
| [010](010-ciso-assistant-integration.md) | Push closed verdicts/gaps into CISO Assistant, don't build risk/policy/vendor here | Accepted |
| [011](011-oidc-auth.md) | OIDC auth alongside the stub identity scheme | Accepted |
| [012](012-auditor-only-ai-nutshell.md) | Auditor-only AI narration of the verdict, redacted by field not by object | Accepted |
| [013](013-organization-defined-commitments.md) | A policy's own stated cadence becomes the org's evidence requirement | Accepted |
| [014](014-live-pipeline-events.md) | Stream pipeline progress to the browser, without becoming the deferred event bus | Accepted |
| [015](015-glossary-layers.md) | Layered glossary: curated entries win, reference corpora are imported not scraped | Accepted |
| [016](016-ai-rmf-starter-pack.md) | AI RMF as a content pack: a new UCO domain, and only the subcategories evidence can settle | Accepted |
| [017](017-compliance-officer-persona.md) | The compliance officer is `ORG_ADMIN`; add only a read-only `COMPLIANCE_VIEWER` role, deferred | Accepted (deferred build) |
