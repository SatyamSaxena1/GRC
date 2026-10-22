# ADR-029 (Proposed): ISO/IEC 42001 and EU AI Act packs on the existing AI_GOVERNANCE objectives

Status: **Proposed**. Section 6 (ingestion) is built: `tools/ingest_source.py`,
`tools/review_drafts.py`, `tests/test_source_ingestion.py`. The AI Act Art. 4, 5, 26 and 27
drafts are in `drafts/eu-ai-act.yaml` awaiting review. No clause has been accepted into
`app/content/` yet.

## Context
Many of the organisations we talk to lead with ISO/IEC 42001 or the EU AI Act, and today we can
only show NIST AI RMF. ADR-016 anticipated this. It
phrased the nine `AI_GOVERNANCE` UCOs framework-neutrally precisely so a second and third AI
framework would map onto them instead of adding parallel taxonomies (`uco.yaml:42-46`). It also
named the cost: the reuse metric does not apply to AI frameworks until a second one exists.
These packs pay that cost back. **One AI policy upload satisfying AI RMF, 42001 and the AI Act
at once is the demo these prospects need to see.**

## Decision

### 1. Same admission test as ADR-016
A clause is packaged only if a document can state the thing, so that its absence is a real
finding. Outcomes no document can settle are left out, not given invented attributes. Both
packs are therefore partial by design, and each pack header says what is omitted and why.

### 2. Licensing decides how clauses are worded
- **ISO/IEC 42001:2023 is copyrighted ISO text.** The pack carries the clause number and our
  own paraphrased title and text, never the standard's wording. `guidance` is our own words.
  We need a purchased copy to check clause numbering and paraphrase accuracy.
- **EU AI Act (Regulation (EU) 2024/1689)** is EU law. EUR-Lex permits reuse with
  attribution, so article text can be quoted like NIST's.
- *Side finding:* `iso27001-2022.yaml` appears to quote Annex A wording near-verbatim. Check
  that separately; it doesn't block this work.

### 3. EU AI Act: deployer obligations first, provider obligations later
The AI Act splits obligations by role (provider vs deployer) and by risk class. Our prospects
are mostly **deployers**: banks, insurers and enterprises using AI, not building models for
sale. Deployer obligations also fit the "policy states X" shape well. Phase 1 packs the
deployer articles only, so no role-scoping code is needed yet. Provider obligations (Art. 9–15,
17, 72, 73) are phase 2 and need an org-level "AI Act role" setting, the way
`Organization.dpdp_na_sources` scopes DPDP. That code isn't worth writing until a provider
prospect appears.

### 4. Reuse the nine UCOs; add only two
Every clause maps onto an existing UCO wherever one fits. Two outcomes have no home:

| New UCO | Why the existing nine don't cover it |
|---|---|
| `UCO-AIGOV-010` Impact assessments of AI systems on affected people and their rights are performed and documented before deployment | 42001 6.1.4 / A.5 and AI Act Art. 27 (FRIA) are about effects on people. AIGOV-003 covers risk *to the organisation*. |
| `UCO-AIGOV-011` People affected by AI-assisted decisions are informed that AI is involved | AI Act Art. 26(11) and 42001 A.8. `UCO-PRIV-001` (privacy notice) is close and gets a SUPPORTING mapping, but AI disclosure isn't a privacy duty. |

AI Act Art. 26(6) log retention maps onto the existing **`UCO-LOG-001`** with a real
numeric condition (at least six months, so `>= 183` days). That makes it the first cross-domain
overlap between the AI and security packs.

### 5. One new artefact type
`AI_IMPACT_ASSESSMENT` is new, because an impact assessment is its own document and a
policy merely promising one is not evidence that one was done (the same reasoning that created
`AI_INVENTORY`). Everything else reuses `AI_POLICY`, `AI_INVENTORY`, `REVIEW_RECORD` and
`LOGGING_POLICY`.

### 6. Packs are drafted from source text, and a human approves each clause
Hand-writing YAML from a PDF does not scale past these two packs, and it leaves no link from a
clause back to the paragraph it came from. A four-stage pipeline replaces that. **The model only
drafts rules; it never decides a verdict** (ADR-004 still holds). Drafts go through human
review before anything reaches `app/content/`.

**Stage 1: sources (free-to-reuse texts only).** Raw downloads are stored under
`sources/<framework>/`, each with a `SOURCE.md` recording the URL, retrieval date, licence and
sha256.

| Framework | Source | Licence |
|---|---|---|
| EU AI Act | EUR-Lex, CELEX 32024R1689 (HTML/XML) | EUR-Lex reuse with attribution |
| GDPR | EUR-Lex, CELEX 32016R0679 | EUR-Lex reuse with attribution |
| DPDP Act 2023 and DPDP Rules | indiacode.nic.in / egazette | Government of India publication; record the exact terms in SOURCE.md |
| NIST AI 100-1, NIST CSF 2.0 | nist.gov | US Government work, public domain |

