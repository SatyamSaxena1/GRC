# GRC frontend

A React + TypeScript SPA over the FastAPI backend in `../app`. Built against the
endpoints that exist today (see `docs/frontend-integration-blueprint.md` at the repo
root for the screen-by-screen mapping this follows) — no screen here calls an endpoint
that isn't real.

## Run it

```bash
# backend, from the repo root
uvicorn app.main:app --reload

# frontend
cd frontend
npm install
npm run dev          # http://localhost:5173
```

The dev server proxies every backend path (`/admin`, `/evidence`, `/controls`, `/gaps`,
`/tasks`, `/audit`, `/analytics`, `/health`) to `http://localhost:8000`, so there's no
CORS configuration to touch on the backend.

By default the backend identifies a caller by a raw `org:<id>` / `user:<id>` /
`auditor:<engagement_id>` token (see `app/auth.py`). The **Quick start** tab on the
sign-in screen creates a demo organisation, audit firm and engagement in one step and
signs you in as that organisation; the other tabs let you sign in with an id you
already have (paste an engagement id to act as the auditor on the same data).

A **Single sign-on** tab appears once an identity provider is configured (see
`docs/adr/011-oidc-auth.md`) via these build-time env vars (e.g. in `frontend/.env.local`):

```
VITE_OIDC_AUTHORIZE_URL=http://localhost:9002/application/o/authorize/
VITE_OIDC_TOKEN_URL=http://localhost:9002/application/o/token/
VITE_OIDC_CLIENT_ID=<the OAuth2 client id from Authentik>
VITE_OIDC_REDIRECT_URI=http://localhost:5173/oidc-callback   # optional, this is the default
```

Both paths work at once — nothing above disables the raw-id tabs.

For a fuller synthetic workload that exercises list density, assignments, role scoping,
evidence processing, gaps and tasks through the real API:

```bash
python scripts/seed_load.py
# or: python scripts/seed_load.py --documents 25 --controls 80 --users 5
# add --wait when you want the command to wait for document analysis
```

The command prints organisation, control-owner and auditor ids for the sign-in screen.
All generated names, users and documents are synthetic; no customer data is copied from
the reference portal.

## Layout

| Path | What it does |
|---|---|
| `src/api/client.ts` | The only place that knows the backend's URLs and response shapes |
| `src/lib/session.tsx` | Current identity (org/user/auditor/oidc), persisted in localStorage |
| `src/lib/pkce.ts` | The OIDC Authorization Code + PKCE redirect, for the SSO tab |
| `src/lib/useApi.ts` | One loading/error/data hook, reused by every page |
| `src/components/DataTable.tsx` | The shared table behind Controls, Gaps and Tasks |
| `src/pages/` | One file per screen |

## Known gaps (backend, not frontend)

- No control-level compliance/maturity score, no risk register, no vendor module, no
  policy lifecycle — these mirror the gaps already tracked in the backend's own
  `docs/adr/` and README "Known limitations". Verified against a live run of the
  reference product this frontend takes its interaction patterns from: none of these
  four are actually functional there either (risk register link 404s, vendor/TPRM and
  policy lifecycle are unwired category placeholders), so there is nothing to catch up
  to — building them now would be inventing screens for backend domains that don't
  exist yet, not closing a gap the reference proves is real.
