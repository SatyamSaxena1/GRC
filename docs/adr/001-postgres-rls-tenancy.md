# ADR-001: PostgreSQL + Row Level Security for tenant isolation

## Context
Three parties share one deployment: the platform operator, audit firms, and auditee
organizations. A single missed `WHERE org_id = ...` leaks another tenant's evidence —
the worst failure this product can have. Application-level scoping is necessary but is
one forgotten filter away from a breach.

## Decision
PostgreSQL with RLS `ENABLE` + `FORCE` on every tenant-owned table. Each request sets
`app.tenant_id` as a transaction-local setting (`set_config(..., true)`), and policies
compare `org_id` against it. Application-level scoping stays as well: defence in depth,
not a replacement.

## Alternatives considered
- **Database per tenant.** Strongest isolation, but migrations and connection
  management across hundreds of auditees make it operationally expensive this early.
- **Application filtering only.** What we started with. One missed filter = breach.
- **Schema per tenant.** Middle ground, still multiplies migration surface.

## Consequences
- SQLite (dev/test default) has no RLS, so tests exercise application scoping only; the
  RLS migration is a documented no-op there. Cross-tenant tests must therefore run
  against Postgres in CI to prove the database layer, not just the app layer.
- Every connection must set tenant context or policies match nothing; background jobs
  pass tenant explicitly (`app/db.py:set_tenant`).
