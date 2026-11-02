# ADR-031: Outbound notifications through one optional webhook

> **Status:** Proposed. Implemented: `app/notify.py`, model `NotificationLog`, migration
> `d5e6f7a8b9c0`, hooks in `app/routers/controls.py` and `app/routers/audit.py`,
> `python -m app.monitor --notify`, `tests/test_notify.py`.

## Context
Everything the platform wants a person to act on (tasks, requests from an auditor, evidence going
stale) was visible only inside the app. Nobody is told. There was no outbound channel at all.

## Decision
One generic webhook, off unless `NOTIFY_WEBHOOK_URL` is set.

- **Event notices** from the request path, after the change commits: a task assigned (one notice
  per bulk assignment, not one per task), evidence requested, unlock requested, a control locked.
  Delivery runs on a background thread, so a slow webhook never slows or fails the action.
- **Digest** from the monitor cron (`--notify`): the same attention items the in-app feed shows
  (expired, expiring, failed or stuck evidence, breach and rights-request deadlines). Each item is
  sent once and again only after `NOTIFY_RESEND_DAYS` (default 7), tracked in `notification_log`.
  A failed send is not recorded, so the next run retries it.
- **Payload** is small and content-free: kind, severity, a one-line message that names a task,
  framework or clause and never evidence text or message bodies, a link, the organisation id and a
  time. It carries `text` (Slack) and `content` (Discord) beside the structured fields.
  `NOTIFY_WEBHOOK_SECRET` signs the body (`X-GRC-Signature: sha256=<hmac>`).
- **Failure is never an error.** A refused or unreachable webhook is logged and dropped.

## Why a webhook, not email
It needs no mail server, so it works on the free hosting, and Slack, Teams and Discord accept it
directly. Email can sit behind the same call site later.

## Trade-offs
- Delivery is best effort and at most once for event notices: a process exit can lose one in flight.
  The digest is the safety net for what matters.
- One webhook per deployment, not per organisation or per person: it announces to a channel, it
  does not route to individual users.
- The digest covers attention items only. Open tasks and auditor requests are covered by event
  notices when they are created, not re-sent.

## Not covered
Per-user preferences or routing, email, retries beyond the next cron run, delivery receipts, and
notices for events not listed above (verdict replaced, exception requested, connector run partial).
