# ADR-012: An auditor-only AI narration of the verdict, redacted by field not by object

## Context
Auditors asked for a short AI-written summary of why a control got its verdict — something to
read in seconds before opening the evidence itself — visible only to them, not the auditee
(the "internal note vs. public reply" pattern every ticketing tool has: one record, one
privileged backchannel). Every existing role check in this codebase (`app/authorization.py`)
is object-level: an unassigned control or a cross-tenant row answers 404, "invisible" rather
than "visible but partly blanked." Nothing here has ever redacted one field of an otherwise
visible object.

The natural risk: doing this well means inventing generic infrastructure (a redaction
framework, per-field visibility rules in the schema) for what is, today, exactly one field.

## Decision
One column (`EvidenceControlLink.nutshell`), one narrow conditional at the two places a link
is already serialized (`app/routers/evidence.py::_link_payload`,
`app/routers/controls.py::get_control`): `if actor.is_auditor: payload["nutshell"] = ...`. No
redaction framework, no field-visibility schema — a second redacted field, if one ever appears,
is the trigger to build one; until then this is simpler to read and to audit than an
abstraction serving a single caller.

**The nutshell narrates, it does not judge.** ADR-004 draws a hard line: the model extracts
facts, Python decides PASS/PARTIAL/FAIL, a human locks it. The nutshell prompt
(`app/ai/prompts.py::NUTSHELL_SYSTEM_PROMPT`) is given the verdict and gaps *after* Python has
already decided them and is explicitly forbidden from stating anything not given to it — it
explains a decision, the same way the extraction prompt already narrates "the document says 8,
page 6" rather than an opinion. This is why the feature does not compromise ADR-004: a second
model call that can only repeat and cite what the deterministic evaluator already concluded is
not a second verdict.

**Generated eagerly, in the same pipeline pass as extraction and evaluation** — one gateway
call per link, right after that link's `Link` is computed in `app/service.py::_run_pipeline`,
gated on the same `gateway.available()` signal the extraction call already produced (`run.status
!= "UNAVAILABLE"`), so an offline model skips every nutshell call for that evidence rather than
repeating a doomed health check per link. Failure never blocks the pipeline or flips
`READY`→`NEEDS_REVIEW`: a missing nutshell is a degraded nicety, exactly like a missing
extracted attribute is handled elsewhere.

## Alternatives considered
- **Generate lazily, on first auditor read.** Rejected: needs a new on-demand endpoint, a
  loading state, and a cache-invalidation story for when evidence is reprocessed — more surface
  for one field than the existing synchronous, no-event-bus pipeline shape (ADR-009) already
  gives eager generation for free.
- **A generic redaction framework** (per-field role visibility declared in the schema).
  Rejected as speculative for one field — see Decision above.
- **Reuse `ControlMessage`** (the existing auditor↔auditee thread table) with a new
  `AI_SUMMARY` kind. Rejected: `ControlMessage` rows are things a person said
  (`created_by`, `resolved_by`); a system-generated narration of a link is not a message in a
  conversation, and forcing it into that shape would need a fake "system" actor and would file
  it in a place readers expect human back-and-forth.

## Consequences
- The frontend types the field as optional (`nutshell?: string`) — absent for a non-auditor
  caller, not merely empty, so "the API never told you" and "the model had nothing to say" stay
  distinguishable in the network response.
- A second redacted field on any record is the signal to stop repeating this conditional by
  hand and build the framework this ADR declined to build now.
