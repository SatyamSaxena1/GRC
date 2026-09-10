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

Five parties, two tenancy axes. An **audit firm** onboards clients and staffs its
**auditors** onto them; an **organisation** (the auditee) supplies evidence through its
**org admin** and **control owners**. Firm-owned rows are scoped by `audit_firm_id`,
auditee-owned rows by `org_id` — an auditor working a client carries both. The rule that
matters: *belonging to a firm grants access to nothing*. Being staffed on an engagement
(`EngagementAuditor`) is the grant, and an unstaffed client answers 404, indistinguishable
from one that does not exist.

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

### Against Supabase (hosted Postgres)

Use the **session pooler** connection string (port 5432), not the transaction
pooler (6543) — Alembic DDL and the per-transaction tenant GUCs need session
mode. Grab it from Supabase → Project Settings → Database → Connection string.

```bash
export DATABASE_URL='postgresql+psycopg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres'
alembic upgrade head        # creates the schema, RLS policies, and revokes the PostgREST anon grants
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
| `app/content/` | Framework packs (YAML) — requirements, UCO mappings, delta conditions — plus the glossary |
| `app/evaluate.py` | The deterministic evaluator. The product's core |
| `app/normalize.py` | "12 March 2026" → a date, "quarterly" → 90 days, "Pass" → true |
| `app/quality.py` | Evidence Quality Score — weighted, deterministic, always explained |
| `app/analytics.py` | Reuse rate and Day-1 framework readiness — the headline metrics |
| `app/audit_log.py` | Append-only, hash-chained trail with before/after state |
| `app/documents.py` | Native parsing per format + the OCR-needed heuristic |
| `app/ai/` | ModelGateway, prompts, structured extraction, validation |
| `app/service.py` | Pipeline: extract → evaluate → links, gaps, tasks, ai_run |
| `app/authorization.py` | Control-owner least privilege, engagement-scoped auditors |
| `app/routers/firm.py` | The firm's side: onboarding approval, staffing, client dashboard |
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

Eight packs ship today. Seven share the same IAM/vulnerability-management UCOs so one
policy or scan report reuses across all of them: `ISO-27001`, `PCI-DSS`, `SOC-2`,
`NIST-CSF`, `HIPAA`, `CIS-CONTROLS`, `GDPR`. Clause text is our own paraphrase, not
quoted from any standard's licensed wording; numeric thresholds a framework doesn't
state explicitly (e.g. HIPAA's addressable specifications) are flagged as our own
baseline in a comment next to the clause.

The eighth, `NIST-AI-RMF` ([ADR-016](docs/adr/016-ai-rmf-starter-pack.md)), is the deliberate
exception: it owns a new `AI_GOVERNANCE` UCO domain because AI governance maps onto none of the
existing objectives, its clause text is NIST's own (public domain), and it covers 11 of the 19
GOVERN subcategories — only those a document can actually evidence. The rest are real outcomes
that no attribute can honestly settle, and inventing one would manufacture a passing verdict
rather than measure it.

## Glossary

Three layers behind one lookup (`GET /glossary`, and the `<Term>` tooltip) — 4,280 terms, see
[ADR-015](docs/adr/015-glossary-layers.md):

| File | Terms | What it is |
|------|-------|------------|
| `app/content/glossary.yaml` | ~70 | Hand-written: the platform's own vocabulary, legal definitions (GDPR Art. 4, HIPAA §160.103), paraphrased standards. **Edit this one.** |
| `app/content/glossary-nist.json` | ~3.9k | NIST CSRC glossary, verbatim, public domain. Generated. |
| `app/content/glossary-ai.json` | 447 | NIST's "Language of Trustworthy AI" — quotations from ISO/IEEE/papers, each keeping its own citation. Generated. |

Earlier layers win every name collision. An empty search returns the curated layer only — the
corpora are reached by searching, which also keeps the tooltip payload at ~20KB.

**Regenerating** (never hand-edit the JSON; nothing fetches at runtime):

```bash
python -m scripts.import_nist_glossary
```

That downloads NIST's own published bulk export and verifies it against the sha256 NIST
publishes beside it. The AI glossary has no stable bulk URL, so it takes the CSV exported from
https://airc.nist.gov/glossary/ as a path:

```bash
python -m scripts.import_ai_glossary "path/to/Glossary.csv"
```

## Known limitations

Honest list, kept current:

- **DPDP is a readiness subset, not certification.** It covers nine document-verifiable and
  technical implementation checks. Applicability, exemptions, lawful purpose and consent validity
  still need qualified legal review. Most substantive provisions represented by the pack commence
  on 14 May 2027 under the 13 November 2025 notification.
- **DPDP connectors use a normalized collector contract, not turnkey vendor OAuth.** AWS, M365,
  Google Workspace and HRMS can be pulled into immutable evidence through configured server-side
  endpoints, but the deployment still needs least-privilege API grants and a source-specific adapter.
  There is no recurring scheduler yet; sync is on demand. HRMS has no universal API.
- **Connector applicability is not modelled.** An organisation that does not use one of the four
  named systems cannot yet mark its source-specific readiness check not applicable, so the preview
  score will understate its posture. Add a scope/assets domain before treating the score as complete.

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
- **Auth is a stub.** `authorization: org:<id>` / `user:<id>` / `auditor:<engagement>` /
  `firm:<audit_firm_id>`. The authorization *rules* are real and tested; identity is not.
  Note `auditor:<engagement>` deliberately bypasses staffing — it is the dev/demo shortcut.
  A firm *user* (`user:<id>` plus `x-engagement-id`) goes through the real staffing check,
  and so does the OIDC path.
- **Prompt injection is mitigated, not solved.** Hardened prompt plus the deterministic
  evaluator as backstop; tested against one probe corpus, not proven in general.
