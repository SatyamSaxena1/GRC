# ADR-008: Native text extraction before any VLM call

## Context
A vision model can read any document, including machine-readable PDFs. It is also
orders of magnitude slower and costlier per page, and it invents text where an exact
text layer was available.

## Decision
Always parse natively first (`app/documents.py`: pypdf, python-docx, openpyxl, csv).
Fall back to the VLM only when a **deterministic heuristic** says native extraction
failed:

- the artefact is an image (`.png`, `.jpg`), or
- the file could not be parsed at all, or
- fewer than 60% of pages carry at least 100 characters (the signature of a scan).

Only the pages that failed are rendered and sent — never the whole document. The model
is never asked whether it needs OCR.

## Alternatives considered
- **VLM for everything.** Uniform code path; far slower and measurably worse on text
  PDFs, where the text layer is ground truth.
- **Ask the model whether OCR is needed.** Makes a routing decision non-deterministic,
  and costs a model call to decide whether to make a model call.

## Consequences
- Machine-readable documents cost zero vision calls. The real ASV scan reports and the
  access control policy all extract natively.
- Rasterizing a PDF page needs PyMuPDF, which is optional: without it, scanned-PDF
  pages degrade to "no text recovered" and surface as missing attributes with a logged
  warning, never as a crash.
- The thresholds are constants in `app/documents.py`, tuned against real documents
  rather than guessed once and hidden.

## Update: hardening the fallback path (kept two-hop, fixed weak points)

The README long carried "the VLM fallback has never been exercised end-to-end" as a
known limitation. Real tests now exercise the actual `render_pdf_page`/`complete_vision`
code paths (`tests/test_documents_vision.py`, skipped without PyMuPDF; a live scanned-PDF
test in `tests/test_live_ollama.py`, skipped without a reachable vision model), and that
review surfaced concrete weak points fixed alongside it — none of them change the
decision above, all of them tighten its execution:

- **The readability heuristic was blind to garbled-but-nonempty text.** A bad encoding
  or corrupted font mapping can produce plenty of *characters* that are not readable
  text, and the old length-only check (`MIN_CHARS_PER_PAGE`) let that straight through
  as "native text, skip the VLM." Added a printable-character-ratio check
  (`MIN_PRINTABLE_RATIO`, `app/documents.py`) alongside the length check, in one shared
  `_page_unreadable()` helper both `needs_vision()` and `pages_needing_vision()` now
  call — they had duplicated the same threshold logic independently before this.
- **DPI was a hardcoded 150 with no override.** Bumped the default to 200 and exposed
  `VLM_RENDER_DPI` as an env var, matching every other model-facing constant's config
  pattern (`app/ai/ollama.py`). Considered per-page-adaptive DPI and rejected it as
  scope beyond "harden the existing heuristic" — a named, tunable constant is exactly
  what this ADR already committed to over a hidden guess.
- **Document-text truncation to 16000 characters was silent.** Named the constant
  (`MAX_DOCUMENT_CHARS`, `app/ai/prompts.py`) and added a log line in
  `app/ai/extraction.py` when it fires — visibility only, the cap itself is unchanged.
  Chunking is the upgrade path if this turns out to fire often on real documents; it
  would not have been visible before this change to know whether it does.
- **Malformed and absent model output were indistinguishable in logs.** Both produced
  the same (correct) null field, but a present-and-invalid payload vs. a genuinely
  unmentioned attribute now log differently in `app/ai/extraction.py`, so a debugging
  session can tell which happened without changing the returned data.
