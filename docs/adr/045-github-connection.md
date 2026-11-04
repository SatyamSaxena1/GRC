# ADR-045: An organisation connects its own GitHub for change-control evidence

Status: accepted. Builds on ADR-044 (connections) and ADR-020 (change control from GitHub).

## Context
Change-control evidence was collected by a CI job using one platform-wide token and repository list set in
repository secrets. Every customer's repositories needed an operator to edit those. ADR-044 gave organisations a
way to connect a chat webhook themselves. This is the second connection, and the first that makes the server call
out with a customer's credential.

## Decision
- A second connection kind, `GITHUB_CHANGE_CONTROL`, holds a token and up to 10 `owner/name` repositories as one
  encrypted blob (same Fernet storage, same write-only rule, same organisation-admin-only rule).
- **The server only ever calls `https://api.github.com`.** The customer supplies a token and repository names,
  never an address, so no outbound-request-forgery resolver is needed for this slice. Repository names are
  matched against `owner/name` characters only. A collector that takes a customer-supplied address (self-hosted
  GitLab, Bitbucket Server) still needs the resolver and is a separate slice.
- "Check access" asks GitHub whether the token can see each named repository and records OK or the reason. It
  never stores or returns a response body or the token.
- A sync for an organisation with its own connection runs the existing read-only collector in-process with that
  token. The result goes through the same assessment, storage and evaluation path as before. An organisation
  without a connection keeps using the platform-wide collector URL, unchanged.
- **A saved connection that cannot be read (key replaced) fails the sync (HTTP 502). It never falls back to the
  platform-wide collector**, so one organisation's evidence is never replaced by another's.
- A crash in an own-token run reports only the error class, so a token cannot appear in a message.
- Audit events record who set, tested or removed it, the repository names and a hint (last four characters of the
  token), never the token.

## Consequences
- Recommend a fine-grained, read-only token limited to the named repositories; the page says so.
- Reading a repository's review history takes minutes, longer than a web request may live (found when first tried
  live). A sync by the button now runs in the background and returns 202 RUNNING at once; the run is recorded
  COMPLETE or FAILED when it ends. Cron already runs outside a request.
- Rotating `CONNECTIONS_KEY` works as for the chat webhook (comma-separated keys).
- The platform-wide CI job and its secrets remain as a fallback for the operator's own organisation.
