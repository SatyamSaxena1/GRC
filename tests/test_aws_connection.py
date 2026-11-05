"""Connections slice 3 (ADR-048): an organisation connects its own AWS account through a cross-account role. The server
only reaches AWS through the SDK; the customer supplies a role ARN and region, never a URL; a check that cannot run is
left out and reported, never read as a failure or a pass."""

from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import connections
from app import db as db_module
from app.collectors import aws_readonly
from app.models import AuditEvent, Connection
from app.routers import connectors

H = lambda org: {"authorization": f"org:{org}"}  # noqa: E731
ROLE = "arn:aws:iam::123456789012:role/grc-readonly"
PRINCIPAL = "arn:aws:iam::999999999999:user/grc-platform"


@pytest.fixture()
def aws_env(monkeypatch):
    monkeypatch.setenv("CONNECTIONS_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("AWS_PLATFORM_PRINCIPAL_ARN", PRINCIPAL)
    monkeypatch.setenv("PLATFORM_AWS_ACCESS_KEY_ID", "AKIAPLATFORMEXAMPLE")
    monkeypatch.setenv("PLATFORM_AWS_SECRET_ACCESS_KEY", "platform-secret-example")


def _org(client, bootstrap):
    return bootstrap(client)[0]


# --- a stand-in for the AWS SDK --------------------------------------------------------------------------------------
class Paginator:
    def __init__(self, pages):
        self.pages = pages

    def paginate(self, **kw):
        return iter(self.pages)


class Denied(Exception):
    response = {"Error": {"Code": "AccessDenied"}}


class FakeSession:
    """Healthy by default; flip `world` entries to make one control fail, or `deny` to refuse a service."""

    def __init__(self, **world):
        self.world = {"ebs_default": True, "rds": [{"StorageEncrypted": True, "BackupRetentionPeriod": 7}],
                      "buckets": [{"Name": "b1"}], "bucket_enc_missing": False, "root_mfa": True,
                      "admin_users": ["alice"], "mfa": {"alice": [{"SerialNumber": "x"}]},
                      "trails": [{"TrailARN": "t", "IsMultiRegionTrail": True}], "logging": True,
                      "backup_plans": [{"BackupPlanId": "p"}], "deny": set(), **world}

    def client(self, name, region_name=None):
        if name in self.world["deny"]:
            raise Denied()
        w = self.world
        s = self

        class C:
            def get_ebs_encryption_by_default(self):
                return {"EbsEncryptionByDefault": w["ebs_default"]}

            def get_paginator(self, op):
                if op == "describe_db_instances":
                    return Paginator([{"DBInstances": w["rds"]}])
                if op == "list_entities_for_policy":
                    return Paginator([{"PolicyUsers": [{"UserName": u} for u in w["admin_users"]], "PolicyGroups": []}])
                raise AssertionError(op)

            def list_buckets(self):
                return {"Buckets": w["buckets"]}

            def get_bucket_encryption(self, Bucket):
                if w["bucket_enc_missing"]:
                    raise Exception("ServerSideEncryptionConfigurationNotFoundError")
                return {}

            def get_account_summary(self):
                return {"SummaryMap": {"AccountMFAEnabled": 1 if w["root_mfa"] else 0}}

            def list_mfa_devices(self, UserName):
                return {"MFADevices": w["mfa"].get(UserName, [])}

            def describe_trails(self):
                return {"trailList": w["trails"]}

            def get_trail_status(self, Name):
                return {"IsLogging": w["logging"]}

            def list_backup_plans(self):
                return {"BackupPlansList": w["backup_plans"]}

        return C()


# --- the four checks -------------------------------------------------------------------------------------------------
def test_a_healthy_account_passes_all_four_and_is_complete():
    out = aws_readonly.collect(FakeSession(), "ap-south-1")
    assert out["attributes"] == {"encryption_at_rest": True, "privileged_access_mfa": True,
                                 "access_logging_enabled": True, "backup_enabled": True}
    assert out["collection"]["complete"] is True and out["collection"]["errors"] == []


@pytest.mark.parametrize("world,attribute", [
    ({"ebs_default": False}, "encryption_at_rest"),
    ({"rds": [{"StorageEncrypted": False, "BackupRetentionPeriod": 7}]}, "encryption_at_rest"),
    ({"bucket_enc_missing": True}, "encryption_at_rest"),
    ({"root_mfa": False}, "privileged_access_mfa"),
    ({"mfa": {}}, "privileged_access_mfa"),
    ({"logging": False}, "access_logging_enabled"),
    ({"trails": [{"TrailARN": "t", "IsMultiRegionTrail": False}]}, "access_logging_enabled"),
    ({"backup_plans": [], "rds": [{"StorageEncrypted": True, "BackupRetentionPeriod": 0}]}, "backup_enabled"),
])
def test_each_control_can_fail_on_its_own(world, attribute):
    out = aws_readonly.collect(FakeSession(**world), "ap-south-1")
    assert out["attributes"][attribute] is False
    assert sum(not v for v in out["attributes"].values()) == 1     # only the one that should


def test_a_missing_permission_is_left_out_and_reported_never_read_as_false():
    out = aws_readonly.collect(FakeSession(deny={"cloudtrail"}), "ap-south-1")
    assert "access_logging_enabled" not in out["attributes"]       # not false, not true: unknown
    assert out["collection"]["complete"] is False
    assert any("access_logging_enabled" in e and "AccessDenied" in e for e in out["collection"]["errors"])
    assert out["attributes"]["backup_enabled"] is True              # the others still ran


# --- input checks --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("arn,region", [
    ("https://evil.test/role", "ap-south-1"), ("arn:aws:iam::123:role/x", "ap-south-1"),
    ("arn:aws:iam::123456789012:user/x", "ap-south-1"), (ROLE, "not a region"), (ROLE, "https://evil.test"),
])
def test_bad_role_or_region_is_refused(arn, region):
    with pytest.raises(ValueError):
        connections.validate_aws(arn, region)


