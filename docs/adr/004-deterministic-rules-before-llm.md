# ADR-004: Deterministic rules decide compliance; the LLM only extracts facts

## Context
The tempting design is to ask a model "does this policy satisfy PCI DSS 8.3.6?". Audit
verdicts must be reproducible and defensible; model output is neither.

## Decision
A strict split:

- **Model** — extracts facts with provenance ("the document states 8, on page 6").
- **Python** (`app/evaluate.py`) — applies the delta conditions from the content packs
  (`password_min_length >= 12`) and produces PASS / PARTIAL / FAIL.
- **Human auditor** — records the verdict that closes and locks a control.

Normalizations that are genuinely deterministic ("quarterly" to 90 days, "Pass" to
true) live in Python, not in the prompt.

## Alternatives considered
- **LLM-as-judge.** Non-reproducible: two runs disagreed on the same document during
  development, which is disqualifying for an audit trail.
- **LLM proposes, human approves everything.** No leverage over manual review.

## Consequences
- Re-running evaluation on unchanged attributes always yields the same verdict.
- Prompt injection cannot flip a verdict: even a fully subverted extraction still meets
  a deterministic rule (regression test in `tests/test_extraction.py`).
- Content packs, not code, hold framework rules, so adding a framework is a data change.
- The model's job is narrow enough that a small local model is viable for it, while the
  same model would be unusable as a judge.
