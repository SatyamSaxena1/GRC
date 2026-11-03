# ADR-039: A public trust page, off by default and content-free

Status: accepted

## Context
Customers and prospects ask "how do you handle security?" and today the answer is an emailed questionnaire.
Other compliance tools publish a trust page. The app had no unauthenticated surface that shows a tenant's
data, so the first one must be small, deliberate and revocable.

## Decision
- **Opt-in.** An organisation admin publishes; until then `/public/trust/{token}` is a 404 for everything.
- **Unguessable link, not a public listing.** `organizations.trust_token` (18 random bytes, url-safe) is the
  only way in. Unpublishing clears it, so the link dies at once; republishing issues a new one.
- **Content-free.** The response is counts and percentages: controls tracked, by verdict, locked by an
  auditor, per-framework requirements met, the date evidence was last collected, and three plain statements
  about how verdicts are decided. No file names, gaps, tasks, people or evidence. A test asserts that a
  sentinel file name, its text, the words "gap" and "task", and the token itself never appear in it.
- **Preview.** The admin sees the exact page before and after publishing, rendered by the same component.
- **Marked `noindex` and `no-store`**, so it is not indexed or cached.
- Figures are computed with the existing dashboard logic read as a viewer, so the page cannot disagree with
  the Overview. The public route binds the tenant itself after finding the organisation by token, so row
  level security still applies to every figure it reads.
- Publishing and unpublishing are audited; the token is never written to the log.
- Admin API lives at `/trust-settings` so the shareable address `/trust/<token>` stays a web-app route.

## Consequences
- Anyone holding the link can read the page; treat it like a shared document link and unpublish to revoke.
- There is no rate limit on the public route yet; the token is long enough that guessing is not practical.
- Showing "not meeting" counts is the organisation's choice; the preview is there so they decide knowingly.
