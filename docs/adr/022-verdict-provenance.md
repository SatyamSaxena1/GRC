# ADR-022: Verdict provenance — every computed verdict names its rule, engine, build and inputs, and can be replayed

> **Status:** Proposed. Pattern from the earlier Trishul attempt (hashes proving which rules
> produced a decision), with the gaps Trishul shipped with closed.

## Context
ADR-004 says a verdict is reproducible because Python decides it, not a model. Until now nothing
let anyone check that. A link stored a verdict and `evaluated_at`, but not which version of the
rule produced it, what the evaluator was, which date freshness was judged against, or which facts
it read. Content packs change by deploy, `as_of` defaults to today, and an auditor's lock
overwrote the computed verdict. So "the rules said PARTIAL on 30 September" was an assertion, not
something an auditor could re-run.

Trishul hashed its rule packs, but three things undermined it: the rule hash covered metadata and
not the rule's logic; the recorded pack hash could disagree with the code that actually ran; and
its input hash left out inputs that changed verdicts. Replaying an old pack was impossible.

## Decision
Every computed verdict (`evidence_control_links`) records:

| Field | What it pins |
|---|---|
| `rule_hash` | the requirement's full definition, hashed exactly as `app/exceptions.py::rule_hash` (the same hash gap exceptions are bound to). The body is kept in `rule_definitions`, keyed by that hash, insert-only |
| `engine_version` | `app/evaluate.py::ENGINE_VERSION`, bumped by hand when evaluator logic changes |
| `build_id` | the deployed commit (`RENDER_GIT_COMMIT`) |
| `evaluation_inputs` | exactly what the rule can read: `consulted_attributes()` of the evidence, the org commitments it uses, the artefact type and the `as_of` date |
| `evaluation_hash` | sha256 of rule hash, engine version, clause, inputs, verdict and gaps; no ids or timestamps, so equal decisions hash equal |
| `engine_verdict` | what the rules said; a lock overwrites `verdict`, never this |

`GET /evidence/{id}/links/{link_id}/replay` re-runs the stored rule body (after checking it still
hashes to its key) over the stored inputs and returns `REPRODUCED`, `DIFFERS`, `NOT_RECORDED` or
`RULE_BODY_INVALID`, plus whether the rule has changed since and what today's rule would say.
`GET /content/packs` names every pack in force by hash. `EVIDENCE_PROCESSED` and `CONTROL_LOCKED`
audit events carry the evaluation hashes, so the hash chain commits to exactly what was decided
and what was locked.

How Trishul's gaps are closed:
- **Logic, not just metadata.** `tests/test_verdict_provenance.py` pins a fingerprint of the
  evaluator's outputs over the golden cases. Changing what any verdict or gap would be fails it
  until `ENGINE_VERSION` and the fingerprint change together — a check that can go red.
- **Replay runs the rule as it was.** Rule bodies are stored by hash, so an old verdict is
  re-run with its own rule, not today's.
- **All verdict-changing inputs.** A test re-evaluates every requirement in every pack over the
  golden cases, demo samples and change-control snapshots, using only the recorded inputs, and
  requires the same evaluation hash.

## Consequences
- Links judged before this change show no provenance and replay as `NOT_RECORDED`; reprocessing
  records it.
- Inputs duplicate a few extracted values per link. They are tenant data under the link's
  existing RLS; nothing new is exposed.
- An evaluator change now needs a version bump, which also tells every later verdict which logic
  produced it.
- `rule_definitions` has no tenant column, by design: packs are public in this repository.
