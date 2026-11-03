# ADR-041: A weekly compliance report, from what is already stored

Status: accepted

## Context
The monitor cron posts what needs attention (ADR-031), but nothing summarises the week: how the position
moved, what was collected, what is still open. Teams want one regular message they can read without opening
the app, and competitors send one.

## Decision
- **No new table.** `app/reports.py` builds the report from existing data: the current position is the same
  content-free summary as the trust page (ADR-039); "this week" counts gaps raised and resolved (their own
  timestamps) and audit events for collections, uploads and locks inside a seven-day window; "open now" is
  open gaps and overdue tasks.
- **Counts only.** No file name, person or evidence text; a test asserts none appears, so it can go to a
  shared chat channel.
- **Delivered by what already exists.** `python -m app.monitor --weekly-report` posts one message per
  organisation through `notify.digest`. The message carries its dates, so the existing de-duplication makes a
  re-run in the same week a no-op. A GitHub Actions job runs it Mondays 07:15 IST, beside the daily report.
  With no `NOTIFY_WEBHOOK_URL` it sends nothing and exits 0.
- **Readable in the app.** `GET /reports/weekly` (JSON and text) and `/reports/weekly.md`, for an
  organisation admin or compliance viewer only, since the figures aggregate the whole organisation.
  A Weekly report card on the Admin page shows the text and downloads Markdown.

## Consequences
- One webhook serves the whole deployment (as in ADR-031), so every organisation's report goes to the same
  channel; per-organisation channels are a later change.
- "Tasks completed" is not reported: tasks carry no completion time, and the audit trail is not queried for
  it. It can be added when tasks record when they were closed.
- The week is a rolling seven days ending when the report runs, not a calendar week.
