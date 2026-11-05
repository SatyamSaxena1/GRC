# Connecting customers' AWS accounts (ADR-048)

Two sides: the **operator** gives the platform one narrow AWS identity, once. Each **customer** creates a read-only role
that trusts it. The Connections page shows the customer their own trusted identity and external ID.

## Operator, once

1. In **your own AWS account**, create an IAM user `grc-platform` with **no console access** and no other permissions
   than this inline policy. It can only ask to assume a role; it cannot read anything itself.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": "sts:AssumeRole", "Resource": "arn:aws:iam::*:role/*" }
  ]
}
```

2. Create an access key for that user.
3. In Render, in the `grc-secrets` environment group, add:

| Name | Value |
|---|---|
| `AWS_PLATFORM_PRINCIPAL_ARN` | the user's ARN, e.g. `arn:aws:iam::<your account>:user/grc-platform` (not secret) |
| `PLATFORM_AWS_ACCESS_KEY_ID` | the access key ID |
| `PLATFORM_AWS_SECRET_ACCESS_KEY` | the secret (enter it yourself; never in chat) |

These names differ on purpose from the evidence-storage keys (`AWS_ACCESS_KEY_ID`). **Never reuse a storage key
here.** This identity can reach every connected customer's read-only role, so rotate its key regularly.

## Customer, per account

Create an IAM role, type **Another AWS account**, trusting the identity shown on the Connections page, and require the
**external ID** shown there. Trust policy shape:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "AWS": "<the platform identity shown on the page>" },
    "Action": "sts:AssumeRole",
    "Condition": { "StringEquals": { "sts:ExternalId": "<the external ID shown on the page>" } }
  }]
}
```

Attach this read-only permissions policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "s3:ListAllMyBuckets", "s3:GetEncryptionConfiguration",
      "ec2:GetEbsEncryptionByDefault", "rds:DescribeDBInstances",
      "iam:GetAccountSummary", "iam:ListEntitiesForPolicy", "iam:GetGroup", "iam:ListMFADevices",
      "cloudtrail:DescribeTrails", "cloudtrail:GetTrailStatus",
      "backup:ListBackupPlans"
    ],
    "Resource": "*"
  }]
}
```

Then paste the role ARN and the region (where the databases and the logging trail live) on the Connections page and press
**Check access**. To stop all access later, delete the role.

## What is checked, and what a missing permission does
| Attribute | True when |
|---|---|
| `encryption_at_rest` | EBS encryption by default is on, every RDS instance is encrypted, and every S3 bucket has default encryption |
| `privileged_access_mfa` | the root account has MFA, and every IAM user with AdministratorAccess (directly or through a group) has an MFA device |
| `access_logging_enabled` | a multi-region CloudTrail trail exists and is logging |
| `backup_enabled` | an AWS Backup plan exists, or every RDS instance keeps automated backups |

A check the role is not allowed to run is **left out** and the run is marked incomplete. It is never counted as a failure
or a pass. One region is checked per connection; connect another account or region by replacing the details.
