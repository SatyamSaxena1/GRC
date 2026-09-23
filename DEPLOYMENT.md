# Deployment / rebuild guide

How to stand this project up on a fresh machine. Two paths: **all-in-Docker**
(one command, self-contained) or **app on a host + hosted Postgres** (Supabase).

---

## Path A — everything in Docker (recommended for a rebuild)

### Prerequisites
- Docker Engine + Compose v2 (`docker compose version` ≥ 2.x)
- ~15 GB free disk (base images + the `qwen2.5vl:7b` model ≈ 6 GB)
- Optional: NVIDIA GPU + `nvidia-container-toolkit` for fast inference

### Run
```bash
git clone https://github.com/SatyamSaxena1/GRC && cd GRC
docker compose up            # first run; add --build after later pulls
```

### What happens on first `up`
1. `postgres`, `minio` start; `createbuckets` makes the `grc-evidence` bucket.
2. `ollama` starts; `ollama-pull` downloads `qwen2.5vl:7b` into the
   `ollama-models` volume, then exits. **This is the slow step (~6 GB).**
3. `app` builds (SPA + API), waits for the above, runs `alembic upgrade head`
   from `docker/entrypoint.sh`, then serves on **http://localhost:8000**.

Later runs skip the download and the build cache makes them quick.

### Verify
```bash
curl localhost:8000/health/ready          # {"ready": true, "checks": {...}}
curl localhost:8000/                        # HTML (the SPA)
docker compose run --rm app python -m demo  # full slice, prints each step
```

### GPU
Edit `docker-compose.yml`, uncomment the `deploy:` block on the `ollama`
service, then `docker compose up -d ollama`. Without it, inference is CPU-only:
the app still works but extraction takes minutes per document, and if the model
is unreachable it degrades to null-field extraction (never a false pass).

### Optional: real OIDC auth
```bash
docker compose --profile oidc up          # also starts Authentik + redis
```
Then finish setup at http://localhost:9002/if/flow/initial-setup/, create an
OAuth2/OIDC provider + application, and set `OIDC_ISSUER` / `OIDC_AUDIENCE` /
`OIDC_JWKS_URL` on the `app` service. See
[docs/adr/011-oidc-auth.md](docs/adr/011-oidc-auth.md).

### Reset
```bash
docker compose down -v        # also drops the DB, storage, and model volumes
```

---

## Path B — app on a host, Postgres on Supabase

Use when you want the database managed and the app running on a PaaS
(Fly / Railway / Render / a VM).

### 1. Database
The schema and RLS are already applied to the Supabase project. To rebuild on a
new Supabase project:
```bash
export DATABASE_URL='postgresql+psycopg://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres'
alembic upgrade head
```
Use the **session pooler (port 5432)**, not the transaction pooler (6543).
Then create the non-superuser runtime role (it holds a password, so it is not in
a migration) — run in the Supabase SQL editor:
```sql
CREATE ROLE grc_app LOGIN PASSWORD '<choose-one>' NOBYPASSRLS;
GRANT USAGE ON SCHEMA public TO grc_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO grc_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO grc_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO grc_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO grc_app;
GRANT grc_app TO postgres;
```
Migrations use the `postgres` URL (it can alter schema); the **app** uses the
`grc_app` URL (it cannot, so RLS policies actually apply):
```
postgresql+psycopg://grc_app.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

### 2. App
The same `Dockerfile` works as the deploy artifact. Set on the host:

| Env var | Value |
|---|---|
| `DATABASE_URL` | the `grc_app` session-pooler URL |
| `STORAGE_BACKEND` | `s3` |
| `S3_BUCKET` / `S3_ENDPOINT_URL` / `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION` | any S3-compatible store (AWS S3, Cloudflare R2, or Supabase Storage's S3 endpoint `https://<ref>.supabase.co/storage/v1/s3`) |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` / `OLLAMA_VISION_MODEL` | a reachable Ollama, or leave unset for null-field extraction |
| `CORS_ORIGINS` | empty if the SPA is served by the same container; otherwise the SPA's origin |

The image runs `alembic upgrade head` on start — point `DATABASE_URL` at the
**`postgres`** URL for that step (a release command) and switch the running
process to `grc_app`, or run migrations manually before deploy.

### 3. Evidence storage
Local disk does not survive a container restart on a PaaS — `STORAGE_BACKEND=s3`
is required for Path B. `app/storage.py` already speaks the S3 API.

---

## Path C: Render + self-hosted GPU LLM (public deploy)

