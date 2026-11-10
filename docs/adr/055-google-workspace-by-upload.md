# ADR-055: Google Workspace evidence arrives from the customer's own script

Status: accepted. Applies ADR-049 and ADR-050 to Google Workspace. Part of the roadmap item "Google Workspace, GCP,
Okta, Jira, Slack via the customer-run script pattern".

## Context
The Google Workspace evidence source (`GOOGLE_WORKSPACE_SNAPSHOT`, read by the DPDP "Rule 6 - Google Workspace baseline"
clause) needs two attributes: administrators have 2-step verification, and access logging is on. Most Indian startups
run Google Workspace. Pulling the facts ourselves would need the platform to hold a credential for every customer's
Workspace. ADR-049 and ADR-050 settled the pattern: the customer runs a read-only script and uploads yes/no answers.

## Decision
- Source key `google-workspace` (it was already in the connector registry), connection kind `GOOGLE_WORKSPACE_PUSH`, one
  line in `PUSH_KINDS`. Same upload token, same strict ingest (`POST /ingest/google-workspace`), same size and rate limits,
  per-source token and attributes. No clause or content change: the existing DPDP clause already reads the snapshot.
- The script is `app/collectors/gworkspace_readonly.py`, standard library only. It calls the Admin SDK Directory and
  Reports APIs read-only, with the scopes `admin.directory.user.readonly` and `admin.reports.audit.readonly`.
- **Sign-in:** an OAuth client in the customer's own Google Cloud project (refresh token), or a short-lived access token.
  A service account with domain-wide delegation is not supported: signing its JWT needs RS256, which the standard library
  does not have, and one dependency-free file is the point of this pattern.
- **privileged_access_mfa:** every active super administrator (`isAdmin`) has `isEnforcedIn2Sv`. If Google returns no
  active super administrators, the check is reported as unknown, not as a pass.
- **access_logging_enabled:** the admin audit activity feed has at least one event since 30 days ago.
- The script never follows a redirect (all of its requests, including to Google), refuses a non-https server address,
  reads the upload token from `GRC_UPLOAD_TOKEN`, and exits 4 when the server cannot be reached.

## Limits, stated plainly
- Super administrators only; delegated administrators are not checked. Suspended ones are ignored.
- Enforced means Google's flag on the account, not a statement about which second factor is used.
- The audit check shows the admin log is active; a Workspace with no admin changes in 30 days would read as false.
- A check the sign-in may not run is left out and the run is incomplete, never a pass or a failure.

## Consequences
- No Google account, key or billing is needed on the platform side.
- Evidence is as fresh as the customer's last run; scheduling is theirs.
- A customer who wants a service account needs a follow-up (a script variant that may use a library).