# --- the page's API ------------------------------------------------------------------------------------------------
def test_prepare_gives_a_stable_external_id_and_the_principal_to_trust(client, bootstrap, aws_env):
    org = _org(client, bootstrap)
    a = client.post("/connections/aws/prepare", headers=H(org)).json()["connections"][2]
    b = client.post("/connections/aws/prepare", headers=H(org)).json()["connections"][2]
    assert a["details"]["external_id"].startswith("grc-") and a["details"]["external_id"] == b["details"]["external_id"]
    assert a["details"]["platform_principal"] == PRINCIPAL and a["hint"] == "waiting for the role"


def test_without_a_platform_identity_prepare_says_so(client, bootstrap, aws_env, monkeypatch):
    monkeypatch.delenv("AWS_PLATFORM_PRINCIPAL_ARN")
    assert client.post("/connections/aws/prepare", headers=H(_org(client, bootstrap))).status_code == 503


def test_saving_the_role_keeps_the_external_id_and_is_audited_without_secrets(client, bootstrap, aws_env):
    org = _org(client, bootstrap)
    ext = client.post("/connections/aws/prepare", headers=H(org)).json()["connections"][2]["details"]["external_id"]
    r = client.put("/connections/aws", json={"role_arn": ROLE, "region": "ap-south-1"}, headers=H(org))
    d = r.json()["connections"][2]["details"]
    assert r.status_code == 200 and d["external_id"] == ext and d["role_arn"] == ROLE
    with Session(db_module.engine) as s:
        row = s.query(Connection).filter_by(org_id=org, kind="AWS_READONLY").one()
        assert ROLE not in row.config_encrypted and "platform-secret-example" not in json.dumps(
            [e.detail for e in s.query(AuditEvent)], default=str)


