# GRC evidence platform — thin vertical slice

One evidence document, evaluated once, against every framework the organization
subscribes to — with provenance, gaps, remediation tasks, and an auditor verdict that
locks the result.

The bet this slice tests: **cross-framework evidence reuse**. Upload an access control
policy, and it should satisfy ISO 27001 while producing precise, actionable PCI DSS
gaps — automatically, reproducibly, and defensibly.

## The architectural rule

```
LLM / VLM       extracts facts from documents, with page-level provenance
Python          decides compliance, deterministically, from content packs
Human auditor   records the verdict that closes and locks a control
```

The model never decides whether a control passes. It reports that the document says
"8 characters, on page 6"; `app/evaluate.py` decides that 8 < 12 fails PCI DSS 8.3.6.
That split is what makes a verdict reproducible, injection-resistant, and explainable
after the fact. See [ADR-004](docs/adr/004-deterministic-rules-before-llm.md).

## Quick start

```bash
python -m venv .venv && .venv/Scripts/activate     # Windows
pip install -e ".[dev]"
cp .env.example .env

ollama list                                        # pick a model you have
export OLLAMA_MODEL=qwen2.5vl:7b

alembic upgrade head
uvicorn app.main:app --reload
```

Without Ollama running, everything still works: extraction returns null fields and the
evaluator correctly reports every requirement as failed for missing evidence. It never
invents a pass.

### With infrastructure

```bash
docker compose up -d postgres redis minio
export DATABASE_URL=postgresql+psycopg://grc:grc@localhost:5432/grc
export STORAGE_BACKEND=s3 S3_BUCKET=grc-evidence S3_ENDPOINT_URL=http://localhost:9000
alembic upgrade head        # also applies the row-level security policies
```

## Tests

```bash
pytest -q                                # 181 tests, no infrastructure needed
pytest tests/test_live_ollama.py -v      # live model; skipped when Ollama is down
python -m evaluation.runner --no-model   # rule engine against the golden corpus
python -m evaluation.runner              # full pipeline, live extraction
```

## End-to-end demo

```bash
python -m demo                           # runs the whole slice and prints each step
```

Creates a tenant and an engagement, assigns a control, uploads a real policy, extracts
attributes with provenance, evaluates ISO and PCI independently, opens gaps and tasks,
reports the reuse rate and Day-1 readiness for an unsubscribed framework, uploads a
corrected V2, resolves the gaps, records an auditor verdict, locks the control, and
proves the auditee can no longer modify it.

The two numbers that make the pitch concrete:

```
GET /analytics/reuse              one artefact -> 7 control links, 6 uploads avoided (86%)
GET /analytics/readiness/PCI-DSS  an ISO-only org is 40% PCI-ready before subscribing
```

## Frontend

```bash
cd frontend && npm install && npm run dev   # http://localhost:5173, proxies to :8000
```

A React/TypeScript SPA over the endpoints below — see [frontend/README.md](frontend/README.md)
and [docs/frontend-integration-blueprint.md](docs/frontend-integration-blueprint.md) for the
screen-by-screen mapping. No login system; sign in with a bootstrap identity token.

## Layout

| Path | What lives there |
|------|------------------|
| `app/content/` | Framework packs (YAML) — requirements, UCO mappings, delta conditions |
| `app/evaluate.py` | The deterministic evaluator. The product's core |
| `app/normalize.py` | "12 March 2026" → a date, "quarterly" → 90 days, "Pass" → true |
| `app/quality.py` | Evidence Quality Score — weighted, deterministic, always explained |
| `app/analytics.py` | Reuse rate and Day-1 framework readiness — the headline metrics |
| `app/audit_log.py` | Append-only, hash-chained trail with before/after state |
| `app/documents.py` | Native parsing per format + the OCR-needed heuristic |
| `app/ai/` | ModelGateway, prompts, structured extraction, validation |
| `app/service.py` | Pipeline: extract → evaluate → links, gaps, tasks, ai_run |
| `app/authorization.py` | Control-owner least privilege, engagement-scoped auditors |
| `app/upload_security.py` | The trust boundary: size, MIME, allowlist, hash, malware |
| `evaluation/` | Golden corpus, metrics, quality gates |
| `docs/adr/` | Why the architecture is the way it is |

## Adding a framework

Frameworks are data, not code. Add a YAML file to `app/content/`:

```yaml
requirements:
  - clause: "8.3.6"
    evidence_requirements:
      - artefact_type: POLICY
        required_attributes: [password_min_length]
    mappings:
      - uco: UCO-IAM-011
        coverage: FULL
        delta_conditions:
          - attribute: password_min_length
            operator: ">="
            value: 12
```

The same uploaded evidence is then evaluated against it automatically, and where the
new framework is stricter, a specific gap is generated saying exactly what to fix.

## Known limitations

Honest list, kept current:

- **Model non-determinism.** A local 7B model returned different values across runs on
  the same document during development. The evaluator is deterministic; extraction is
  not. This is why auto-accept stays gated on `evaluation/`.
- **Golden corpus is 3 cases over 2 documents**, not the 20–30 the quality gates assume.
  The gate numbers are indicative until it grows.
- **Reuse rate counts links, not verified savings.** An artefact's first link is treated
  as the upload and every further link as reuse. That is the honest reading of the
  definition, but it assumes each link would otherwise have been a separate upload.
- **Freshness rules cover two artefact types** (ASV scan reports, policies). Any new
  requirement needs its own `evidence_validity` block or its evidence is never checked
  for staleness — the machinery does not apply itself.
- **The VLM fallback now has real code-path coverage** — `tests/test_documents_vision.py`
  exercises real `render_pdf_page`/PyMuPDF rasterization and the merge back into
  `read_document()` (skipped automatically without the `ocr` extra installed), and
  `tests/test_live_ollama.py` has one end-to-end test against a real vision model
  (skipped without one configured). Its readability heuristic also now catches
  garbled-but-nonempty text (bad encodings), not just short/empty pages — see
  [ADR-008](docs/adr/008-native-extraction-before-vlm.md)'s update section. Still
  unverified: accuracy on a real photographed/faxed document, as opposed to the
  synthetic scanned-style fixtures the tests generate.
- **MinIO/S3 storage is now exercised** by `tests/test_storage_s3.py` (put/get roundtrip,
  immutability, presigned URLs, and the full upload pipeline) — verified passing against
  a real `docker compose up -d minio createbuckets` container. Skipped automatically when
  MinIO isn't reachable, so CI stays green without docker.
- **No separate worker process** — see ADR-006.
- **Background jobs are in-process** ([ADR-006](docs/adr/006-async-job-framework.md)):
  no retries, and they die with the process.
- **RLS is untested in CI** — SQLite has no row-level security, so the policies in
  `alembic/versions/a1b2c3d4e5f6_row_level_security.py` need a Postgres CI job to be
  proven, not just applied.
- **Scanned PDFs need PyMuPDF** for page rasterization. Without it, unreadable pages
  degrade to missing attributes with a logged warning.
- **Auth is a stub.** `authorization: org:<id>` / `user:<id>` / `auditor:<engagement>`.
  The authorization *rules* are real and tested; identity is not.
- **Prompt injection is mitigated, not solved.** Hardened prompt plus the deterministic
  evaluator as backstop; tested against one probe corpus, not proven in general.
