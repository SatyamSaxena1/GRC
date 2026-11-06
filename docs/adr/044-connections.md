# ADR-044: Connections an organisation sets up itself

Status: accepted. Slice 1 (chat webhook) built as written. **Later slices took a different route:** GitHub is connected
by a token and fixed host (ADR-045), AWS, Microsoft 365 and HR by customer-run scripts that upload answers (ADR-049, 050,
051), and scheduled jobs stayed with cron (ADR-006). The general outbound-address resolver described below was never
needed and was not built.

## Context
Everything the product talks to outward (the alert webhook, each evidence collector's URL and key) is a
server setting: Render environment variables for the web service, and a second copy in GitHub for the cron
jobs. That is wrong in three ways. An organisation cannot connect anything without the operator editing
servers; one value serves every organisation, so a second customer's alerts would land in the first one's
channel; and the two copies drift (the cron jobs ran for days against a database the app had left).

## Decision
A **Connections** page where an organisation admin pastes a destination, tests it, and removes it. Built in
slices; this ADR covers the rules every slice follows, and slice 1.

**Storage.** A `connections` table (row level security from the start), one row per organisation per kind
(`CHAT_WEBHOOK` first). The secret is stored only as ciphertext (`config_encrypted`). Beside it live
non-secret facts the page can show: a `hint` (the host and the last few characters), the last test's
status and time, and a short error reason.

**Encryption.** Fernet (authenticated AES) from the `cryptography` library, which production already has
through the sign-in library. The key is `CONNECTIONS_KEY`, set once by the operator as a server secret; a
comma-separated list is accepted so a key can be rotated (the first encrypts, all decrypt). **With no key
the feature is switched off**: saving returns a clear 503, and nothing is ever stored in plain text.

**The secret is write-only.** No endpoint returns it. The page shows "connected, ending ...a1b2" and
offers Replace and Remove. It is never written to the audit log, a log line, an error message or a test
result. Decryption happens only where the message is sent.

**Who.** Only an organisation admin can see or change connections. Another organisation's rows are a 404.

**Where a message goes.** For an organisation with a `CHAT_WEBHOOK` connection, its alerts and its weekly
report go there. Otherwise the server-wide `NOTIFY_WEBHOOK_URL` still applies (unchanged, so existing
deployments keep working). One organisation's alert never reaches another's channel.

**Server-side request forgery.** Anything a customer can type that the server then calls is an attack
surface (an address inside the network, or a cloud metadata address). Slice 1 removes the risk by
construction: the webhook must be `https` on an allow-listed host (`discord.com`, `discordapp.com`,
`hooks.slack.com`) with the expected path, so a customer cannot aim the server anywhere else. Calls use a
short timeout and never follow redirects. Slices that accept a free-form URL (evidence collectors) must add
a resolver that refuses private, loopback, link-local and metadata addresses, and re-check it at send time;
that is their ADR addendum, not an afterthought.

**Test.** A Test button sends a one-line message and records OK or the failure reason (the HTTP status,
never the response body). A connection that has never been tested reads "untested".

**Audit.** Setting, replacing, removing and testing a connection are audit events with who, when and the
result, and no secret.

## Slices
1. Chat webhook (Discord or Slack): this change.
2. Evidence collectors (AWS, Microsoft 365, GitHub, HR): URL plus token, with the SSRF resolver and a
   per-organisation sync.
3. The scheduled jobs move into the app, so there is no second copy of any setting.

## Consequences
- The operator sets one secret, `CONNECTIONS_KEY`, once. Losing it makes saved connections unreadable (they
  must be pasted again), which is the safe failure.
- A chat message can still carry what the product puts in it: the "task assigned" alert names the assignee's
  email (ADR-031 and a deliberate choice), so the destination channel should be the organisation's own.
- Rotating a webhook means pasting the new one; there is no history of old values.
