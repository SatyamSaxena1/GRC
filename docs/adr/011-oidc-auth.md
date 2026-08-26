# ADR-011: OIDC JWTs as a second, additive path into `_resolve()`

## Context
`app/auth.py`'s docstring already named this as deliberate stub-for-now:
"`app/authorization.py` holds the real rules and does not change when a proper IdP
replaces this." A real deployment (and giving CISO Assistant users real identity to
share via SSO, see ADR-010) needs that IdP now.

The obvious reading of "replaces this" is delete the stub and require a JWT. That
breaks every existing test and `demo/`, all of which authenticate with the literal
`org:<id>` / `user:<id>` / `auditor:<engagement_id>` tokens — dozens of call sites,
none of them incidental to what they're testing.

## Decision
Add OIDC JWT verification (`app/oidc.py`) as a second path `_resolve()` dispatches to,
selected by shape: three dot-separated segments (`token.count(".") == 2`) routes to
JWT verification, everything else falls through to the existing stub parsing
unchanged. A stub token can never collide with this — `org:<uuid>` contains no dots.

This keeps `_resolve()` the only thing that changes, as originally promised:
`Actor`, `current_actor()`'s RLS-binding, and all of `app/authorization.py` are
untouched. Tests and `demo/` keep working exactly as written; anything fronted by a
real IdP sends a JWT instead.

**Verification, not provisioning.** The JWT proves *who* (its signature, its `email`
claim) — it does not carry org/role/engagement scope. `_resolve_oidc()` looks the
user up locally by email and uses *our* `org_id`/`role`, the same way the `user:<id>`
stub path already does. Users are pre-provisioned via `POST /admin/users`; there is no
just-in-time account creation from an unrecognized JWT. Rejected the alternative
(trusting `org_id`/`role` as custom claims on the token): it would let anyone who can
get Authentik to mint a claim assign themselves an org, moving the security boundary
into IdP configuration instead of this app's own tables.

**Auditors need an engagement, and a JWT can't say which one.** An auditor's access is
scoped to one engagement at a time (see `app/authorization.py`'s
`assert_engagement_covers`); the stub token already encoded this directly
(`auditor:<engagement_id>`). A JWT authenticates the auditor, not their in-progress
engagement selection — that's a UI-level choice, not an identity fact. Added
`x-engagement-id` as a second header, required only when the resolved user's role is
`AUDITOR`, checked against that user's `audit_firm_id` before trusting it.

## Alternatives considered
- **Delete the stub, require JWTs everywhere.** Rejected: breaks the entire test suite
  and `demo/`, which are exactly the "runs without infrastructure" property the README
  advertises. Real auth should not cost that.
- **Trust `org_id`/`role` as JWT claims directly.** Rejected — see above; local lookup
  keeps this app's tables as the authorization source of truth, matching the existing
  `user:<id>` stub semantics exactly.
- **JIT-provision a `User` row from an unrecognized JWT.** Rejected as unnecessary
  scope: `/admin/users` is already the provisioning flow, and silently creating org
  members from IdP claims is a bigger trust decision than this ADR needs to make.

## Consequences
- `OIDC_JWKS_URL`/`OIDC_ISSUER`/`OIDC_AUDIENCE` unset (default) means `oidc.decode()`
  always 401s — the stub path is unaffected and remains the only path in dev/CI.
- A JWT's `email` claim must exactly match a provisioned `User.email`; no fuzzy
  matching, no case-folding beyond whatever the IdP normalizes.
- The frontend now sends two headers for an authenticated auditor session
  (`Authorization: Bearer <jwt>`, `x-engagement-id: <id>`) instead of folding both
  into one token string.
- **Trigger to revisit**: if a second IdP or multi-engagement-per-request need ever
  appears, `x-engagement-id` as a bare header is the thing to reconsider first.