**ISO, PCI DSS and AICPA text is never fetched or stored.** Those packs keep clause numbers and
our own paraphrase only (section 2), and a test enforces it.

**Stage 2: deterministic parse.** Each source is parsed into numbered provisions (article /
paragraph / point) as JSONL:
`{id, framework, ref, text, url, sha256}`. There is no LLM in this stage, and the same input
bytes must always produce byte-identical output. For EUR-Lex, use the XML's own article and
paragraph structure rather than guessing from text layout. The stdlib (`html.parser`,
`xml.etree`) should be enough, so no new dependency.

**Stage 3: drafting.** For each provision, the existing model gateway (`app/ai/gateway.py`,
ADR-005; local by default) drafts one requirement in the pack schema:
- `clause`, `title`, `text` (quoted only where the licence allows), `guidance`.
- `evidence_requirements` using **existing** artefact types where possible. A new type is
  flagged for the reviewer, never silently created.
- `mappings` onto **existing** UCOs, with coverage and confidence, and `source: AI`.
- `delta_conditions` only where the text states a checkable fact or a number, for example
  Art. 26(6) "at least six months" becomes `ai_log_retention_days >= 183`.
- `verdict_basis`: either `documentable` or `not documentable`, with a reason, applying
  ADR-016's admission test. Never invent an attribute to make an outcome testable.

Drafts are written to `drafts/<framework>.yaml` and **never** to `app/content/`. A draft that
fails the pack schema is rejected at this stage, not at review. The drafting run is
deterministic too (temperature 0, fixed prompt), and its prompt and model ID are recorded in
the draft file's header.

**Thermal limit:** if a local model runs, the GPU thermal watchdog stays on. The remote
LM Studio gateway (`app/ai/lmstudio.py`) is the default when it's reachable, because it puts no
heat on the laptop GPU.

**Stage 4: review gate.** `python -m tools.review_drafts <framework>` shows the source
provision next to each draft. The reviewer accepts, edits or rejects each one. On accept, the
requirement is appended to `app/content/<pack>.yaml`:
- its mapping `source` is set to `EXPERT`, because a person has now vouched for it;
- it gains a `source_ref` with the provision id and sha256, so every clause links to its exact
  source paragraph.

Drafts marked "not documentable" are shown so the reviewer can confirm the omission. They are
listed in the pack header's "left out" section rather than dropped silently.

**Schema change.** `Requirement` in `app/content/load.py` is `extra="forbid"`, so
`source_ref` must be added as an optional field: `source_ref: SourceRef | None = None`. Existing
packs load unchanged. This complements ADR-022: verdict provenance records which rule judged a
verdict, and `source_ref` records which legal text that rule came from.

**Checks (one test per stage):**
- Parsing the same file twice gives the same sha256 and the same JSONL.
- A draft that fails the schema is rejected.
- Accepted clauses load through `app/content/load.py`.
- No ISO text appears anywhere under `sources/`. The test fails on any `SOURCE.md` naming
  ISO, PCI or AICPA, or any file containing their copyright notices.

**First slice:** the EU AI Act deployer articles (Art. 4, 5, 26, 27) end to end, then stop and
report. This replaces hand-writing the AI Act table below. The table becomes the expected
output that the reviewer checks the drafts against.

## Proposed clause selection

Clause numbers are to be verified against the purchased standard before writing YAML.

### ISO/IEC 42001:2023: about 16 clauses

