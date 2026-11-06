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
      "ec2:GetEbsEncryptionByDefault", "ec2:DescribeVolumes", "rds:DescribeDBInstances",
      "iam:GetAccountSummary", "iam:ListEntitiesForPolicy", "iam:GetGroup", "iam:ListMFADevices",
      "cloudtrail:DescribeTrails", "cloudtrail:GetTrailStatus",
      "backup:ListBackupPlans", "backup:ListBackupSelections"
    ],
    "Resource": "*"
  }]
}
```

3. Get the script: `app/collectors/aws_readonly.py` from the project repository. It needs Python 3 and `boto3`.

## Each time
```bash
export GRC_UPLOAD_TOKEN="<the upload token>"     # in the environment, not on the command line
python aws_readonly.py --url https://grc.blinkedit.me --region ap-south-1 --dry-run
python aws_readonly.py --url https://grc.blinkedit.me --region ap-south-1
```
The address must start with `https://` (the script refuses to send the token in clear) and a redirect is never followed.
The first prints the answers and uploads nothing. Schedule the second (cron, a CI job) for regular evidence. Exit codes:
0 uploaded and complete, 1 refused by the server, 2 missing token or an address that is not https, 3 uploaded but some
check could not run, 4 the server could not be reached.

## What is checked
| Attribute | True when |
|---|---|
| `encryption_at_rest` | EBS encryption by default is on **and no existing EBS volume in the region is unencrypted**, every RDS instance is encrypted, and every S3 bucket has default encryption |
| `privileged_access_mfa` | the root account has MFA, and every IAM user with AdministratorAccess (directly or through a group, all pages) has an MFA device. **If no such user exists the check is reported unknown, not true**: administrators who sign in through single sign-on are outside this check |
| `access_logging_enabled` | a multi-region CloudTrail trail exists and is logging |
| `backup_enabled` | an AWS Backup plan **that selects at least one resource** exists, or every RDS instance keeps automated backups (and at least one exists) |

A check the permissions do not allow is left out and the run is marked incomplete. It is never a pass or a failure.
One region per run. A lost token is replaced, never read back; replacing it ends the old one.
