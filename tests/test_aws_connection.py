"""AWS by upload (ADR-049): the customer runs a read-only script in their own account and uploads four yes/no answers
with a token. The platform holds no AWS identity and calls nothing in AWS. A check that cannot run is left out and
reported, never read as a failure or a pass."""

from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app import connections
from app import db as db_module
from app.collectors import aws_readonly
from app.models import AuditEvent, Connection

H = lambda org: {"authorization": f"org:{org}"}  # noqa: E731


@pytest.fixture()
def aws_env(monkeypatch):
    monkeypatch.setenv("CONNECTIONS_KEY", Fernet.generate_key().decode())


def _org(client, bootstrap):
    return bootstrap(client)[0]


# --- a stand-in for the AWS SDK --------------------------------------------------------------------------------------
class Paginator:
    def __init__(self, pages):
        self.pages = pages

    def paginate(self, **kw):
        return iter(self.pages)


class GroupPaginator:
    """get_group pages: a group's members arrive over several pages."""

    def __init__(self, groups):
        self.groups = groups

    def paginate(self, GroupName):
        return iter([{"Users": [{"UserName": u} for u in page]} for page in self.groups[GroupName]])


class Denied(Exception):
    response = {"Error": {"Code": "AccessDenied"}}


class FakeSession:
    """Healthy by default; flip `world` entries to make one control fail, or `deny` to refuse a service."""

    def __init__(self, **world):
        self.world = {"ebs_default": True, "rds": [{"StorageEncrypted": True, "BackupRetentionPeriod": 7}],
                      "buckets": [{"Name": "b1"}], "bucket_enc_missing": False, "root_mfa": True,
                      "admin_users": ["alice"], "mfa": {"alice": [{"SerialNumber": "x"}]},
                      "trails": [{"TrailARN": "t", "IsMultiRegionTrail": True}], "logging": True,
                      "backup_plans": [{"BackupPlanId": "p"}], "backup_selections": [{"SelectionId": "s"}],
                      "unencrypted_volumes": [], "admin_groups": {}, "deny": set(), **world}

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
                    return Paginator([{"PolicyUsers": [{"UserName": u} for u in w["admin_users"]],
                                       "PolicyGroups": [{"GroupName": g} for g in w["admin_groups"]]}])
                if op == "describe_volumes":
                    return Paginator([{"Volumes": w["unencrypted_volumes"]}])
                if op == "get_group":
                    return GroupPaginator(w["admin_groups"])
                if op == "list_backup_plans":
                    return Paginator([{"BackupPlansList": w["backup_plans"]}])
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

            def list_backup_selections(self, BackupPlanId):
                return {"BackupSelectionsList": w["backup_selections"]}

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
    ({"unencrypted_volumes": [{"VolumeId": "v-1"}]}, "encryption_at_rest"),                      # default is on, an old volume is not
    ({"backup_selections": [], "rds": [{"StorageEncrypted": True, "BackupRetentionPeriod": 0}]}, "backup_enabled"),  # an empty plan
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


# --- the token ------------------------------------------------------------------------------------------------------
def test_a_token_carries_the_org_and_only_its_hash_is_kept():
    token, digest = connections.new_push_token("org-1")
    org, secret = connections.split_push_token(token)
    assert org == "org-1" and token.endswith(secret) and len(secret) >= 40
    assert connections.push_token_matches(digest, secret) and not connections.push_token_matches(digest, secret + "x")
    assert connections.split_push_token("nodot") is None and connections.split_push_token("a.short") is None


def _make_token(client, org):
    r = client.post("/connections/aws/token", headers=H(org))
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    return r.json()["new_token"], r.json()


GOOD = {"attributes": {"encryption_at_rest": True, "privileged_access_mfa": True, "access_logging_enabled": True,
                       "backup_enabled": False},
        "collection": {"complete": True, "errors": [], "region": "ap-south-1"}}


def _push(client, token, body=GOOD):
    return client.post("/ingest/aws", json=body, headers={"authorization": f"Bearer {token}"})


def test_the_token_is_shown_once_and_never_stored_or_returned_again(client, bootstrap, aws_env):
    org = _org(client, bootstrap)
    token, body = _make_token(client, org)
    secret = token.split(".", 1)[1]
    assert body["connections"][2]["configured"] and secret not in json.dumps(body["connections"])
    assert secret not in client.get("/connections", headers=H(org)).text
    with Session(db_module.engine) as s:
        row = s.query(Connection).filter_by(org_id=org, kind="AWS_PUSH").one()
        assert secret not in row.config_encrypted and secret not in row.hint
        assert secret not in json.dumps([e.detail for e in s.query(AuditEvent)], default=str)


