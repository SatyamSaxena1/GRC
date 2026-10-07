# ADR-021: Gap exceptions that cannot quietly widen

> **Status:** Proposed. Implemented: `app/exceptions.py`, `app/routers/exceptions.py`, model
> `GapException`, migration `b8c9d0e1f2a4` (under RLS from the start),
> `tests/test_gap_exceptions.py`. The pattern comes from the earlier Trishul attempt's
> `ExceptionWaiver`.

## Context
Some gaps are accepted rather than fixed for a while. The clearest case is the solo developer
under change control (ADR-019, ADR-020): there is no second person to approve merges, so
"reviewed after a cooling-off period" is a compensating control, not a pass. Without a way to
record that, the gap is either ignored or the rule is loosened, and both are worse.

The danger of exceptions is that they widen without anyone deciding: written against one value,
they silently cover a bigger one; written against one rule, they survive the rule changing; with
no end date, they become permanent.

## Decision
An exception is a separate, append-only record that never edits the gap. The evaluator keeps
recomputing the gap, and on every read the exception is checked against the gap as it is now.
It waives the gap only while all of these hold:

| Condition | Otherwise the state is |
|---|---|
| It was approved | `REQUESTED`, `REJECTED` or `REVOKED` |
| It has not expired; every exception has an expiry, at most 180 days out | `EXPIRED` |
| The requirement's full content-pack definition still hashes to `rule_hash` | `RULE_CHANGED` |
| The gap's framework, clause, attribute, kind and actual value still match `value_fingerprint` | `VALUE_CHANGED` |

Because validity is computed at read time, nothing has to run on a schedule to retire an
exception. "Four unapproved merges" accepted never covers five.

**Who may do what:**
- **Request:** the auditee side, with write access. It needs a justification of at least
  20 characters and an expiry; a compensating control is optional.
- **Approve or reject:** an auditor on the engagement. The approval records who decided and
  why. The requester can never decide their own request, and approval is refused if the rule
  changed after the request.
- **Revoke:** either side, at any time.

Every step is an audit event.

A waived gap stays `OPEN` and is reported with `waived: true` and the exception beside it, in
`GET /gaps` and on the Gaps page. Verdicts are unchanged: the rule's verdict and the human
decision to accept it are shown side by side, never merged.

## Alternatives considered
- **Mark the gap itself waived.** Rejected: the evaluator owns gap status, and the next
  re-evaluation would either overwrite the waiver or have to be taught to preserve it.
- **A scheduled job that expires exceptions.** Rejected: computing the state at read time is
  simpler and can't lag.
- **Let a waived gap turn the verdict into PASS.** Rejected for now (ADR-004): the rule's
  verdict and the human acceptance stay distinguishable. A later report can present them
  together.

## Consequences
- An exception tied to a content-pack rule is retired by any edit to that rule, even a
  wording change. That is deliberate: re-approving is cheap, and a silently surviving
  exception is not.
- The change-control solo-developer case has a defensible path: request an exception on
  `merges_without_independent_approval`, describe the cooling-off control, and have the
  auditor approve it for the audit period.
- Operational signal, also from Trishul: rising exceptions on one rule usually mean the rule
  is miscalibrated, not that the risk is acceptable.
