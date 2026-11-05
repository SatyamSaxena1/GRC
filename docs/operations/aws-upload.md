# Sending AWS evidence from your own account (ADR-049)

No AWS key of yours is shared with us, and we call nothing in your account. You run one small script and it uploads four
yes/no answers.

## One-time
1. Connections page, **AWS** card, **Create my upload token**. Copy it now; it is shown once.
2. Give whoever will run the script these read-only permissions (an IAM user, a role, or your own admin login):

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

3. Get the script: `app/collectors/aws_readonly.py` from the project repository. It needs Python 3 and `boto3`.

## Each time
```bash
python aws_readonly.py --url https://grc.blinkedit.me --region ap-south-1 --token "$GRC_UPLOAD_TOKEN" --dry-run
python aws_readonly.py --url https://grc.blinkedit.me --region ap-south-1 --token "$GRC_UPLOAD_TOKEN"
```
The first prints the answers and uploads nothing. Schedule the second (cron, a CI job) for regular evidence. Exit codes:
0 uploaded and complete, 1 refused, 2 no token, 3 uploaded but some check could not run.

## What is checked
| Attribute | True when |
|---|---|
| `encryption_at_rest` | EBS encryption by default is on, every RDS instance is encrypted, and every S3 bucket has default encryption |
| `privileged_access_mfa` | the root account has MFA, and every IAM user with AdministratorAccess (directly or through a group) has an MFA device |
| `access_logging_enabled` | a multi-region CloudTrail trail exists and is logging |
| `backup_enabled` | an AWS Backup plan exists, or every RDS instance keeps automated backups |

A check the permissions do not allow is left out and the run is marked incomplete. It is never a pass or a failure.
One region per run. A lost token is replaced, never read back; replacing it ends the old one.