def test_a_valid_upload_is_stored_as_aws_evidence_and_marks_the_connection_ok(client, bootstrap, aws_env):
    org = _org(client, bootstrap)
    token, _ = _make_token(client, org)
    r = _push(client, token)
    assert r.status_code == 202 and r.json()["complete"] is True
    state = client.get("/connections", headers=H(org)).json()["connections"][2]
    assert state["status"] == "OK" and state["last_tested_at"]
    from app.models import Evidence
    with Session(db_module.engine) as s:
        ev = s.query(Evidence).filter_by(org_id=org, artefact_type="AWS_SNAPSHOT").one()
        assert ev.uploaded_by == "upload:aws"


@pytest.mark.parametrize("header", [None, "", "Bearer ", "Bearer nodot", "Bearer a.tooshort", "Basic xyz"])
def test_missing_or_malformed_tokens_are_refused(client, bootstrap, aws_env, header):
    _make_token(client, _org(client, bootstrap))
    r = client.post("/ingest/aws", json=GOOD, headers={"authorization": header} if header is not None else {})
    assert r.status_code == 401 and r.json()["detail"] == "invalid upload token"


def test_a_wrong_secret_an_unknown_org_and_a_removed_connection_are_all_refused_the_same_way(client, bootstrap, aws_env):
    org = _org(client, bootstrap)
    token, _ = _make_token(client, org)
    secret = token.split(".", 1)[1]
    assert _push(client, f"{org}.{'x' * 40}").status_code == 401
    assert _push(client, f"someone-else.{secret}").status_code == 401
    client.delete("/connections/aws", headers=H(org))
    assert _push(client, token).status_code == 401


def test_replacing_the_token_ends_the_old_one_at_once(client, bootstrap, aws_env):
    org = _org(client, bootstrap)
    old, _ = _make_token(client, org)
    new, _ = _make_token(client, org)
    assert old != new and _push(client, old).status_code == 401 and _push(client, new).status_code == 202


def test_one_organisations_token_cannot_write_to_another(client, bootstrap, aws_env):
    a = _org(client, bootstrap)
    b = client.post("/admin/organizations", json={"name": "Other", "frameworks": ["SOC-2"]}).json()["id"]
    token_a, _ = _make_token(client, a)
    secret_a = token_a.split(".", 1)[1]
    assert _push(client, f"{b}.{secret_a}").status_code == 401


@pytest.mark.parametrize("body", [
    {}, {"attributes": {}}, {"attributes": {"encryption_at_rest": "yes"}}, {"attributes": {"made_up": True}},
    {"attributes": {"encryption_at_rest": 1}},
])
def test_only_the_four_yes_no_attributes_are_accepted(client, bootstrap, aws_env, body):
    token, _ = _make_token(client, _org(client, bootstrap))
    assert _push(client, token, body).status_code == 422


def test_a_run_with_errors_is_marked_incomplete_and_extra_fields_are_dropped(client, bootstrap, aws_env):
    org = _org(client, bootstrap)
    token, _ = _make_token(client, org)
    body = {"attributes": {"backup_enabled": True},
            "collection": {"complete": True, "errors": ["access_logging_enabled could not be checked (AccessDenied)"],
                           "region": "ap-south-1", "secret_field": "x"},
            "script": "rm -rf /"}
    r = _push(client, token, body)
    assert r.status_code == 202 and r.json()["complete"] is False
    from app.models import CollectionRun
    with Session(db_module.engine) as s:
        run = s.query(CollectionRun).filter_by(org_id=org, source="aws").one()
        assert run.status == "PARTIAL" and "rm -rf" not in json.dumps(run.returned, default=str)


def test_uploads_are_rate_limited_and_size_capped(client, bootstrap, aws_env):
    token, _ = _make_token(client, _org(client, bootstrap))
    assert _push(client, token).status_code == 202
    assert _push(client, token).status_code == 429
    big = {"attributes": {"backup_enabled": True}, "pad": "x" * 30_000}
    assert client.post("/ingest/aws", json=big, headers={"authorization": f"Bearer {token}"}).status_code == 413


def test_the_feature_is_off_without_a_key(client, bootstrap, monkeypatch):
    monkeypatch.delenv("CONNECTIONS_KEY", raising=False)
    assert client.post("/connections/aws/token", headers=H(_org(client, bootstrap))).status_code == 503


