# ADR-050: Microsoft 365 evidence arrives from the customer's own script

Status: accepted. Applies ADR-049 to Microsoft 365. Part of issue #79.

## Context
The Microsoft 365 evidence source needs two attributes: administrators have multi-factor authentication, and access
logging is on. Pulling them ourselves would need the platform to hold a credential for every customer's tenant. ADR-049
already settled the pattern for AWS: the customer runs a read-only script and uploads yes/no answers.

## Decision
- Same upload token, same strict ingest (`POST /ingest/m365`), same size and rate limits. The connection and the token
  are per source, so a Microsoft 365 token never works for AWS, and the reverse. Each source accepts only its own named
  attributes, taken from the connector registry, so a new upload source needs one line in `PUSH_KINDS`.
- The script is `app/collectors/m365_readonly.py`, standard library only. It uses a read-only app registration in the
  customer's own Entra tenant (client credentials, `AuditLog.Read.All`), or a Graph token they already have.
- **privileged_access_mfa:** every account Graph marks as an administrator (`userRegistrationDetails`, `isAdmin eq true`)
  has registered multi-factor authentication. If Graph returns no administrators, the check is reported as unknown, not
  as a pass.
- **access_logging_enabled:** the directory audit log has recorded at least one event in the last 30 days.

## Limits, stated plainly
- The audit check shows that the Entra audit log is available and active. It does **not** read the Microsoft Purview
  "unified audit log" setting, which is not exposed through Graph. A tenant with no directory changes at all in 30 days
  would read as false; the run note and this record say so.
- MFA registered is not MFA enforced: a conditional-access policy decides enforcement. This evidences registration.
- A check the app registration may not run is left out and the run is incomplete, never a pass or a failure.

## Consequences
- No Microsoft account, key or billing is needed on the platform side.
- Evidence is as fresh as the customer's last run; scheduling is theirs.
