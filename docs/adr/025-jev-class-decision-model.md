# ADR-025: Typed decisions get their own Jev-class model, measured on our own cases

> **Status:** Proposed. Builds on the Jev-style decisions in `app/ai/decision.py` and on
> ADR-018 (the model may doubt or suggest, never decide).

## Context
Three places ask a model to pick one option from a fixed list, reading the answer from the
next-token log-probabilities rather than from prose:
- the upload form's artefact-type suggestion and the wrong-document guard (`classify_artefact`);
- the quote-support check that flags an extracted value its own quote does not state;
- the rights-request kind suggestion.

They ran on the extraction model: a vision LLM chosen for reading scans, never tuned for
decisions. We measured its position bias live: one PCI attestation read SCAN_REPORT at 0.98 in
one option order and 0.71 in another.

JevBench (benchmarkheaven.com/jev-models) now ranks "Jev-class" decision models on four
axes: intelligence, calibration, speed and cost. Open-weight models match the closed Jev
reference there; for example H2O-Lightning-4B v1.1 (a 4B fine-tune of Qwen3.5-4B) scores
calibration 90 and speed 93. A 4B model is small enough to run beside the extraction model,
and self-hosting keeps every document on our own servers.

## Decision
- **A separate decision model, by environment only.**
  - `LLM_DECISION_MODEL` names it, and `LLM_DECISION_PROVIDER` / `LLM_DECISION_BASE_URL` /
    `LLM_DECISION_API_KEY` say where it runs and how to authenticate (Ollama, or any
    OpenAI-compatible server such as vLLM or llama.cpp).
  - Unset means exactly today's behaviour. Setting it is a deploy-free switch; unsetting it is
    the rollback.
  - The extraction gateway stands behind it (`FailoverGateway`). A decision server that is
    down costs one failed call, not the wrong-document guard.
  - `AiRun.model` names whichever model actually answered.
- **An answer that depends on the order is no answer.** When the permutation passes put
  different options on top, `decision.choose` returns nothing, and the caller behaves as if
  no model were configured.
- **Measured on our cases before it is switched on.** `python -m evaluation.decisions` runs
  candidate models through the exact production prompts, over the labelled documents, the
  demo samples, and `evaluation/decision_cases/`. It reports:
  - accuracy;
  - Brier score and ECE;
  - p50 latency per call, failed calls included, on JevBench's scale (80 is 1 s, 90 is 316 ms);
  - how often an answer depends on the option order;
  - what the guards would have caught, and falsely flagged, at today's thresholds.

  Self-hosted cost is the machine's, so it is not scored.

## Consequences
- **A different model can need different thresholds.** `MISMATCH_TOP` and `UNSUPPORTED_MIN`
  were measured on qwen2.5vl:7b. The evaluation prints what they would do for the candidate;
  if they are wrong for it, change them in the same change that switches the model, with the
  numbers in this ADR.
- **The corpus is small.** It has 12 type cases across three types, 18 quote pairs and 11
  rights messages. It shows a model is not worse on what we know; it is no general benchmark.
  Add a labelled case whenever production shows a miss.
- Nothing here lets a model decide a verdict. Every decision is still a suggestion, a flag for
  review, or nothing.

## Results
Fill in from `python -m evaluation.decisions --model <current> --model <candidate> --save`
before setting `LLM_DECISION_MODEL` in production.
