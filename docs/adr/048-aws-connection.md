# ADR-048: An organisation connects its own AWS account

Status: **superseded by ADR-049** (the operator could not set up an AWS account for the platform, so the role-based
design below was replaced before it was ever used; kept for the reasoning). Builds on ADR-044 (connections) and ADR-045 (GitHub connection). Part of issue #79.

## Context
The AWS evidence source (`AWS_SNAPSHOT`: encryption at rest, privileged-access MFA, access logging, backups) is
read from an external collector at a platform-wide URL. There is no collector code in this repository, so a customer
cannot connect their own AWS account without an operator building and hosting one. `boto3` is already a dependency
(for evidence storage).

## Decision (proposed)
- A third connection kind, `AWS_READONLY`, holding what the customer chooses to share, encrypted and write-only as
  before.
- **Preferred access method: cross-account role.** The customer creates a read-only IAM role in their account that
  trusts the platform's AWS account, with an **external ID** we generate for them (this prevents a third party from
  tricking the platform into using someone else's role). They paste only the role ARN and a region. No long-lived
  customer secret is stored at all.
- **Fallback: a read-only access key pair**, stored encrypted, for customers who cannot create a role. Higher risk,
  so off unless the operator enables it.
- **Fixed endpoints only.** The server calls AWS service endpoints through the SDK. The customer supplies a role ARN
  matching `arn:aws:iam::<12 digits>:role/<name>` and a region from a fixed list, never a URL, so no
  outbound-request-forgery resolver is needed.
- **Four read-only checks**, each one a documented API call, mapped to the existing attributes: S3 default
  encryption and EBS/RDS encryption (`encryption_at_rest`), MFA on IAM users with admin rights
  (`privileged_access_mfa`), a multi-region CloudTrail trail that is logging (`access_logging_enabled`), and AWS
  Backup plans or automated RDS backups (`backup_enabled`). Counts and yes/no only; no resource names are stored.
- Runs in the background like the GitHub collection, retried on transient errors, judged by the same completeness
  rules (ADR-030). A permission the role lacks is reported as an incomplete run, never as a pass.
- A "Check access" button asks AWS to assume the role and lists any permission that is missing.

## What this needs from the operator
The platform must have its **own AWS identity** to assume customers' roles (an IAM user or role in the operator's
account, with `sts:AssumeRole` only). Its credentials are server settings, like the Auth0 ones. This is the main
decision: it makes the platform hold one AWS credential that can reach every connected customer's read-only role.

## Consequences
- Each customer's exposure is limited to the read-only permissions they grant and can revoke by deleting the role.
- A compromise of the platform's AWS identity would expose every connected customer's read-only data, so that
  identity must be narrowly scoped, rotated, and never reused for storage.
- Microsoft 365 and HR follow the same pattern with their own fixed hosts.

