# Scheduled jobs (decision: stay with cron)

Closes the question in issue #80. ADR-006 chose an external scheduler over an in-process one, and that still holds:
a job that exits non-zero is something every scheduler already knows how to alert on, and an in-app scheduler would
need leader election to avoid running twice.

## The jobs
| Job | Command | When | What a red run means |
|---|---|---|---|
| Daily attention report | `python -m app.monitor` | daily | Something needs a human. The alert is working. |
| Weekly report | `python -m app.monitor --weekly-report` | Mondays | The webhook or database is wrong. |
| Retry extractions | `python -m app.monitor --retry-extractions` | optional, after the report | Evidence stuck because the model was down. |
| Collector sync (platform-wide) | `python -m app.monitor --sync-connectors` | manual | Storage secrets or a collector URL are stale. |

Customers connect GitHub themselves on the Connections page (ADR-045) and collect from there, so no scheduled job
is needed for that.

## Set it up on a customer's own deployment
- **GitHub Actions:** copy `.github/workflows/monitor.yml`. Secrets needed: `DATABASE_URL` (a URL reachable from
  GitHub's runners over IPv4; on Supabase, the session pooler) and `CONNECTIONS_KEY` (to read saved webhooks).
- **VM or Render cron:** run the same commands with the same environment as the web service.
- A missed run is safe: the weekly report de-duplicates, so re-running within the week sends nothing new.

## Retired
The 6-hourly connector sync was removed on 2026-11-05 because its storage secrets pointed at a retired project.
Delete these GitHub secrets if present: `S3_BUCKET`, `S3_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, and the variables `CHANGE_CONTROL_ORG_IDS`, `CHANGE_CONTROL_REPOS`.
