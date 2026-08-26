# ADR-009: Domain events and the transactional outbox — deferred, not forgotten

## Context
The specification asks for named domain events (`evidence.uploaded`,
`gap.resolved`, `control.locked`, …) carrying `event_id`, `event_type`, `tenant_id`,
`actor_id`, `entity_id`, `timestamp`, `correlation_id` and a payload, with an outbox table
where an event has to influence more than one transactional action.

This ADR exists because the gap was previously absent from the record entirely: pgvector
had ADR-002 explaining its deferral, while the outbox had nothing, which reads as an
oversight rather than a decision.

## Decision
Defer the event bus and outbox. Nothing currently consumes an event: there is one process,
one database, and every state change is committed in the same transaction that caused it.
An outbox exists to make a commit and a publish atomic — with no subscriber, it would be
a table that is written to and never read.

The append-only audit log (`app/audit_log.py`) already records the same facts, with a
hash chain and an explicit `seq`, and is queryable through
`GET /evidence/{id}/history` and `GET /controls/{id}/history`.

## Alternatives considered
- **Build the outbox now.** A table, a poller, a dispatcher, and a delivery-semantics
  decision, all serving zero consumers. It would be exercised only by its own tests.
- **Publish events inline from the service layer.** Couples producers to consumers
  precisely as the eventual bus is meant to avoid, and would need rewriting anyway.
- **Treat the audit log as the event stream.** Tempting — the rows carry actor, entity,
  timestamp and payload already. Rejected as a permanent answer: the audit log's
  contract is *evidential completeness*, and bending it into a delivery mechanism
  (consumer offsets, retries, redelivery) would compromise that.

## Consequences
- Anything wanting to react to a state change today must poll or read the audit log.
- The migration path is clear: the audit log is written at exactly the points events
  would be emitted, so an outbox writer slots into `audit_log.record()` and gains
  `correlation_id` from the `request_id` already threaded through every call.
- **Trigger to revisit**: the first real consumer — notifications, a webhook, or a
  separate worker that must react rather than be called. Building it before then is
  infrastructure without a user.
