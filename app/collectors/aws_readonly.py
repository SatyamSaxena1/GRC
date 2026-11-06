"""Read-only AWS checks for the four attributes the AWS evidence source needs (ADR-049), run on the customer's own computer.

Every check is a documented read call through the AWS SDK with the credentials and permissions the customer chose. Only
yes/no answers are uploaded: no resource names are kept. A check that cannot run (a permission the role lacks, a service
error) is *left out* of the result and reported in `collection`, never reported as false, so a missing permission
can never read as a failing control or, worse, a passing one.

`collect(session, region)` takes anything with `.client(name, region_name=...)`, so tests pass a stand-in and nothing
here knows about credentials.
"""

from __future__ import annotations

from typing import Any, Callable

ADMIN_POLICY = "arn:aws:iam::aws:policy/AdministratorAccess"


class Unknown(Exception):
    """A check that ran but could not reach an answer. Reported as unknown, never as a pass or a failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


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
    # The default only covers NEW volumes: any existing unencrypted volume in this region still fails the check.
    for page in ec2.get_paginator("describe_volumes").paginate(Filters=[{"Name": "encrypted", "Values": ["false"]}]):
        if page.get("Volumes"):
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
            for members in iam.get_paginator("get_group").paginate(GroupName=g["GroupName"]):   # groups can hold over 100
                admins |= {u["UserName"] for u in members.get("Users", [])}
    if not admins:
        # Nobody was examined, so "all of them have MFA" would be vacuously true. Administrators who sign in through single
        # sign-on or hold the access another way are outside this check: report it as unknown, never as a pass.
        raise Unknown("NoAdministratorUsersFound")
    return all(iam.list_mfa_devices(UserName=name).get("MFADevices") for name in admins)


def _access_logging(session, region) -> bool:
    ct = session.client("cloudtrail", region_name=region)
    for trail in ct.describe_trails().get("trailList", []):
        if trail.get("IsMultiRegionTrail") and ct.get_trail_status(Name=trail["TrailARN"]).get("IsLogging"):
            return True
    return False


def _backup(session, region) -> bool:
    backup = session.client("backup", region_name=region)
    for page in backup.get_paginator("list_backup_plans").paginate():
        for plan in page.get("BackupPlansList", []):
            # A plan that selects no resources protects nothing, so only a plan with at least one selection counts.
            if backup.list_backup_selections(BackupPlanId=plan["BackupPlanId"]).get("BackupSelectionsList"):
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
            code = getattr(exc, "code", None) or (
                getattr(exc, "response", {}).get("Error", {}).get("Code") if hasattr(exc, "response") else None)
            errors.append(f"{name} could not be checked ({code or type(exc).__name__})")
    return {"attributes": attributes,
            "collection": {"complete": not errors, "errors": errors, "region": region}}


def _url_ok(url: str) -> bool:
    """The upload token travels in a header, so it is only sent over https (or to this computer, for testing)."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1"))


def _post(request):
    """POST without following redirects: a redirect would carry the token to another address."""
    import urllib.request

    class _Stop(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    return urllib.request.build_opener(_Stop).open(request, timeout=30)


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
        print("no upload token: set GRC_UPLOAD_TOKEN (or pass --token)")
        return 2
    if not _url_ok(args.url):
        print("the --url must start with https:// so the token is not sent in clear")
        return 2
    request = urllib.request.Request(args.url.rstrip("/") + "/ingest/aws", data=json.dumps(result).encode(),
                                     method="POST", headers={"Content-Type": "application/json",
                                                             "Authorization": f"Bearer {args.token}"})
    try:
        with _post(request) as response:
            print(f"uploaded: HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        print(f"upload refused: HTTP {exc.code}")
        return 1
    except (urllib.error.URLError, OSError) as exc:
        print(f"could not reach the server: {type(exc).__name__}")
        return 4
    return 0 if result["collection"]["complete"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