| Clause | Paraphrased outcome | Evidence | UCO |
|---|---|---|---|
| 5.2 / A.2.2 | An AI policy exists and is approved by top management | AI_POLICY | AIGOV-003 |
| A.2.4 | The AI policy is reviewed at planned intervals (cadence set by the org's own policy, per ADR-013) | AI_POLICY + REVIEW_RECORD | AIGOV-003 |
| 5.3 / A.3.2 | AI roles and responsibilities are defined | AI_POLICY | AIGOV-004 |
| A.3.3 | A process exists to report concerns about AI systems | AI_POLICY | AIGOV-007 |
| 6.1.2 | AI risk assessment process is defined | AI_POLICY | AIGOV-003 |
| 6.1.4 / A.5.2 | AI system impact assessment process is defined | AI_POLICY | **AIGOV-010** |
| A.5.3 | Impact assessments are documented and retained | AI_IMPACT_ASSESSMENT | **AIGOV-010** |
| A.4.2–A.4.6 | Resources for AI systems (data, tooling, compute, people) are documented | AI_INVENTORY | AIGOV-001 |
| 7.2 | People doing AI work are competent; training is recorded | AI_POLICY + REVIEW_RECORD | AIGOV-005 |
| A.6.2.6 | AI systems in operation are monitored | AI_POLICY | AIGOV-004 |
| A.6.2.8 | AI system event logs are recorded | LOGGING_POLICY | LOG-001 (PARTIAL) |
| A.8.2 | Users are given system documentation and information | AI_POLICY | **AIGOV-011** |
| A.8.4 | AI incidents are communicated to interested parties | AI_POLICY | AIGOV-007 |
| A.9.2 | Processes for responsible use of AI are defined | AI_POLICY | AIGOV-006 |
| A.10.3 | Suppliers of AI systems and data are assessed | AI_POLICY | AIGOV-008 |
| 9.3 | Management reviews the AI management system | REVIEW_RECORD | AIGOV-003 |

**Left out:** 4.1/4.2 (organisational context; no document settles "understood"), 9.1
(monitoring effectiveness is measurement, not a document) and the A.7 data-quality
controls (MEASURE-type, as in ADR-016).

### EU AI Act, phase 1 (deployer): about 9 clauses

| Article | Obligation | Evidence | UCO |
|---|---|---|---|
| Art. 4 | AI literacy of staff | AI_POLICY + REVIEW_RECORD | AIGOV-005 |
| Art. 5 | No prohibited practices; screening documented | AI_INVENTORY (`prohibited_practices_screened`) | AIGOV-002 |
| Art. 26(1) | High-risk systems used according to the provider's instructions | AI_POLICY | AIGOV-004 |
| Art. 26(2) | Human oversight assigned to competent people | AI_POLICY | AIGOV-004 |
| Art. 26(5) | Operation monitored; risks and serious incidents reported to the provider | AI_POLICY | AIGOV-007 |
| Art. 26(6) | Automatically generated logs kept at least six months | LOGGING_POLICY (`ai_log_retention_days >= 183`) | **LOG-001** |
| Art. 26(7) | Workers informed before high-risk AI is used at work | AI_POLICY | **AIGOV-011** |
| Art. 26(11) | People subject to decisions informed | AI_POLICY / PRIVACY_NOTICE | **AIGOV-011**, PRIV-001 (SUPPORTING) |
| Art. 27 | Fundamental-rights impact assessment where required (public bodies; credit scoring; life and health insurance pricing) | AI_IMPACT_ASSESSMENT | **AIGOV-010** |

Art. 27 covers credit scoring and insurance pricing, which makes it directly relevant to the
bank and insurer leads.

## What changes
- New: `sources/<framework>/` (raw text + SOURCE.md), `drafts/<framework>.yaml`, a parser
  and drafter module, and `tools/review_drafts.py`.
- `app/content/load.py`: add the optional `source_ref` field to `Requirement`.
- `app/content/uco.yaml`: add AIGOV-010 and AIGOV-011.
- `app/content/iso42001-2023.yaml` and `app/content/eu-ai-act-2024.yaml`: new packs. The
  loader globs `*.yaml`, so no loader change is needed.
- `frontend/src/pages/EvidenceList.tsx`: add `AI_IMPACT_ASSESSMENT` to the label lookup
  table.
- Tests:
  - extend `test_ai_rmf_owns_a_new_uco_domain` to assert that the two new packs *reuse* the
    AIGOV UCOs and add no other domain;
  - one reuse test: a single AI_POLICY counts toward all three AI frameworks;
  - one boundary test: Art. 26(6) at 182 days fails and at 183 days passes.
- `evaluation/`: add golden-corpus cases for the new attributes. As ADR-016 noted, whether
  extraction reliably finds them is an open question; the tests above don't answer it.

## What we must not claim
- **Not certification or conformity assessment.** The output is *evidence readiness* against
  the clauses the pack covers, and each pack header states its coverage.
- **No AI Act dates without checking them.** The high-risk application dates have been under
  revision, so check the
  current timeline before giving dates in a call.
- **Phase 1 is deployer-only.** A provider prospect should be told this before a demo, not
  after.

## Sequencing against the meetings
1. Build the ingestion pipeline (section 6) and run the first slice: AI Act Art. 4, 5, 26
   and 27, from source to reviewed clauses. Stop and report.
2. Add the two UCOs, `AI_IMPACT_ASSESSMENT`, the `source_ref` field and the tests in the same
   PR as the first accepted AI Act clauses.
3. Buy ISO/IEC 42001 and verify the clause table above. That pack stays hand-paraphrased,
   because its text can't go through the pipeline.
4. Run the pipeline on GDPR, DPDP and NIST CSF 2.0 to attach a `source_ref` to their existing
   clauses, and check them against their source paragraphs.
5. Re-record the demo with one AI policy satisfying three frameworks.

## Alternatives considered
- **Package all of 42001 Annex A (38 controls) and every AI Act article.** Rejected for the
  same reason as ADR-016: about half can't be evidenced by a document, and filling them with
  invented attributes would produce passing verdicts that mean nothing.
- **Build provider and deployer obligations with role scoping now.** Rejected for now: no
  provider prospect yet, and role scoping is code, while deployer-only is pure content.
- **Map the AI Act onto 42001 instead of onto the UCOs.** Rejected: that would make one
  framework the taxonomy for another, which is exactly what UCOs exist to avoid.