`render.yaml` is a Blueprint for the web service, Postgres 16 and the two monitor
crons (Singapore region). The LLM cannot run on Render (no GPUs): stand it up
first from `deploy/llm/` (Ollama behind a bearer-token proxy), then:

1. Create a Render environment group `grc-secrets` with the values listed at the
   top of `render.yaml` (never commit them).
2. Apply the Blueprint. The pre-deploy step runs `alembic upgrade head` with the
   owner URL (`MIGRATION_DATABASE_URL`); the running app uses `DATABASE_URL`.
3. Create the `grc_app` role (SQL in Path B, step 1), put its URL in
   `grc-secrets` as `DATABASE_URL`, redeploy, then restrict the database's
   `ipAllowList`.
4. The service runs with `AUTH_STUB_ENABLED=false`: sign-in is OIDC only, and the
   `/admin/*` bootstrap routes need an `X-Admin-Key` header (`ADMIN_API_KEY`).
   Provision orgs, firms and users with `curl`/a script — the SPA's in-app Admin
   page sends no key, so it does not work against a production deploy.
5. Keep `numInstances: 1`: SSE and upload background tasks are in-process.

## Continuous integration / image publishing

`.github/workflows/ci.yml` runs the backend test suite (`pytest`) and the
frontend build (`tsc -b && vite build`) on every push and pull request.

`.github/workflows/publish.yml` builds the same `Dockerfile` used above and
pushes it to `ghcr.io/<owner>/<repo>` on every push to `main` (tag `latest`)
and on version tags (`v*`, tagged with the tag name). It stops at "image is
published" — pulling and running that image on a target host (Fly/Railway/
Render/a bare VM, per Path B above) remains a manual step until a target host
is chosen.

## Periodic DPDP jobs (connector sync, breach/DSR deadline sweep)

Nothing re-runs on its own (see `app/monitor.py`'s docstring and ADR-006) —
connectors only sync when someone clicks "Collect evidence", and breach/DSR
deadlines are only checked when something calls `GET /analytics/attention` or
`/notifications`. Two `python -m app.monitor` modes cover recurring work; run
them from cron or Task Scheduler rather than adding a scheduler dependency:

```bash
# Every 6 hours: sync every org's configured, in-scope DPDP connectors
# (AWS/M365/Google Workspace/HRMS) and print the same attention report
# app.monitor's default mode prints (evidence expiry/stuck jobs plus breach
# and DSR deadlines) — exit code is non-zero if a connector failed to sync.
0 */6 * * * cd /opt/grc && .venv/bin/python -m app.monitor --sync-connectors >> /var/log/grc-monitor.log 2>&1

# Daily: the plain attention report (expiry, stuck jobs, breach/DSR deadlines),
# non-zero exit if anything needs a human — wire into your alerting the same
# way as any other cron job's exit code.
0 7 * * * cd /opt/grc && .venv/bin/python -m app.monitor >> /var/log/grc-monitor.log 2>&1
```

Windows Task Scheduler equivalent:

```bash
schtasks /create /tn "GRC DPDP Sync" /tr "C:\opt\grc\.venv\Scripts\python.exe -m app.monitor --sync-connectors" /sc hourly /mo 6
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `exec /entrypoint.sh: no such file or directory` | CRLF line endings. `.gitattributes` prevents this; if you edited the file on Windows, re-save as LF. |
| `app` exits immediately, logs show `alembic ... could not connect` | Postgres not ready yet, or wrong `DATABASE_URL`. Compose waits on health; for Path B check the pooler host/port. |
| `ollama-pull` hangs or fails | No network, or disk full. Re-run `docker compose up ollama-pull`. The volume caches a partial download. |
| Extraction returns all `null` | Model unreachable or still downloading. `curl localhost:11434/api/tags` should list `qwen2.5vl:7b`. Not fatal — verdicts still compute. |
| `new row violates row-level security policy` (Path B) | The app is connecting as a role with `BYPASSRLS` off but no tenant GUC set — this only happens on admin/bootstrap endpoints. Run those with the `postgres` URL, or see `app/db.py` `set_tenant`. |
| SPA loads but every API call 401/422 | No identity. In dev, sign in with a bootstrap token (`org:<id>`); see [frontend/README.md](frontend/README.md). |
| Port 8000 / 5432 / 9000 already in use | Another stack is running. `docker compose down` it, or remap ports in `docker-compose.yml`. |

## Related docs
- [README.md](README.md) — what the product does and why
- [CONTRIBUTING.md](CONTRIBUTING.md) — codebase map for making changes
- [docs/adr/](docs/adr/README.md) — the architecture decisions behind all of the above
