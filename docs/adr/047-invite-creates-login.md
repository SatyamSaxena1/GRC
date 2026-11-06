# ADR-047: Inviting someone also creates their login, without anyone choosing their password

Status: accepted. Builds on ADR-011 (sign-in by email match) and ADR-036 (team management). Closes the plan for issue #81.

## Context
Inviting a user only wrote our own `users` row. Passwords live in the sign-in service (Auth0), and nobody could sign in
until someone separately created a login with the same email.

## Decision
- **Off unless configured.** With `AUTH0_DOMAIN`, `AUTH0_M2M_CLIENT_ID` and `AUTH0_M2M_CLIENT_SECRET` all set (a
  machine-to-machine application with `create:users`, `read:users`, `update:users`, `create:user_tickets`), an invite
  also prepares the login. Without them, behaviour is exactly as before.
- **Login first, row second.** If the sign-in service fails, the invite fails (HTTP 502) and no half-invited person
  is left behind. An existing login for that email is reused, never overwritten.
- **Nobody chooses or sees a password.** The new login gets a random password nobody knows, and the admin receives a
  one-time password-change link, valid seven days. The person sets their own password from it.
- **The link is a credential.** It is returned once in the invite response with `Cache-Control: no-store`, shown once
  on the page, and never stored, logged or put in the audit trail.
- **Deactivating also blocks the login**, and reactivating unblocks it. Our own check already ends access at the next
  request, so a failure to block is recorded in the audit event (`login_block_error`) and does not stop the
  deactivation.
- The management client calls only the configured Auth0 domain (a plain hostname is required), never follows a
  redirect, has a 10-second timeout, caches the management token until just before it expires, and reports only a
  short reason, never a body, token or link.

## Consequences
- The first release is link-only. An admin-typed starting password was considered and left out.
- The operator enters the three settings on the server. They are secrets and are not committed.
- If Auth0 and our row ever disagree (a login created outside the app), the next invite reuses it and the next
  deactivation blocks it.
