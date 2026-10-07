# ADR-018: What the model may do — witness, doubter, suggester, narrator; never a decider

> **Status:** Proposed. This records the boundary the code already keeps, so the next
> model feature is measured against a written rule instead of re-derived from ADR-004.

## Context
ADR-004 split the work three ways: the model extracts facts, Python decides the verdict, a
human locks it. At the time the model did exactly one thing. It now does seven:

| Use | Where | What its output can change |
|-----|-------|----------------------------|
| Attribute extraction (value + quote + page) | `app/ai/extraction.py`, `app/service.py::_run_pipeline` | The facts `app/evaluate.py` decides on |
| Artefact-type suggestion on the upload form | `app/routers/evidence.py::suggest_artefact_type` | A pre-filled dropdown; nothing stored |
| Rights-request kind suggestion | `app/routers/rights_requests.py::suggest_kind` | A pre-filled dropdown; nothing stored |
| Wrong-document guard | `app/service.py::_type_mismatch` | `READY` → `NEEDS_REVIEW` |
| Quote-support check | `app/service.py::_unsupported_values` | `READY` → `NEEDS_REVIEW` |
| Auditor nutshell (ADR-012) | `app/ai/extraction.py::generate_nutshell` | Text an auditor reads |
| Remediation draft, cross-framework explanation | `app/ai/extraction.py::draft_remediation`, `app/ai/explain.py` | Text a person reads |

And one use was tried and dropped: model-suggested task priority (`app/service.py`, "No
model-suggested priority", 2026-09-24).

Each addition was argued locally ("suggestions only", "it narrates, it does not judge"), and each
argument holds. But nothing written says what the *next* one may do. The two guards are the
first uses whose output changes the state of evidence rather than only text on a screen, and the
next step along that line — a guard that *clears* a review, a suggestion that is saved without a
click, a confidence that auto-accepts — would cross ADR-004 without any single commit looking like
the one that did it.

## Decision
The model may act in exactly four roles. A new use must fit one of them, or get its own ADR.

1. **Witness** — states what a document says, with the quote and page it says it on. Extraction
   is the only witness. Its output is the one model output that reaches `evaluate()`, and it
   reaches it only as attributes that went through `app/normalize.py` and validation; a value
   without a source is treated as not stated.
2. **Doubter** — may send an item *to* a human, never *away from* one. The wrong-document guard
   and the quote-support check are doubters. A doubter's output can only add a
   `NEEDS_REVIEW` reason; it never changes a verdict, a gap, a declared artefact type or any
   extracted value. It is evaluated as declared and flagged, not re-routed.
3. **Suggester** — pre-fills a choice a person then makes. Nothing a suggester returns is
   persisted unless a person submits it (`/suggest-type` and `/suggest-kind` store nothing).
4. **Narrator** — explains a decision after Python and people have made it, given only that
   decision's facts (ADR-012). Narration is labelled as model-written, is never read by
   `evaluate()`, `app/quality.py` or any status transition, and its absence is a degraded nicety.

**Never, in any role:** decide or change a verdict, a gap's kind or severity, a quality-score
number, a task's priority, which framework or clause applies, the artefact type; close a gap or
task; clear a `NEEDS_REVIEW`; lock, unlock or count toward a human verdict; auto-accept evidence.

Four rules make the roles hold:

- **One-way ratchet.** Model output may add a reason for human attention; no model output may
  remove one. This is the line the guards sit on, and the line an "auto-accept above 0.95"
  feature would cross.
- **Absent equals never asked.** Every non-witness call has a defined no-model path identical to
  the call not existing (`decision.choose` returns `{}` and the caller carries on). The witness
  is the exception and fails closed: no facts means every requirement fails and the evidence goes
  to `NEEDS_REVIEW`, never a pass. Consequence: a doubter is best-effort. It may be described as
  "catches most misfiled documents", never as a control the audit relies on.
- **Every call is on the record.** Each model call that influences state is logged as an `AiRun`
  with operation, model, provider and prompt-template version, so any flag can be explained
  later. Every threshold (`MISMATCH_TOP`, `UNSUPPORTED_MIN`, `SUGGEST_THRESHOLD`) carries the
  model and date it was measured on, and is re-measured with `evaluation/` when the model changes.
- **The deciding modules import nothing from `app.ai`.** `app/evaluate.py`, `app/quality.py` and
  `app/normalize.py` do not today; a test should keep it that way, so the boundary is checked by
  CI rather than by review.

## Alternatives considered
- **Leave ADR-004 as the only rule.** It was written when "the model" meant extraction. It says
  the model must not *judge*; it is silent on a model that *routes*, which is what the guards do
  and where the next drift would come from.
- **Allow model confidence to auto-accept above a threshold.** This is the obvious next
  efficiency step and the one this ADR exists to stop. The README already names the condition
  ("auto-accept stays gated on `evaluation/`"); a 3-case golden corpus cannot support it, and
  even a large one measures the average document, not the adversarial one.
- **Let a doubter re-route rather than flag** (evaluate a misfiled scan report as `SCAN_REPORT`
  because the model is 87% sure). Rejected: the model would then choose which rules apply, which
  is a verdict by another route. The declared type stays authoritative until a person changes it.
- **Ban the model from state changes entirely, guards included.** Rejected: a doubter only ever
  costs a human look, and the two in place catch real failures (three misfiled scan reports;
  five of six wrong extracted values in the 2026-10-06 measurement).

## Consequences
- The question for a new model feature becomes "which role is this?". Most answers are quick;
  one that fits none is the signal to write an ADR instead of a commit.
- A doubter that fails silently lowers coverage without telling anyone. Track the rate at which
  doubters return `{}` (from `AiRun`) if they come to matter.
- The witness remains the residual risk. A confident, wrong, well-quoted extraction passes every
  doubter and reaches `evaluate()`. The defences are the quote shown to the auditor and the
  auditor's own look, which is why ADR-012's nutshell must stay a summary and never become a
  substitute for opening the cited page.
- Follow-up: an import-boundary test (`app/evaluate.py`, `app/quality.py`, `app/normalize.py`
  must not import `app.ai`) and a status-transition test that no model-produced value moves
  evidence from `NEEDS_REVIEW` to `READY`.
