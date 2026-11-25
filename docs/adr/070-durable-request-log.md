# ADR-070: Keep a compact request log in our own database for 365 days

**Status:** Accepted (owner decision, 26 Nov 2026)

## Context
The DPDP Rules (6(1)(e), 8(3)) ask for security logs kept at least a year. Our per-request access log lived only on the
server's temporary disk and was lost on every deploy. The audit log (hash-chained, ADR-001 and later) was already durable; the
request log was not. The owner has not chosen a paid log service.

## Decision
Store one row per request in a `request_logs` table in the existing Postgres database, and delete rows after 365 days.

- **What is stored:** time (UTC), method, path (never the query string), status, request id, how the caller signed in
  (`present`, `none`, `demo`, `operator`; never the credential), organisation if one was resolved, caller address, duration.
  Never bodies, headers, tokens or email addresses: a path segment containing `@` is replaced, and a caller-supplied request id
  that is not a plain token is stored as `invalid`. The address is the Cloudflare header, else the last forwarded hop, else the
  socket peer. `operator` means a key was presented; the status shows whether it was right.
- **Never in the request's way:** the middleware only appends to an in-memory buffer. A background task writes batches every 5
  seconds and once more at shutdown. If the database is away the batch goes back, the buffer is capped at 5,000 rows (oldest
  dropped), and one warning is logged until a write succeeds.
- **Not stored:** `/health/*` (polled every few seconds) and `/csp-report`; they are counted in memory and the count is shown on the
  operator endpoint.
- **Retention:** `LOG_RETENTION_DAYS`, default and floor 365. Below 365 is honoured only with `LOG_RETENTION_ALLOW_SHORT=1`, and a
  warning is logged. A daily job (first run a minute after start) deletes older rows.
- **Who can read it:** the table is not tenant-owned, but under forced row-level security anyone may INSERT while SELECT and DELETE
  need `app.log_access = 'on'` in the transaction. Only the operator endpoint `GET /admin/request-logs` (admin key, same wrong-key
  lockout as the other operator routes) and the retention job set it. A tenant session reads nothing.
- **A policy template:** "Logging and Monitoring Policy", whose retention figure is the strictest `log_retention_days` in the packs.

## Consequences
- The 365-day claim becomes true only once this is deployed and the migration has run, and only for rows from then on; nothing
  earlier exists to keep. It holds as long as the Supabase database itself keeps its data (backups remain a separate open item).
- The daily gate is in-process, so a restart prunes again that day, which is harmless.
- Rows hold personal data (an address), so the privacy notice must say they are kept for a year.
- The old `access.log` file and the stdout line are unchanged and still ephemeral.
