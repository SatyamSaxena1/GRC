# Evaluation results

One JSON (plus the console log) per `python -m evaluation.runner --save` run.
All runs: 11 documents (2 labelled + 9 demo samples), 3 repeats = 33 extractions,
`google/gemma-4-e4b` over LM Link, temperature 0, seed 42, num_ctx 16384.
This is **not** the production model (`qwen2.5vl:7b`); it is a fixed reference to compare
changes against on the same model.

## Attribute guide (R3): measured effect

| | control (no guide) | with guide |
|---|---|---|
| verdict accuracy | 98.5% | **99.2%** |
| attribute accuracy | 98.1% | 98.1% |
| facts left out ("said nothing") | 2 | **0** |
| facts invented (samples, closed-world) | 3* | **0 of 66** |
| runs that disagree with themselves | 2 of 52 | **0 of 53** |
| mean extraction time | 11.0 s | 10.8 s |

\* three answers that were correct; the breach-policy sample's label had omitted a fact its text states (fixed).

Files: `20261006-134747-*` is the first baseline (before the harness fixes, no guide).
`20261006-135634-*` is the **first guide attempt and is kept deliberately**: it regressed.
With the guide the model answered `mfa_required_for: []` for a document silent on MFA, which the
rules read as "stated, and wrong" (PARTIAL) instead of "missing" (FAIL). Fixed in code
(`ExtractedField` turns an empty answer into null) and in the guide wording.
`20261006-141835-*` is the final guide run.

## Known, unresolved

`access_review_frequency_days` still shows 75% on the real Asteron policy, which says access is
reviewed "quarterly for critical systems and annually for all other systems". The guide tells the
model to report the *least frequent* tier, so it answers `annually`; `labels/access_control_policy_v1.json`
says `quarterly` and expects PCI 7.2.4 to PASS, while `tests/test_real_document.py` expects `annually`
and PARTIAL. The two disagree with each other; the model is consistent with the rule it was given.
Needs an owner decision, then the label (never the model) is aligned.

## Limits

11 documents, one model, one run family. Indicative, not a clearance for auto-accept; the
harness itself warns below 20 documents. A run aborts with "model unreachable" instead of
scoring blanks.
