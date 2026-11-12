# ADR-065: Standard security headers, and a limit on wrong operator keys

**Status:** Accepted
**Date:** 2026-11-12
**Deciders:** Platform owner

## Context
A readiness check against SOC 2 and ISO 27001 for the platform itself (docs/product/soc2-readiness.md) found two cheap,
real gaps on the live site. It sent none of the standard browser security headers, and a caller could try operator keys
as fast as they liked: eight wrong keys in a row all got a plain 401 and no limit.

## Decision
- **Headers on every response:** `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`,
  `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy` denying camera, microphone and location, and
  `Strict-Transport-Security` for a year, only on a request that arrived over https. A header a route already set is kept.
  `SAMEORIGIN` and the permissions list were checked against the app: every frame is the app framing itself (the pitch
  page and the document viewer), and nothing uses the camera, microphone or location.
- **No Content-Security-Policy yet.** The 3D sign-in page and inline styles need a policy written and run in
  report-only mode first, or it would break the page. It is the next step, not a decision to skip it.
- **Operator key:** ten wrong keys from one address within five minutes, and further attempts from it are refused with
  429 and `Retry-After` before the key is even compared, so guessing faster gains nothing. A right key clears that
  address's count. The address is `cf-connecting-ip` (set by Cloudflare) or the connection's own; `x-forwarded-for` is
  never used, because a caller can write it.

## Consequences
- The count lives in the process, which suits the one-instance design (app/events.py). If the app ever runs on more than one
  instance it needs a shared store.
- Someone who mistypes the operator key ten times is locked out of that address for five minutes. That is intended.
- Not covered: limits on other endpoints, and on signed-in callers. Sign-in itself is Auth0's, which has its own protections.
