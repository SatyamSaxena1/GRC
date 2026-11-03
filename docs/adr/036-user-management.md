# ADR-036: User management

Status: accepted

## Context
Access was granted with bootstrap forms keyed by UUID. An admin could not see who had access, change a
role, or remove someone; a leaver kept signing in. Sign-in matches a JWT's email to exactly one `users`
row, so a duplicate address would lock both people out.

## Decision
- `users.active` (additive migration, default true). Deactivation refuses sign-in at both identity
  lookups (stub `user:` and OIDC email), so a live session ends at its next request. The row stays: every
  past action still resolves to a name in the audit log.
- `GET /admin/users` lists the caller's own organisation (org admin) or firm (firm admin).
  `PATCH /admin/users/{id}` changes role and/or `active`. Row level security makes another tenant's user
  a 404.
- Guards: roles are checked against the user's side (org vs firm); the last active admin cannot be
  demoted or deactivated; nobody can deactivate themselves.
- Every change is `USER_UPDATED` in the audit chain with before and after; a no-op writes nothing.
- Pickers (`/tasks/owners`, `/firm/auditors`) list active users only.
- Email addresses are unique, case-insensitively, across all tenants (`409` on create).
- An org admin may invite without knowing their organisation id.

## Consequences
Deactivated users' tasks and ownerships are not reassigned automatically; the admin hands them over
with the existing bulk task and owner tools. A user-facing "who has access" export is not included.
