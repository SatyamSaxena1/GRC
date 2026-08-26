# ADR-010: Push closed verdicts and resolved gaps into CISO Assistant, don't build risk/policy/vendor here

## Context
A benchmark of this slice against real GRC workflows found it strong at exactly one thing
(cross-framework evidence reuse, deterministic verdicts, provenance) and missing risk
register, policy lifecycle, vendor/third-party risk, and reporting — deliberately out of
scope per the README, but a real gap once someone wants to *use* this day to day.

CISO Assistant (github.com/intuitem/ciso-assistant-community, AGPLv3) already covers that
surface: risk register, TPRM, policy management, 150+ frameworks, a REST API. The
alternative — building Risk/Policy/Vendor/Incident tables and UI here — would duplicate a
maintained, audited open-source platform for no benefit specific to this slice.

## Decision
Deploy CISO Assistant standalone (its own containers, its own database). This app stays
the evidence-extraction engine and pushes results into it via its REST API
(`app/ciso_sync.py`); it never becomes a second copy of risk/policy/vendor data.

**Direction of sync:** one-way, this app → CISO Assistant. Nothing is pulled back into
`app/models.py`. If a page here ever needs risk context, it fetches CISO Assistant's API
live rather than caching a copy that can drift.

**Trigger for a sync call:** a closed fact, not pipeline chatter — `CONTROL_LOCKED`/
`CONTROL_UNLOCKED` (`app/routers/audit.py`) and a gap's `OPEN` → `RESOLVED_BY_EVIDENCE`
transition (`app/service.py`). Intermediate evidence-processing states are not synced.

**Mechanism:** a direct HTTP call at the same point the corresponding `audit_log.record()`
call happens, wrapped so a CISO Assistant outage never blocks the auditor's action — the
local lock/resolution is authoritative regardless of whether CISO Assistant heard about it.
A `CisoSyncState` row (one per local entity) tracks PENDING/OK/FAILED/SKIPPED for
observability and manual retry (`app/routers/ciso.py`); a `CISO_SYNC_FAILED` audit event is
recorded on failure so it surfaces the same way every other refusal does (see
`authorization.deny()`).

This is ADR-009's deferred trigger firing, not a new decision from scratch: ADR-009 named
"a webhook... that must react rather than be called" as the thing that would justify an
outbox. It does not exist yet — one consumer, no ordering/replay requirement, so a direct
push plus a status row is enough. The `push_verdict`/`push_gap_resolution` function
signatures already take ids and manage their own session, so a later `@dramatiq.actor`
decorator (ADR-006) is a no-op change if retries become necessary before an outbox does.

**Auth:** the service-to-service leg (this app's backend → CISO Assistant) uses a static
API token read from env, the same shape as `app/ai/ollama.py`'s `OLLAMA_*` config — no
end-user identity crosses this leg. The end-user leg (two separate UIs) needs a shared
identity provider before external users touch either; until then, the frontend deep-links
to CISO Assistant's own login.

## Alternatives considered
- **Build Risk/Policy/Vendor/Incident natively here.** Rejected: duplicates a maintained
  platform, and this slice's stated bet is evidence reuse, not becoming a full GRC suite.
- **Polling CISO Assistant, or pulling its data into local tables.** Rejected: nothing here
  needs to react to CISO Assistant's state, and a local copy of risk/policy data is a
  second source of truth that drifts. Read-through at render time if ever needed.
- **An outbox/event bus for this sync.** Rejected for the same reason ADR-009 rejected it:
  one consumer today. The seam is already in the right place if a second one appears.
- **iframe-embedding CISO Assistant's UI.** Rejected: CSP/CORS/cross-origin-session cost
  disproportionate to a deep-link with shared SSO.

## Consequences
- CISO Assistant's exact `requirement-assessment` payload schema isn't available outside a
  running instance's Swagger/ReDoc; `app/ciso_sync.py` isolates that assumption behind one
  constant (`REQUIREMENT_ASSESSMENT_PATH`) and payload dict, marked `ponytail:` — confirm
  against a live instance before go-live.
- A `CisoSyncState` row with status `SKIPPED` is expected and harmless when
  `CISO_ASSISTANT_BASE_URL`/`CISO_ASSISTANT_API_TOKEN` are unset (default: unset).
- **Trigger to revisit**: a second consumer of the same closed-fact events, or a delivery-
  order/replay requirement — at that point, ADR-009's outbox is the upgrade path, not a
  bespoke queue bolted onto `ciso_sync.py`.
