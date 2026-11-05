"""Read-only AWS checks for the four attributes the AWS evidence source needs (ADR-048).

Every check is a documented read call through the AWS SDK with a role the customer created and can revoke. Counts and
yes/no answers only: no resource names are kept. A check that cannot run (a permission the role lacks, a service
error) is *left out* of the result and reported in `collection`, never reported as false, so a missing permission
can never read as a failing control or, worse, a passing one.

`collect(session, region)` takes anything with `.client(name, region_name=...)`, so tests pass a stand-in and nothing
here knows about credentials.
"""

from __future__ import annotations

from typing import Any, Callable

ADMIN_POLICY = "arn:aws:iam::aws:policy/AdministratorAccess"


def _s3_encrypted(session, region) -> bool:
    s3 = session.client("s3", region_name=region)
    for b in s3.list_buckets().get("Buckets", []):
        try:
            s3.get_bucket_encryption(Bucket=b["Name"])
        except Exception as exc:  # noqa: BLE001
            if "ServerSideEncryptionConfigurationNotFoundError" in str(exc):
                return False
            raise
    return True


def _encryption_at_rest(session, region) -> bool:
    ec2, rds = session.client("ec2", region_name=region), session.client("rds", region_name=region)
    if not ec2.get_ebs_encryption_by_default().get("EbsEncryptionByDefault"):
        return False
    for page in rds.get_paginator("describe_db_instances").paginate():
        if not all(db.get("StorageEncrypted") for db in page.get("DBInstances", [])):
            return False
    return _s3_encrypted(session, region)


def _privileged_access_mfa(session, region) -> bool:
    iam = session.client("iam", region_name=region)
    if not iam.get_account_summary().get("SummaryMap", {}).get("AccountMFAEnabled"):
        return False                                                    # the root account has no MFA
    admins = set()
    for page in iam.get_paginator("list_entities_for_policy").paginate(PolicyArn=ADMIN_POLICY):
        admins |= {u["UserName"] for u in page.get("PolicyUsers", [])}
        for g in page.get("PolicyGroups", []):
            members = iam.get_group(GroupName=g["GroupName"]).get("Users", [])
            admins |= {u["UserName"] for u in members}
    return all(iam.list_mfa_devices(UserName=name).get("MFADevices") for name in admins)


def _access_logging(session, region) -> bool:
    ct = session.client("cloudtrail", region_name=region)
    for trail in ct.describe_trails().get("trailList", []):
        if trail.get("IsMultiRegionTrail") and ct.get_trail_status(Name=trail["TrailARN"]).get("IsLogging"):
            return True
    return False


def _backup(session, region) -> bool:
    if session.client("backup", region_name=region).list_backup_plans().get("BackupPlansList"):
        return True
    rds = session.client("rds", region_name=region)
    dbs = [db for page in rds.get_paginator("describe_db_instances").paginate() for db in page.get("DBInstances", [])]
    return bool(dbs) and all((db.get("BackupRetentionPeriod") or 0) > 0 for db in dbs)


CHECKS: dict[str, Callable[[Any, str], bool]] = {
    "encryption_at_rest": _encryption_at_rest,
    "privileged_access_mfa": _privileged_access_mfa,
    "access_logging_enabled": _access_logging,
    "backup_enabled": _backup,
}


def collect(session, region: str) -> dict:
    """{"attributes": {...}, "collection": {...}}: the shape every connector returns (app/routers/connectors.py)."""
    attributes: dict[str, bool] = {}
    errors: list[str] = []
    for name, check in CHECKS.items():
        try:
            attributes[name] = bool(check(session, region))
        except Exception as exc:  # noqa: BLE001 - the class and a short code only, never a message that may name resources
            code = getattr(exc, "response", {}).get("Error", {}).get("Code") if hasattr(exc, "response") else None
            errors.append(f"{name} could not be checked ({code or type(exc).__name__})")
    return {"attributes": attributes,
            "collection": {"complete": not errors, "errors": errors, "region": region}}


def main(argv: list[str] | None = None) -> int:
    """Run the four checks in the customer's own account and upload the answers. Standard library plus boto3 only,
    so this one file can be downloaded and run on its own:

        python aws_readonly.py --url https://grc.example.com --token "$GRC_UPLOAD_TOKEN" --region ap-south-1
    """
    import argparse
    import json
    import os
    import urllib.error
    import urllib.request

    parser = argparse.ArgumentParser(description="Read-only AWS checks, uploaded as four yes/no answers.")
    parser.add_argument("--url", required=True, help="your GRC address, e.g. https://grc.blinkedit.me")
    parser.add_argument("--region", required=True, help="the region where your databases and logging trail live")
    parser.add_argument("--token", default=os.environ.get("GRC_UPLOAD_TOKEN", ""), help="or set GRC_UPLOAD_TOKEN")
    parser.add_argument("--dry-run", action="store_true", help="print the answers, upload nothing")
    args = parser.parse_args(argv)

    import boto3  # imported here so the checks above stay testable without it

    result = collect(boto3.Session(), args.region)
    print(json.dumps(result, indent=2))
    if args.dry_run:
        return 0
    if not args.token:
        print("no upload token: pass --token or set GRC_UPLOAD_TOKEN")
        return 2
    request = urllib.request.Request(args.url.rstrip("/") + "/ingest/aws", data=json.dumps(result).encode(),
                                     method="POST", headers={"Content-Type": "application/json",
                                                             "Authorization": f"Bearer {args.token}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            print(f"uploaded: HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        print(f"upload refused: HTTP {exc.code}")
        return 1
    return 0 if result["collection"]["complete"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