def test_only_org_admins_can_make_or_remove_the_token(client, bootstrap, aws_env):
    org = _org(client, bootstrap)
    assert client.post("/connections/aws/token", headers={"authorization": "user:nobody"}).status_code in (401, 403)
    _make_token(client, org)
    assert client.delete("/connections/aws", headers=H(org)).json()["connections"][2]["configured"] is False
    with Session(db_module.engine) as s:
        assert s.query(AuditEvent).filter_by(action="CONNECTION_REMOVED").count() == 1


def test_the_connect_button_explains_that_results_arrive_from_the_script(client, bootstrap, aws_env, monkeypatch):
    org = _org(client, bootstrap)
    monkeypatch.delenv("DPDP_AWS_COLLECTOR_URL", raising=False)
    _make_token(client, org)
    r = client.post("/connectors/aws/sync", headers=H(org))
    assert r.status_code == 409 and "own script" in r.json()["detail"]


def test_the_script_dry_run_prints_the_answers_and_uploads_nothing(monkeypatch, capsys):
    import sys, types
    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(Session=lambda: FakeSession()))
    assert aws_readonly.main(["--url", "https://example.test", "--region", "ap-south-1", "--dry-run"]) == 0
    assert '"backup_enabled": true' in capsys.readouterr().out


def test_no_administrators_found_is_unknown_not_a_pass():
    out = aws_readonly.collect(FakeSession(admin_users=[]), "ap-south-1")
    assert "privileged_access_mfa" not in out["attributes"] and out["collection"]["complete"] is False
    assert any("privileged_access_mfa" in e and "NoAdministratorUsersFound" in e for e in out["collection"]["errors"])


def test_admin_group_members_on_a_later_page_are_checked_too():
    world = {"admin_users": [], "admin_groups": {"admins": [["alice"], ["bob"]]},          # bob is on page two and has no MFA
             "mfa": {"alice": [{"SerialNumber": "x"}]}}
    assert aws_readonly.collect(FakeSession(**world), "ap-south-1")["attributes"]["privileged_access_mfa"] is False
    world["mfa"]["bob"] = [{"SerialNumber": "y"}]
    assert aws_readonly.collect(FakeSession(**world), "ap-south-1")["attributes"]["privileged_access_mfa"] is True


def test_the_scripts_refuse_a_clear_text_address_and_report_an_unreachable_server(capsys, monkeypatch):
    import sys, types
    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(Session=lambda: FakeSession()))
    base = ["--region", "ap-south-1", "--token", "x" * 30]
    assert aws_readonly.main(["--url", "http://example.test"] + base) == 2
    assert "https://" in capsys.readouterr().out
    assert aws_readonly._url_ok("https://grc.example.test") and aws_readonly._url_ok("http://localhost:8000")
    assert not aws_readonly._url_ok("http://grc.example.test") and not aws_readonly._url_ok("ftp://x")
    assert aws_readonly.main(["--url", "https://127.0.0.1:9"] + base) == 4                    # nothing listens there
    assert "could not reach" in capsys.readouterr().out


# --- the ingest reads nothing for a caller who is not allowed, and caps what it does read ------------------------------
def test_a_chunked_body_with_no_content_length_is_still_capped(client, bootstrap, aws_env):
    token, _ = _make_token(client, _org(client, bootstrap))

    def chunks():
        for _ in range(10):                      # 10 x 5 KB, sent as a stream: no Content-Length header at all
            yield b" " * 5000

    r = client.post("/ingest/aws", content=chunks(), headers={"authorization": f"Bearer {token}",
                                                              "content-type": "application/json"})
    assert r.status_code == 413


def test_an_unauthenticated_caller_is_refused_before_the_body_is_read(client, bootstrap, aws_env):
    _make_token(client, _org(client, bootstrap))
    read = []

    def chunks():
        for _ in range(10):
            read.append(1)
            yield b" " * 5000

    r = client.post("/ingest/aws", content=chunks(), headers={"authorization": "Bearer nobody.nothingnothingnothingnothing"})
    assert r.status_code == 401
    assert len(read) < 10                        # the server stopped before consuming the stream


def test_an_upload_that_does_not_say_whether_it_is_complete_is_not_complete(client, bootstrap, aws_env):
    org = _org(client, bootstrap)
    token, _ = _make_token(client, org)
    r = _push(client, token, body={"attributes": {"backup_enabled": True}})                 # no "collection" at all
    assert r.status_code == 202 and r.json()["complete"] is False
    r2 = client.post("/ingest/aws", json={"attributes": {"backup_enabled": True}, "collection": {"complete": "yes"}},
                     headers={"authorization": f"Bearer {token}"})
    assert r2.status_code in (202, 429)
    assert not isinstance(r2.json().get("complete", False), str)
