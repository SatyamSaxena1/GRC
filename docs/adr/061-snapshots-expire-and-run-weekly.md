# ADR-061: A script's snapshot counts for 30 days, and a template runs the scripts every week

**Status:** Accepted
**Date:** 2026-11-11
**Deciders:** Platform owner

## Context
Competitor research (November 2026) found that the leaders keep customers by re-checking their systems all the time,
so a control stays green only while it is still true. Our AWS, Microsoft 365, Google Workspace and HR checks run as
scripts in the customer's own account (ADR-049, ADR-050, ADR-055), and we hold none of their keys. That stays. But a
snapshot never aged: an AWS upload from six months ago still passed every rule it fed, and running the scripts again
was left to memory.

## Decision
- **Every rule fed by a script snapshot (AWS, Microsoft 365, Google Workspace, HR; 16 requirements) has
  `evidence_validity: {issued_attribute: collected_at, max_age_days: 30}`.** After 30 days the snapshot reads STALE and
  the clause FAILs, exactly as an expired policy does, until the script runs again.
- **`collected_at` is the UTC day the server received the upload** (`routers/connectors._snapshot`), never a value the
  customer's script supplies.
- The limit is `required: false`: a snapshot stored before this change has no `collected_at` and is judged as before,
  rather than every existing customer failing at once. Its next upload carries the date.
- **A GitHub Actions template** (`deploy/evidence-schedule/grc-evidence.yml`) runs the three cloud scripts every Monday
  in the customer's own GitHub account, with their own keys (AWS through GitHub OIDC, no stored AWS key). It fetches the
  scripts at a commit the customer pins after reading them, never at a moving branch. The HR check reads lists exported
  by hand and stays manual.
- **The Connections page** says each upload counts for 30 days, links the template, warns from 14 days (when the weekly
  digest also calls the source quiet, ADR-058), and says plainly from 30 days that the answers no longer count.

## Consequences
- Stored verdicts are still frozen at upload (app/monitor.py): readiness, the attention report and the weekly digest
  show a stale snapshot, and nothing silently flips a locked verdict.
- The 16 requirements' rule hashes change, so their existing verdicts are marked "rules changed since" until the next
  upload. That is true: the rule did change.
- Change-control (GitHub, GitLab, Bitbucket) and key-health snapshots are pulled by our own server on a schedule and are
  not covered here.
