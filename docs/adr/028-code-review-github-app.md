# ADR-028: The code-review GitHub App — tenant binding, durable jobs, check outcomes

> **Status:** Proposed — a specification to agree **before** any of it is built. It follows a
> design review of the Phase 1b plan. That review found three gaps: the App bound tenants
> through a webhook-supplied id, ran reviews in a process-local background task, and left open
> what an incomplete review does to a merge. Each is settled here.

## Tenant binding
- **Connecting.**
  - An organisation admin, signed in to GRC, starts the connect flow. GRC stores a
    **single-use connect request**: a random nonce, the org, the admin and an expiry
    (10 minutes).
  - The admin installs the App on GitHub. GitHub redirects to the setup URL with
    `installation_id` and our `state` (the nonce).
  - GRC then checks three things:
    - the nonce exists, is unexpired and unused;
    - the signed-in admin is the one who started it;
    - **GitHub itself confirms the installation**: an App-JWT call to
      `GET /app/installations/{id}` returns it, and the account matches what the admin chose.
  - Only then does it write `github_installations(org_id, installation_id, account, ...)`. The
    callback alone, which anyone can forge, never binds anything.
- **Webhooks never authorise a tenant.**
  - After the HMAC check, the webhook handler looks the installation up through a single
    **trusted lookup**: a `SECURITY DEFINER` function that returns only `org_id` for an
    installation id.
  - It then binds the tenant with the existing `set_tenant(org_id)`.
  - Every review table keeps the strict tenant-only policy
    (`org_id = current_setting('app.tenant_id')`). There is no installation-scoped policy and
    no second route to tenant data.
- **Lifecycle events.** The App subscribes to *Pull request*, *Installation* and
  *Installation repositories* events.
  - Installation deleted or suspended: the binding is marked inactive and queued jobs are
    cancelled.
  - Repositories removed: their jobs are cancelled and future deliveries for them ignored.

  All of these are audit events.

## Durable jobs
- **Receiving a delivery.** The webhook handler does only this, in one transaction:
  1. verify `X-Hub-Signature-256`;
  2. insert the delivery id (unique; a redelivery is a no-op);
  3. resolve the tenant as above;
  4. upsert a `review_jobs` row;
  5. return 202.

  No diff is fetched and nothing is queued in memory.
- **Job identity is idempotent:** `(org, repo, pr, head_sha, standard_hash, engine_version)`
  is unique. A second delivery for the same state never runs a second review.
- **Rows carry no code:** ids, SHAs, status, attempt count, lease expiry, last error type.
- **A separate worker process** (a Render background worker, not the web service) claims jobs
  with `SELECT … FOR UPDATE SKIP LOCKED` and a lease of a few minutes. It retries with
  backoff, honouring GitHub's rate-limit headers, up to N attempts, then marks the job `error`.
- **Stale heads.** Before posting, the worker re-reads the PR head. If it has moved, the job
  is `superseded`: the check is completed as neutral, "superseded by a newer commit", never
  left in progress.
- **Logging.** The job runner logs exception type and location, never message bodies that
  could contain diff text. A test feeds a diff containing a fake secret through a failing job
  and asserts that the secret appears in no log record.

## Check outcomes
- **The check.** One check run, named exactly **`GRC code review`**, so branch protection can
  require it. Its conclusion follows the engine's review outcome (ADR-027) and the standard's
  `on_incomplete`:

  | Review outcome | `on_incomplete: warn` | `on_incomplete: block` |
  |---|---|---|
  | passed | success | success |
  | violated | failure | failure |
  | incomplete | neutral (title says what was not read) | failure |
  | error | neutral | failure |
  | job could not run (worker down, retries exhausted) | the check stays queued, then is completed as `neutral` (warn) or `failure` (block) by a sweeper after a timeout | |

- **Annotations:** rule, severity, action and message only (no code, no secret), at most 50
  per request, in batches.
- **Forks:** pull requests from forks are reviewed like any other, since the App reads the
  base repository's view of the PR. The check never exposes base-repository data to the fork.
- **Uninstall.** When the App is uninstalled while checks are open, the sweeper completes them
  as `neutral`, "GRC review disconnected", and the event is audited.

## Audit evidence
Each run records the following in `review_runs` and as a `CODE_REVIEW_RUN` event in the
tenant's chain:
- repository, PR, base and head SHAs;
- the standard version and hash;
- the engine version;
- the outcome, the findings hash and the check-run id.

This is **proof of execution** under a named standard. It is not proof of compliance, which
remains a judgement over the evidence (ADR-027: audit verification, not guaranteed replay).

## Delivery, in five milestones (each its own PR)
1. **ADR-026** (merged).
2. **ADR-027 and the deterministic engine:** standards, packs, outcomes and the try-it box.
3. **GitHub App and durable ingestion:** connect flow, trusted lookup, webhook, delivery
   dedupe, `review_jobs`, the worker, lifecycle events.
4. **Check runs and evidence:** outcomes to conclusions, annotations, superseding, the sweeper,
   `review_runs`, `review_findings` and the audit events.
5. **Dogfood and hardening:** installed on `SatyamSaxena1/GRC`. Replay recorded webhook
   deliveries in staging, kill the worker mid-job, uninstall with open checks, then roll back.

**Production-readiness gate.** Every PR in milestones 3 to 5 must clear this as well as green
CI:
- RLS tests for each new table;
- the migration applied and rolled back on a copy of production;
- recorded-delivery replay;
- a rollback note;
- an explicit deploy check.

**The end-to-end demonstration that closes milestone 5:**
1. A policy is published.
2. A PR violates it and the required check fails.
3. The corrected PR passes.
4. An auditor verifies, from the audit chain alone, which standard and engine version
   produced both outcomes.

## Out of scope until this lands
Model inference, fine-tuning, ReviewBench optimisation, analytics and PR triage.
