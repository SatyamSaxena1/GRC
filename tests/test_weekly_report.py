"""The weekly report (ADR-041): counts from stored timestamps, content-free, delivered once a week."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app import db as db_module, monitor, notify, reports
from app.models import Organization
from test_demo_collectors import _sync

AUTH = lambda org: {"authorization": f"org:{org}"}  # noqa: E731


def _org(client):
    with Session(db_module.engine) as s:
        return s.query(Organization).first().id


@pytest.fixture()
def posts(monkeypatch):
    sent: list[dict] = []

    class Response:
        status_code = 200

    monkeypatch.setattr(notify.requests, "post",
                        lambda url, data=None, headers=None, timeout=None: sent.append(json.loads(data)) or Response())
    monkeypatch.setattr(notify, "_spawn", lambda work: work())
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://hooks.test/x")
    return sent


def test_this_week_counts_what_happened_in_the_window(client, bootstrap, monkeypatch):
    _sync(client, bootstrap, monkeypatch, "aws")
    with Session(db_module.engine) as s:
        org = s.query(Organization).first()
        now = datetime.now(timezone.utc)
        report = reports.build(s, org, now)
        later = reports.build(s, org, now + timedelta(days=30))  # a month on: that week is long over
    assert report["this_week"]["new_gaps"] > 0
    assert report["this_week"]["evidence_collected_or_uploaded"] >= 1
    assert report["open_now"]["gaps"] > 0
    assert later["this_week"] == {"new_gaps": 0, "gaps_resolved": 0, "evidence_collected_or_uploaded": 0, "controls_locked": 0}
    assert later["open_now"]["gaps"] == report["open_now"]["gaps"]  # open gaps are a position, not a window


def test_the_report_is_content_free(client, bootstrap, monkeypatch):
    _sync(client, bootstrap, monkeypatch, "aws")
    with Session(db_module.engine) as s:
        report = reports.build(s, s.query(Organization).first())
    blob = (json.dumps(report) + reports.text(report) + reports.markdown(report)).lower()
    for leaked in ("connector-aws", ".json", "encryption_at_rest", "privileged_access_mfa", "@"):
        assert leaked not in blob, leaked


def test_the_text_names_the_period_and_the_counts(client, bootstrap, monkeypatch):
    _sync(client, bootstrap, monkeypatch, "m365")
    with Session(db_module.engine) as s:
        report = reports.build(s, s.query(Organization).first())
    line = reports.text(report)
    assert line.startswith("Weekly compliance report for Acme (") and report["period"]["to"] in line
    assert f"Controls: {report['now']['controls']['total']}" in line


def test_only_admins_and_viewers_can_read_it(client, bootstrap, monkeypatch):
    _sync(client, bootstrap, monkeypatch, "m365")
    org = _org(client)
    body = client.get("/reports/weekly", headers=AUTH(org)).json()
    assert body["organisation"] == "Acme" and body["text"].startswith("Weekly compliance report")
    assert body["delivery"]["webhook_configured"] is False
    assert client.get("/reports/weekly.md", headers=AUTH(org)).text.startswith("# Weekly compliance report")

    owner = client.post("/admin/users", json={"email": "o@x.test", "org_id": org, "role": "CONTROL_OWNER"}).json()["id"]
    assert client.get("/reports/weekly", headers={"authorization": f"user:{owner}"}).status_code == 403


def test_the_cron_posts_once_per_organisation_per_week(client, bootstrap, monkeypatch, posts):
    _sync(client, bootstrap, monkeypatch, "m365")
    assert monitor._weekly_report() == 0
    assert len(posts) == 1 and posts[0]["kind"] == "weekly_report" and posts[0]["message"].startswith("Weekly compliance report")
    monitor._weekly_report()  # the same week again
    assert len(posts) == 1


def test_without_a_webhook_the_cron_sends_nothing_and_does_not_fail(client, bootstrap, monkeypatch, capsys):
    _sync(client, bootstrap, monkeypatch, "m365")
    monkeypatch.delenv("NOTIFY_WEBHOOK_URL", raising=False)
    assert monitor._weekly_report() == 0
    assert "not configured" in capsys.readouterr().out


def _vendor(client, org, name, **kw):
    body = {"name": name, "data_access": "PERSONAL", "criticality": "HIGH", **kw}
    return client.post("/vendors", json=body, headers=AUTH(org)).json()


def test_vendor_reviews_are_counted_and_never_named(client, bootstrap, monkeypatch):
    _sync(client, bootstrap, monkeypatch, "m365")
    org = _org(client)
    with Session(db_module.engine) as s:
        assert reports.build(s, s.query(Organization).first())["vendors"]["active"] == 0
        assert "Vendors:" not in reports.text(reports.build(s, s.query(Organization).first()))  # no register, no sentence

    never = _vendor(client, org, "Secret Supplier Ltd")
    done = _vendor(client, org, "Another Hidden Vendor")
    client.post(f"/vendors/{done['id']}/review", json={"note": "Read their latest audit report"}, headers=AUTH(org))
    off = _vendor(client, org, "Departed Vendor")
    client.patch(f"/vendors/{off['id']}", json={"status": "OFFBOARDED"}, headers=AUTH(org))

    with Session(db_module.engine) as s:
        org_row = s.query(Organization).first()
        now = datetime.now(timezone.utc)
        report = reports.build(s, org_row, now)
        year_on = reports.build(s, org_row, now + timedelta(days=400))
    assert report["vendors"] == {"active": 2, "reviews_overdue": 1, "reviews_due_soon": 0}  # offboarded is not counted
    assert year_on["vendors"]["reviews_overdue"] == 2  # a year later the reviewed one has lapsed too
    line = reports.text(report)
    assert "Vendors: 2 active, 1 reviews overdue, 0 due soon." in line
    blob = (json.dumps(report) + line + reports.markdown(report)).lower()
    for name in ("secret supplier", "another hidden", "departed"):
        assert name not in blob, name
    assert never["name"] not in blob


def test_a_current_report_changes_when_a_review_is_due(client, bootstrap, monkeypatch):
    _sync(client, bootstrap, monkeypatch, "m365")
    org = _org(client)
    v = _vendor(client, org, "Cadence Co", data_access="NONE", criticality="LOW")  # LOW tier: reviewed yearly
    client.post(f"/vendors/{v['id']}/review", json={"note": "Checked their security page"}, headers=AUTH(org))
    with Session(db_module.engine) as s:
        org_row = s.query(Organization).first()
        now = datetime.now(timezone.utc)
        assert reports.build(s, org_row, now)["vendors"]["reviews_overdue"] == 0
        assert reports.build(s, org_row, now + timedelta(days=340))["vendors"]["reviews_due_soon"] == 1
        assert reports.build(s, org_row, now + timedelta(days=370))["vendors"]["reviews_overdue"] == 1
