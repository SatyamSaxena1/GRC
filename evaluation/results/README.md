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

## Real gateway, thinking off (app/ai/openai_compat.py)

Through the production gateway class itself (no translator), `reasoning_effort: none`,
`json_schema` response format, LM Studio serving Gemma over LM Link:

| | translator, thinking on | real gateway, thinking off |
|---|---|---|
| verdict accuracy | 99.2% | **99.2%** |
| attribute accuracy | 98.1% | 98.1% |
| left out / invented / unstable | 0 / 0 / 0 | **0 / 0 / 0** |
| mean extraction time | 10.8 s | **4.6 s** |
| quality gates | pass | **pass** |

`20261006-144427-*` is the first thinking-off run **before** the date fix and is kept on purpose:
critical accuracy fell to 92% (gate FAIL) because a thinking model had been converting the
`Wed Jun 14 2023` dates printed by ASV reports to ISO form and the non-thinking one copied them
verbatim, which the normaliser could not read, so a valid scan became a false FAIL. Fixed in code
(`normalize.to_date` accepts a leading weekday) plus the guide asking for `YYYY-MM-DD`.
`20261006-145741-*` is the run after the fix.

## Hosting finding: LM Link is not a dependable transport

Three times the remote model dropped out ("No models loaded"), once mid-run. The server's own
message, captured once the gateway logged it: `LM Link connection entered error state
peer_keepalive_timeout`. The link flaps (the remote machine, `Gemperts-In`, later showed
*disconnected* after its GPU shut off). A production path that goes Render -> Funnel -> laptop
-> LM Link -> remote model inherits that. Serve the model on the machine that holds it instead.

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
