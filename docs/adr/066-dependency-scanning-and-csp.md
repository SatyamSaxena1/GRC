# ADR-066: Dependency scanning, weekly updates, and a Content-Security-Policy in report-only mode

**Status:** Accepted
**Date:** 2026-11-12
**Deciders:** Platform owner

## Context
The readiness check for our own SOC 2 (docs/product/soc2-readiness.md) found that nothing in CI looked for known-vulnerable
packages, and that the site had no Content-Security-Policy. A strict policy written blind can break the sign-in page, so it
could not simply be switched on.

## Decision
**Scanning** (`.github/workflows/security.yml`)
- Python: `pip-audit` over a fresh install of the project (82 packages, no advisories today). Any advisory fails the job.
- Frontend: `npm audit --omit=dev --audit-level=high` over the packages that ship to the browser. High or critical fails.
  Build tools (`vite`, `esbuild`) are reported but do not fail it: they never reach a customer. Today that leaves `vite`
  (fix needs a major upgrade) and two moderate `react-router` advisories that also need a major upgrade; both are tracked.
- Runs weekly, on demand, on main, and on a pull request only when a dependency file changed, so an unrelated change is not
  held up by a new advisory. It is not added to the branch ruleset's required checks.
- Dependabot opens grouped weekly update pull requests for pip, npm, GitHub Actions and Docker, capped at a few; a person
  merges each after the same tests and gate as any change.
- The lock file's `source-map-js` is updated to its fixed version.
- **First run:** it failed on `setuptools 79.0.1` (three advisories; fixes in 83 and 84), a build tool that ships pre-installed
  on GitHub's Python runner, not one of our dependencies. The scan now upgrades pip, setuptools and wheel first, then audits
  what the project pulls in. **The production image is probably the same:** `python:3.11-slim` likely carries an older
  setuptools, which is unused at runtime but is shipped. I did not check the exact version, and upgrading it in the
  `Dockerfile` (one line) is left for a change that can be verified with a real image build, because Render builds that file
  on every deploy.

**Content-Security-Policy** (`app/csp.py`)
- Sent as `Content-Security-Policy-Report-Only` by default, so nothing can break. `CSP_MODE=enforce` makes it enforcing;
  `off` removes it.
- Written from what the app loads: its own scripts, styles (inline allowed, because React writes style attributes), images
  (own, `data:`, `blob:`), same-origin frames, and one outside connection, the sign-in provider's token address, taken from
  `VITE_OIDC_TOKEN_URL`. Scripts are strict: no inline and no `eval`. `object-src 'none'`, same-origin `base-uri` and
  `form-action`.
- Violations go to `POST /csp-report`, which is public because a browser sends it with no credentials. It reads at most 8 KB,
  keeps only the directive, what was blocked and the page's path (never the query string), clips and flattens each field so a
  forged report cannot write a fake log line, and logs at most 30 a minute.

## How it was checked
The built app has no inline scripts or styles and no `eval`. Headless Chrome against the sign-in, pitch and guided-demo pages
produced no violations. To show a violation would be noticed, Chrome was pointed at the API docs page, which loads from a
CDN: it reported all five and the server logged them cleanly.

## Consequences
- **Enforcing comes later.** Leave it in report-only until a quiet week of real traffic, then set `CSP_MODE=enforce`.
- The API docs pages (`/docs`, `/redoc`) are public on the live site and load scripts from a CDN, so they will show in the
  reports under `page=/docs`. They are not part of the app. Switching them off in production is a separate change, because
  `scripts/smoke_live.py` reads `/openapi.json`.
- The failure and logging limits live in the process, which suits the one-instance design.
