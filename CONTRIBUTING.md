# Contributing

A map of the codebase and how to make the common changes. Start with the
[README](README.md) for *what* the product does and *why* the architecture is
shaped this way — this file is *where things live* and *how to work in them*.

## Setup

```bash
python -m venv .venv && .venv/Scripts/activate      # Windows; use bin/activate on POSIX
pip install -e ".[dev]"
cp .env.example .env                                # SQLite + local storage, no infra
pytest -q                                           # should pass with nothing running
uvicorn app.main:app --reload                       # API on :8000
cd frontend && npm install && npm run dev           # SPA on :5173, proxies to :8000
```

The default `.env` runs everything on SQLite and local disk. Postgres, S3, OIDC,
Ollama, and CISO Assistant are all opt-in via env vars — the app degrades to a
documented fallback when each is absent (see `.env.example` for every switch).

## The model in one paragraph

Five parties on **two tenancy axes**: an **audit firm** (`audit_firm_id`) staffs
**auditors** onto **engagements**; an **organisation** (`org_id`, the auditee)
supplies evidence through its **org admin** and **control owners**. The LLM
extracts facts from documents with page-level provenance; `app/evaluate.py`
decides pass/fail deterministically from YAML content packs; a human auditor
records the verdict that locks a control. The model never decides compliance —
that split is what makes a verdict reproducible and injection-resistant
([ADR-004](docs/adr/004-deterministic-rules-before-llm.md)).

## Module map (`app/`)

Dependency direction is strict: **routers → service → domain logic → models/db**.
Nothing upstream imports a router; `app/ai/` and `app/content/` are leaves that
import neither.

### HTTP layer — `app/routers/`
One router per domain, all wired in `app/main.py`. A router's only jobs:
authenticate (via the `Actor` dependency), validate input, call into `service`
or a domain module, shape the response.

| Router | Owns |
|---|---|
| `admin.py` | Bootstrap: create orgs, firms, engagements, users, assignments |
| `firm.py` | Firm console: onboarding approval, auditor staffing, client dashboard |
| `evidence.py` | Upload, versioning, status, attributes, per-evidence history |
| `controls.py` | Controls + `gaps_router`, `tasks_router`, `messages_router`, `requests_router` (same file) |
| `audit.py` | Auditor verdicts, lock / unlock |
| `analytics.py` | Reuse rate, Day-1 framework readiness |
| `connectors.py` | DPDP evidence collectors (server-side pull instead of upload) |
| `export.py` · `activity.py` · `notifications.py` · `glossary.py` · `ciso.py` | Read models / integrations |

### Identity & access — `app/auth.py`, `app/authorization.py`, `app/oidc.py`
- `auth.py` — the `Actor` FastAPI dependency. Resolves either a stub token
  (`org:<id>` / `user:<id>` / `auditor:<engagement_id>`) or a real OIDC JWT, and
  calls `set_tenant` / `set_firm` so Postgres RLS is scoped for the request.
- `authorization.py` — the actual access rules (control-owner least privilege,
  engagement-scoped auditor visibility). Unchanged whether auth is stub or OIDC.
- `oidc.py` — JWKS fetch + token validation only.

### Pipeline — `app/service.py`
The orchestrator. `process_evidence` runs **ingest → evaluate → persist** and
owns the `Evidence.status` lifecycle. Gap/task history is append-only: a gap that
stops reproducing becomes `RESOLVED_BY_EVIDENCE`, never deleted. Locked links are
never rewritten.

### Domain logic (leaves of the pipeline)
| Module | Responsibility |
|---|---|
| `ingest.py` | Orchestrates one extraction call (native text or VLM) → validated fields |
| `documents.py` | Per-format native parsing + the "needs OCR" heuristic + encrypted-PDF detection |
| `evaluate.py` | The deterministic evaluator. Content pack + attributes → verdict, gaps |
| `normalize.py` | `"12 March 2026"` → date, `"quarterly"` → 90 days, `"Pass"` → true |
| `quality.py` | Evidence Quality Score — weighted, deterministic, always explained |
| `analytics.py` | Reuse rate and framework readiness math |
| `audit_log.py` | Append-only, hash-chained trail with before/after state |
| `ciso_sync.py` | Push locked verdicts / resolved gaps into CISO Assistant (best-effort) |
| `events.py` | In-process pub/sub for live pipeline progress to the browser (SSE) |
| `storage.py` | `LocalStorage` / `S3Storage` behind one `Storage` protocol |
| `upload_security.py` | The trust boundary: size, MIME sniff, allowlist, hash, malware scan |

### AI — `app/ai/`
| File | Responsibility |
|---|---|
| `gateway.py` | The `ModelGateway` Protocol — 3 methods. Swap providers by adding one class here. |
| `ollama.py` | The only implementation today. Local inference, nothing leaves the host. |
| `prompts.py` | Prompt templates + their versions (recorded on every `AiRun`) |
| `schemas.py` · `validators.py` | Expected output shape and the validation that rejects bad model output |
| `vision.py` · `streaming.py` | VLM page-image path; streamed extraction |

