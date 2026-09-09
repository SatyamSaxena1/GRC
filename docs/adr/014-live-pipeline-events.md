# ADR-014: Stream pipeline progress to the browser, without becoming the event bus ADR-009 deferred

## Context
Extraction against a real document is slow enough to feel broken. Measured on the
development machine (RTX 3080, `qwen2.5vl:7b`) against a real 16k-character ASV scan report:

| | |
|---|---|
| Time to first token | **~3s** |
| Time to last token | **~27s** |

Until now the browser saw none of that: it polled `GET /evidence/{id}/status` every 2s and
every extracted fact appeared at once, at the end. The user watched a spinner for ~20s and
then everything materialised — which reads as "hung, then finished", not "working".

The gap between 3s and 27s is entirely token generation, so it is recoverable: the model has
usable answers long before it has all of them.

## Decision
Stream the extraction (`stream: true`, already supported by the gateway's Ollama backend),
report each attribute the moment its JSON value closes, publish each framework's evaluation
as it is computed, and deliver all of it to the browser over Server-Sent Events
(`GET /evidence/{id}/events`). Measured end-to-end after this change: first fact on screen at
~10s instead of ~18s, then accumulating, instead of a single batch at the end.

**This is explicitly not the domain event bus ADR-009 deferred, and `app/events.py` says so
in its own docstring.** The distinction is not stylistic:

| ADR-009's deferred outbox | `app/events.py` |
|---|---|
| Durable, survives restart | In-memory, dies with the process |
| Ordered, replayable, at-least-once | Best-effort, drops on a full queue |
| Business logic reacts to it | Nothing reacts to it; only a browser renders it |
| Would make a commit + publish atomic | Publishes *after* the commit, and doesn't care if it fails |

Every event published is a **preview of a row the pipeline is persisting anyway**. The
database remains the single source of truth. If the stream never connects, drops mid-run, or
the process restarts, nothing is lost and nothing is inconsistent — the client falls back to
the existing poll and reads the persisted result. That fallback is retained deliberately and
must stay: the stream is an accelerator, never a dependency.

**Streaming is only used when someone is watching** (`events.has_subscribers`). With no
subscriber the pipeline takes the ordinary blocking path, so an upload driven by a script,
a test, or a closed browser tab behaves exactly as before.

**The streamed JSON is scanned, not repaired.** `app/ai/streaming.py` yields an attribute only
once its value is syntactically closed, and every slice it emits was accepted verbatim by
`json.loads` — a half-written value can never surface as a fact. A complete-but-malformed
entry is skipped and scanning continues, so one bad value cannot strand the attributes behind
it.

## Also decided here: remediation drafting is a drafting aid, not an assessment
`POST /gaps/{gap_id}/draft-remediation` asks the model for wording that would close a gap,
plus the artefacts an auditor would expect as proof. It is bounded the same way ADR-012's
nutshell is: **it writes nothing, closes nothing, and cannot move a verdict.** ADR-004's split
holds — the model produces facts and prose, `app/evaluate.py` decides compliance. POST rather
than GET because it costs a model call, not because it changes state; the test suite asserts
the gap is untouched afterwards.

## Alternatives considered
- **Structured outputs (JSON schema) for extraction.** Measured: 5x faster (4.9s vs 27s) and it
  filled three fields on a document where the current prompt returned nothing. **Rejected for
  now**: it also invented `asv_company: "Extract87"`, reproducibly. A schema pressures the model
  to fill every field, trading honest nulls for confident fabrication — the exact failure ADR-004
  exists to prevent, and unacceptable in an evidence trail. Revisit behind a verification gate
  (below).
- **Verbatim-quote verification as the gate for the above.** Tested: requiring a quote per value
  and checking it appears in the source text *did* catch the fabrication deterministically, but
  did **not** catch misattribution (real quote, wrong field — it returned the completed-date as
  the expiry-date). A partial defence, so it is recorded as a finding rather than shipped as a
  safeguard.
- **Server-side polling instead of SSE.** Simpler, but caps granularity at the poll interval and
  cannot show sub-extraction progress at all, which is the entire point.
- **EventSource on the frontend.** Cannot send the `Authorization` header this app authenticates
  with; `fetch` + a stream reader is used instead.

## Consequences
- Single process only, exactly as ADR-006's in-process BackgroundTasks already assume. A second
  worker would find no subscribers and publish into nothing — degrading to today's polling
  rather than breaking.
- `X-Accel-Buffering: no` is set on the stream so a proxy doesn't buffer it into uselessness;
  verified streaming correctly through the Vite dev proxy.
- **Trigger to revisit**: if anything other than a browser ever needs to consume these events,
  that is the real consumer ADR-009 named, and the outbox — not this module — is the answer.
