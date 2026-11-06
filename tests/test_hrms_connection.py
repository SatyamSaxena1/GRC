"""HR leavers by upload (ADR-051): a script on the customer's own computer reconciles two exports and uploads one number.
No name or address leaves the machine. The ingest accepts a count for HR, never a yes/no, and the other sources never a count."""

from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app import connections
from app import db as db_module
from app.collectors import hr_leavers
from app.models import AuditEvent, Connection, Evidence

H = lambda org: {"authorization": f"org:{org}"}  # noqa: E731


@pytest.fixture()
def key(monkeypatch):
    monkeypatch.setenv("CONNECTIONS_KEY", Fernet.generate_key().decode())


def _org(client, bootstrap):
    return bootstrap(client)[0]


# --- the reconciliation, on the customer's computer ------------------------------------------------------------------
def test_leavers_with_an_active_account_are_counted_ignoring_case_spaces_and_repeats():
    count, who = hr_leavers.count_leavers(["A@x.com", " b@x.com ", "a@x.com", "c@x.com", ""],
                                          ["a@X.com", "b@x.com", "d@x.com"])
    assert count == 2 and who == ["a@x.com", "b@x.com"]


def test_nobody_left_with_access_is_zero():
    assert hr_leavers.count_leavers(["a@x.com"], ["b@x.com"]) == (0, [])


def test_the_upload_carries_only_the_number():
    out = hr_leavers.build(["a@x.com", "b@x.com"], ["a@x.com"])
    assert out == {"attributes": {"terminated_users_with_active_accounts": 1},
                   "collection": {"complete": True, "errors": [], "region": "hrms"}}
    assert "a@x.com" not in json.dumps(out)


def test_an_empty_leavers_list_is_incomplete_unless_allowed():
    assert hr_leavers.build([], ["a@x.com"])["collection"]["complete"] is False
    assert hr_leavers.build([], ["a@x.com"], allow_empty=True)["collection"]["complete"] is True
    assert hr_leavers.build(["a@x.com"], [])["collection"]["complete"] is False       # no accounts: wrong file, not "zero"


def test_the_script_reads_csv_files_and_reports_a_missing_column(tmp_path, capsys):
    leavers, accounts = tmp_path / "l.csv", tmp_path / "a.csv"
    leavers.write_text("﻿Name,Email\nAda,ada@x.com\nBob,bob@x.com\n", encoding="utf-8")
    accounts.write_text("email\nada@x.com\n", encoding="utf-8")
    args = ["--url", "https://example.test", "--leavers", str(leavers), "--accounts", str(accounts), "--dry-run"]
    assert hr_leavers.main(args) == 0
    out = capsys.readouterr().out
    assert '"terminated_users_with_active_accounts": 1' in out and "ada@x.com" not in out      # not printed unless asked
    assert hr_leavers.main(args + ["--show"]) == 0 and "still active: ada@x.com" in capsys.readouterr().out
    bad = tmp_path / "bad.csv"
    bad.write_text("who\nada@x.com\n", encoding="utf-8")
    assert hr_leavers.main(["--url", "https://example.test", "--leavers", str(bad), "--accounts", str(accounts), "--dry-run"]) == 2
    assert "no 'email' column" in capsys.readouterr().out


# --- the ingest ------------------------------------------------------------------------------------------------------
def _token(client, org, source="hrms"):
    r = client.post(f"/connections/{source}/token", headers=H(org))
    assert r.status_code == 200
    return r.json()["new_token"]


def _push(client, token, count, source="hrms", extra=None):
    body = {"attributes": {"terminated_users_with_active_accounts": count}, "collection": {"complete": True, "errors": []}, **(extra or {})}
    return client.post(f"/ingest/{source}", json=body, headers={"authorization": f"Bearer {token}"})


def test_the_connections_list_has_all_five_kinds_in_the_order_the_page_expects(client, bootstrap, key):
    kinds = [c["kind"] for c in client.get("/connections", headers=H(_org(client, bootstrap))).json()["connections"]]
    assert kinds == ["CHAT_WEBHOOK", "GITHUB_CHANGE_CONTROL", "AWS_PUSH", "M365_PUSH", "HRMS_PUSH"]


def test_a_count_is_stored_as_hr_evidence_and_zero_is_a_valid_answer(client, bootstrap, key):
    org = _org(client, bootstrap)
    token = _token(client, org)
    assert _push(client, token, 0).status_code == 202
    with Session(db_module.engine) as s:
        ev = s.query(Evidence).filter_by(org_id=org, artefact_type="HRMS_SNAPSHOT").one()
        assert ev.uploaded_by == "upload:hrms"
        assert s.query(Connection).filter_by(org_id=org, kind="HRMS_PUSH").one().status == "OK"


@pytest.mark.parametrize("bad", [True, False, -1, 1.5, "3", None, 10**9])
def test_only_a_whole_number_in_range_is_accepted_for_hr(client, bootstrap, key, bad):
    assert _push(client, _token(client, _org(client, bootstrap)), bad).status_code == 422


def test_yes_no_sources_still_refuse_counts_and_hr_refuses_other_attributes(client, bootstrap, key):
    org = _org(client, bootstrap)
    aws = _token(client, org, "aws")
    assert client.post("/ingest/aws", json={"attributes": {"backup_enabled": 3}},
                       headers={"authorization": f"Bearer {aws}"}).status_code == 422
    hr = _token(client, org)
    assert client.post("/ingest/hrms", json={"attributes": {"backup_enabled": True}},
                       headers={"authorization": f"Bearer {hr}"}).status_code == 422


def test_the_hr_token_never_works_for_another_source_and_is_never_stored(client, bootstrap, key):
    org = _org(client, bootstrap)
    hr = _token(client, org)
    assert client.post("/ingest/aws", json={"attributes": {"backup_enabled": True}},
                       headers={"authorization": f"Bearer {hr}"}).status_code == 401
    secret = hr.split(".", 1)[1]
    assert secret not in client.get("/connections", headers=H(org)).text
    with Session(db_module.engine) as s:
        assert secret not in json.dumps([e.detail for e in s.query(AuditEvent)], default=str)


def test_the_collect_button_explains_that_results_come_from_the_script(client, bootstrap, key, monkeypatch):
    org = _org(client, bootstrap)
    monkeypatch.delenv("DPDP_HRMS_COLLECTOR_URL", raising=False)
    _token(client, org)
    r = client.post("/connectors/hrms/sync", headers=H(org))
    assert r.status_code == 409 and "own script" in r.json()["detail"]


def test_rows_with_no_usable_email_are_reported_not_silently_dropped():
    out = hr_leavers.build(["a@x.com", "", "not-an-email"], ["a@x.com", "b@x.com", " "])
    assert out["collection"]["complete"] is False
    assert any("leavers" in e and "2 row" in e for e in out["collection"]["errors"])
    assert any("accounts" in e and "1 row" in e for e in out["collection"]["errors"])
