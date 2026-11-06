# ADR-049: AWS evidence arrives from the customer's own script

Status: accepted. Supersedes ADR-048. Builds on ADR-044 and ADR-045. Part of issue #79.

## Context
ADR-048 had the platform assume a read-only role in each customer's AWS account. That needs the platform to hold its own
AWS identity, which means an AWS account with billing. The operator cannot set that up, and the design also made one
credential able to reach every connected customer.

## Decision
- **The platform holds no AWS identity and calls nothing in AWS.** The customer runs one small read-only script
  (`app/collectors/aws_readonly.py`, standard library plus `boto3`, runnable on its own) in their own account. It runs the
  four checks and uploads four yes/no answers.
- **An upload token** authenticates the upload. Only an organisation admin can create it. It is shown once. It has the
  form `<organisation id>.<secret>`: the organisation id (not secret) lets the server select the tenant before reading
  anything, and only the SHA-256 of the secret is stored, compared in constant time. Making a new token ends the old one
  at once. Removing the connection ends it too.
- **`POST /ingest/aws` accepts almost nothing.** Four named yes/no attributes and a short completeness note; unknown
  fields are dropped; bodies over 20 KB are refused; at most one upload per 30 seconds per organisation. Every failure to
  authenticate gives the same answer (401), whether the organisation, the secret or the connection is wrong.
- The upload goes through the same storage, completeness rules (ADR-030), evaluation and audit as a pulled collector.
  A check the script could not run is left out and reported, so the run is incomplete, never a pass or a failure.
- ADR-048's role-based endpoints were removed before use.

## Consequences
- Evidence is as fresh as the customer's last run; the Collect button explains this rather than pretending to pull.
  Scheduling the script (cron, a CI job) is the customer's choice.
- A customer's token can only add AWS evidence for its own organisation. It cannot read anything.
- The script runs with the customer's own credentials and the permissions they choose; the page lists the eleven
  read-only permissions the four checks need.
- Microsoft 365 and HR can use this same upload pattern where a hosted-API connection is not practical.

## Amended 2026-11-06 after an adversarial review
- **The body cap is now enforced on what arrives.** The token is checked first and the body is then read as a stream and
  refused (413) once it passes 20 KB, so an anonymous caller cannot make the server buffer a large request, and a chunked
  request with no Content-Length is capped too. Earlier wording ("bodies over 20 KB are refused") was true only for callers
  who declared a length.
- **A missing or malformed completeness declaration is never read as complete.** An upload that does not say so is
  incomplete.
- **Checks tightened:** existing unencrypted EBS volumes fail encryption; admin group members are read across all pages; a
  backup plan with no selections does not count; no administrators found is unknown, not a pass.
- **Scripts:** refuse an `http://` address (other than this computer), never follow a redirect, take the token from the
  environment in the documented examples, and exit 4 when the server cannot be reached.
- Not changed, on purpose: the region the script assessed is not shown next to a pass (one region per run is documented),
  and the check covers one region per run.
