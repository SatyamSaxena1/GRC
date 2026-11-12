# ADR-067: Hide the interactive API pages in production

**Status:** Accepted
**Date:** 2026-11-12
**Deciders:** Platform owner

## Context
The readiness check (docs/product/soc2-readiness.md) found that the live site served `/docs`, `/redoc` and `/openapi.json` to
anyone. They list every route and load scripts from a CDN, so they also showed up as Content-Security-Policy reports (ADR-066).

## Decision
- When stub auth is off (production), the app does not serve those three pages. `API_DOCS=on` brings them back for a
  debugging session. The local stub-auth setup keeps them.
- `scripts/smoke_live.py` read `/openapi.json` to check a deploy carries the newest routes. With the list hidden, and the
  web-app fallback answering 200 for unknown paths, it now checks that `/findings` refuses an anonymous caller (401, 403 or 422: the live API answers 422 for a missing Authorization header).
  That is weaker: it proves the API is there, not that every new route is.

## Consequences
- Anyone who needs the route list reads the code or runs the app locally.
- Hiding the list is not a lock: every route still needs sign-in. It only stops handing out a map.