def test_the_test_button_reports_assume_role_failures_without_leaking(client, bootstrap, aws_env, monkeypatch):
    org = _org(client, bootstrap)
    client.post("/connections/aws/prepare", headers=H(org))
    client.put("/connections/aws", json={"role_arn": ROLE, "region": "ap-south-1"}, headers=H(org))

    class Boto:
        @staticmethod
        def client(*a, **k):
            class STS:
                def assume_role(self, **kw):
                    assert kw["ExternalId"].startswith("grc-") and kw["RoleArn"] == ROLE
                    raise Denied()
            return STS()

    import sys, types
    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=Boto.client, Session=lambda **k: None))
    one = client.post("/connections/aws/test", headers=H(org)).json()["connections"][2]
    assert one["status"] == "FAILED" and "AccessDenied" in one["last_error"]
    assert "platform-secret-example" not in json.dumps(one)


def test_only_org_admins_and_each_org_sees_only_its_own(client, bootstrap, aws_env):
    org = _org(client, bootstrap)
    other = client.post("/admin/organizations", json={"name": "Other", "frameworks": ["SOC-2"]}).json()["id"]
    client.post("/connections/aws/prepare", headers=H(org))
    assert client.get("/connections", headers=H(other)).json()["connections"][2]["configured"] is False
    assert client.post("/connections/aws/prepare", headers={"authorization": "user:nobody"}).status_code in (401, 403)


def test_removing_deletes_the_row(client, bootstrap, aws_env):
    org = _org(client, bootstrap)
    client.post("/connections/aws/prepare", headers=H(org))
    assert client.delete("/connections/aws", headers=H(org)).json()["connections"][2]["configured"] is False


# --- the sync uses the organisation's own role ---------------------------------------------------------------------
def test_a_sync_collects_through_the_orgs_own_role(client, bootstrap, aws_env, monkeypatch):
    org = _org(client, bootstrap)
    client.post("/connections/aws/prepare", headers=H(org))
    client.put("/connections/aws", json={"role_arn": ROLE, "region": "ap-south-1"}, headers=H(org))
    monkeypatch.delenv("DPDP_AWS_COLLECTOR_URL", raising=False)
    seen = []
    monkeypatch.setattr(connections, "aws_assume", lambda cfg: seen.append(cfg) or FakeSession())
    with Session(db_module.engine) as s:
        payload = connectors._pull("aws", s, org)
    assert seen[0]["role_arn"] == ROLE and payload["attributes"]["backup_enabled"] is True
    assert payload["source"] == "aws"


def test_a_prepared_but_unfinished_connection_is_not_a_collector(client, bootstrap, aws_env, monkeypatch):
    org = _org(client, bootstrap)
    client.post("/connections/aws/prepare", headers=H(org))
    monkeypatch.delenv("DPDP_AWS_COLLECTOR_URL", raising=False)
    with Session(db_module.engine) as s, pytest.raises(HTTPException) as e:
        connectors._pull("aws", s, org)
    assert e.value.status_code == 409


def test_an_unreadable_connection_fails_closed_and_never_uses_the_shared_collector(client, bootstrap, aws_env, monkeypatch):
    org = _org(client, bootstrap)
    client.post("/connections/aws/prepare", headers=H(org))
    monkeypatch.setenv("CONNECTIONS_KEY", Fernet.generate_key().decode())       # the key was replaced
    monkeypatch.setenv("DPDP_AWS_COLLECTOR_URL", "http://127.0.0.1:9/should-not-be-called")
    with Session(db_module.engine) as s, pytest.raises(HTTPException) as e:
        connectors._pull("aws", s, org)
    assert e.value.status_code == 502 and "unreadable" in e.value.detail


def test_a_partial_aws_run_is_not_complete(client, bootstrap, aws_env, monkeypatch):
    org = _org(client, bootstrap)
    client.post("/connections/aws/prepare", headers=H(org))
    client.put("/connections/aws", json={"role_arn": ROLE, "region": "ap-south-1"}, headers=H(org))
    monkeypatch.delenv("DPDP_AWS_COLLECTOR_URL", raising=False)
    monkeypatch.setattr(connections, "aws_assume", lambda cfg: FakeSession(deny={"cloudtrail"}))
    with Session(db_module.engine) as s:
        snapshot = connectors._pull("aws", s, org)
    assert snapshot["declared"]["complete"] is False