### Content — `app/content/`
Framework packs as YAML (`iso27001-2022.yaml`, `pcidss-4.0.1.yaml`, …), the UCO
map (`uco.yaml`), and the three-layer glossary. `load.py` parses and validates
them into `Content` at startup. **Frameworks are data, not code** — see the
README's "Adding a framework".

### Base — `app/models.py`, `app/db.py`
- `models.py` — every table in one file, by choice (the entity count doesn't earn
  a package). Tenant-owned rows carry `org_id`; firm-owned rows carry
  `audit_firm_id`.
- `db.py` — the engine, `get_session`, and `set_tenant` / `set_firm` (which set
  the Postgres GUCs the RLS policies read; no-ops on SQLite).

## Tracing one request

`POST /evidence` (`routers/evidence.py`):
1. `Actor` dependency authenticates and scopes the DB session to the tenant.
2. `upload_security.py` runs the trust-boundary checks; the file is written via
   `storage.py`; an `Evidence` row is created `UPLOADED`.
3. A FastAPI `BackgroundTask` calls `service.process_evidence`
   ([ADR-006](docs/adr/006-async-job-framework.md) — in-process, single worker).
4. `service` → `ingest.read_document` → `documents.py` (native) or `ai/vision.py`
   (VLM) → validated `ExtractedField`s, persisted as `EvidenceAttribute` rows,
   plus an `AiRun` audit row.
5. `service` → `evaluate.evaluate` for every subscribed framework → one
   `EvidenceControlLink` per requirement, `GapRow`s for shortfalls, a `TaskRow`
   per gap.
6. `quality.score_evidence` sets the quality score. Status → `READY` (or
   `NEEDS_REVIEW` / `FAILED`). `events.publish` streams each transition to the
   browser.

## Where common changes go

| Change | Touch |
|---|---|
| New endpoint | The relevant `app/routers/*.py`; register in `app/main.py` if it's a new router. Take `Actor` as a dependency. |
| New column / table | Edit `app/models.py`, then `alembic revision -m "..."` and hand-write the migration. If it's a tenant table, add an RLS policy migration (see below). |
| New framework or requirement | Add / edit a YAML file in `app/content/`. No Python. README has the schema. |
| New extractable attribute | Add it to the pack's `required_attributes`; add a `normalize.py` rule if it needs parsing; `evaluate.py` picks it up. |
| Swap / add an AI provider | New class implementing `ModelGateway` in `app/ai/`; select it where `OllamaGateway` is constructed. |
| New AI prompt | `app/ai/prompts.py`, and bump its `*_PROMPT_VERSION` so `AiRun` rows stay traceable. |

## Migrations

```bash
alembic revision -m "short description"      # creates a stub in alembic/versions/
alembic upgrade head
alembic downgrade -1
```

- Migrations read `DATABASE_URL` from the environment (see `alembic/env.py`).
- **RLS migrations are Postgres-only.** Follow the existing pattern: guard with
  `if op.get_bind().dialect.name != "postgresql": return`, then
  `ENABLE` + `FORCE ROW LEVEL SECURITY` and a `*_tenant_isolation` policy keyed
  on `current_setting('app.tenant_id')` (or `app.firm_id` for firm tables).
  Copy `alembic/versions/f4a5b6c7d8e9_control_messages_rls.py`.
- Chain is linear; the current head is the newest file. Run migrations with the
  privileged connection — the app's runtime role deliberately can't alter schema.
- Hosted DB notes (Supabase, roles, connection strings) are in the README.

## Tests

`pytest -q` — ~180 tests, no infrastructure. `tests/conftest.py` builds a fresh
SQLite DB and temp storage per test; fixtures live in `tests/fixtures/`.

- One `tests/test_<area>.py` per concern, mirroring the module it exercises.
- `test_live_*.py` need real infra (Ollama, CISO Assistant, SSE) and skip
  themselves when it's absent — never make them hard-fail.
- Run a subset with `pytest tests/test_evaluate.py -q` or `pytest -k versioning`.
- `python -m evaluation.runner --no-model` runs the rule engine against the
  golden corpus in `evaluation/`; `python -m demo` runs the whole slice end to
  end and prints each step.

## Conventions

- **An ADR before a structural change.** `docs/adr/` records every
  non-obvious call; add one (copy the format, append to `docs/adr/README.md`)
  rather than changing a boundary silently.
- **Docstrings carry the rationale.** Module and class docstrings here explain
  *why*, and often cite an ADR or the concept note. Match that when you add code.
- **Commits**: imperative subject, body explains the *why*. Keep unrelated
  changes in separate commits.
- **Don't log document contents** — only identifiers. The request middleware in
  `app/main.py` and `audit_log.py` both hold this line.
- Prefer the smallest change that fits the existing pattern over a new
  abstraction.

## Operational scripts

`monitor.py`, `dashboard-monitor.py`, `analyze-access.py` read `access.log`
(written per-request by the `app/main.py` middleware) for lightweight local
observability. Not part of the request path.
