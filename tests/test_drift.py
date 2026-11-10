"""Drift (ADR-058): a control's verdict over time, "turned worse this week", connectors gone quiet, and where each shows.

What is proved here: the recorded verdict is the same one the Controls page shows, history grows only when a verdict
moves, "worse" is a net comparison over the window, and the weekly chat summary carries counts and no names.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import db as db_module, drift, reports
from app.auth import Actor
from app.models import CollectionRun, ControlVerdictChange, EvidenceControlLink, Organization
from app.routers.analytics import best_verdict, control_details
from test_demo_collectors import _sync
from test_monitor import JUST_BEFORE, make_ready

NOW = datetime(2026, 11, 10, 12, 0)  # naive UTC, as stored


def _hist(org_id, clause, *rows, framework="ISO-27001"):
    """rows are (days before NOW, verdict)."""
    with Session(db_module.engine) as s:
        for days, verdict in rows:
            s.add(ControlVerdictChange(org_id=org_id, framework=framework, clause=clause, verdict=verdict,
                                       at=NOW - timedelta(days=days)))
        s.commit()


def _worse(org_id, now=NOW):
    with Session(db_module.engine) as s:
        return {(c["clause"]): (c["was"], c["now"]) for c in drift.controls_worse(s, org_id, now=now)}


def _admin(client, org_id):
    uid = client.post("/admin/users", json={"email": "admin@acme.test", "org_id": org_id, "role": "ORG_ADMIN"}).json()["id"]
    return {"authorization": f"user:{uid}"}


def _run(org_id, source, status, days_ago):
    with Session(db_module.engine) as s:
        s.add(CollectionRun(org_id=org_id, source=source, status=status, expectation="NONE",
                            started_at=NOW - timedelta(days=days_ago)))
        s.commit()


# ------------------------------------------------------------------ recording


def test_the_recorded_verdict_is_the_one_the_controls_page_shows(client, bootstrap, monkeypatch):
    """Two code paths decide a control's verdict; if they ever disagree, "turned worse" would report phantom changes."""
    _sync(client, bootstrap, monkeypatch, "aws")  # real verdicts across several frameworks
    with Session(db_module.engine) as s:
        org = s.query(Organization).first()
        shown = {(c["framework"], c["clause"]): best_verdict(c["links"])
                 for c in control_details(Actor(org_id=org.id, role="COMPLIANCE_VIEWER"), s)}
        recorded = {(r.framework, r.clause): r.verdict for r in s.query(ControlVerdictChange).filter_by(org_id=org.id)}
        assert shown and len(set(shown.values())) > 1 or "PASS" not in shown.values()  # a real spread, not all one verdict
        assert recorded == shown  # the pipeline wrote one row per control it judged, with the same verdict


def test_history_grows_only_when_a_verdict_moves(client, bootstrap, monkeypatch):
    _sync(client, bootstrap, monkeypatch, "aws")
    with Session(db_module.engine) as s:
        org_id = s.query(Organization).first().id
        before = s.query(ControlVerdictChange).count()
        assert before > 0
        assert drift.snapshot(s, org_id) == 0  # nothing moved since the pipeline wrote them

        link = s.query(EvidenceControlLink).filter(EvidenceControlLink.verdict != "PASS").first()
        link.verdict = "COMPLIANT"  # what an auditor's lock does: no evaluation runs, so only a snapshot sees it
        s.commit()
        assert drift.snapshot(s, org_id) == 1
        assert drift.snapshot(s, org_id) == 0
        newest = s.query(ControlVerdictChange).order_by(ControlVerdictChange.at.desc()).first()
        assert (newest.framework, newest.clause, newest.verdict) == (link.framework, link.clause, "PASS")  # mapped, as the page does
        assert s.query(ControlVerdictChange).count() == before + 1


# ------------------------------------------------------------------ what counts as worse


def test_worse_is_a_net_drop_over_the_window(client, bootstrap):
    org_id, _ = bootstrap(client)
    _hist(org_id, "dropped", (10, "PASS"), (2, "FAIL"))             # PASS a week ago, FAIL now
    _hist(org_id, "partly", (10, "PASS"), (3, "PARTIAL"))
    _hist(org_id, "recovered", (10, "FAIL"), (2, "PASS"))           # better
    _hist(org_id, "gained", (10, "NO_EVIDENCE"), (2, "FAIL"))       # evidence arrived: not worse
    _hist(org_id, "wobbled", (10, "PASS"), (4, "FAIL"), (1, "PASS"))  # worse then back: net nothing
    _hist(org_id, "steady", (10, "PASS"))
    _hist(org_id, "lost", (10, "PASS"), (1, "NO_EVIDENCE"))         # evidence went away
    _hist(org_id, "appeared", (3, "PASS"))                          # first recorded inside the window, never worse
    _hist(org_id, "appeared-then-failed", (5, "PASS"), (1, "FAIL"))  # caught from its first row
    _hist(org_id, "long-ago", (40, "PASS"), (20, "FAIL"))           # it turned worse, but not this week
    assert _worse(org_id) == {"dropped": ("PASS", "FAIL"), "partly": ("PASS", "PARTIAL"), "lost": ("PASS", "NO_EVIDENCE"),
                              "appeared-then-failed": ("PASS", "FAIL")}


def test_the_window_moves_with_the_clock(client, bootstrap):
    org_id, _ = bootstrap(client)
    _hist(org_id, "c", (10, "PASS"), (2, "FAIL"))
    assert "c" in _worse(org_id, NOW)
    assert "c" not in _worse(org_id, NOW + timedelta(days=9))  # the drop is now older than a week, so it is not this week's


def test_worst_first_and_scoped_to_the_organisation(client, bootstrap):
    a, _ = bootstrap(client)
    b, _ = bootstrap(client)
    _hist(a, "mild", (10, "PASS"), (2, "PARTIAL"))
    _hist(a, "bad", (10, "PASS"), (2, "FAIL"))
    _hist(b, "other", (10, "PASS"), (2, "FAIL"))
    with Session(db_module.engine) as s:
        assert [c["clause"] for c in drift.controls_worse(s, a, now=NOW)] == ["bad", "mild"]


# ------------------------------------------------------------------ connectors gone quiet


def test_a_connector_not_refreshed_in_n_days_is_listed_and_a_failed_run_is_not_a_refresh(client, bootstrap):
    org_id, _ = bootstrap(client)
    _run(org_id, "aws", "COMPLETE", 20)          # quiet
    _run(org_id, "m365", "COMPLETE", 3)          # fresh
    _run(org_id, "github", "COMPLETE", 30)
    _run(org_id, "github", "FAILED", 1)          # tried yesterday, failed: still 30 days since it worked
    _run(org_id, "hrms", "FAILED", 25)           # never worked: dated from the attempt
    _run(org_id, "keys", "PARTIAL", 2)           # partial still brought something in
    with Session(db_module.engine) as s:
        org = s.get(Organization, org_id)
        found = {c["source"]: c["days"] for c in drift.stale_connectors(s, org, now=NOW)}
        assert found == {"github": 30, "hrms": 25, "aws": 20}
        assert [c["source"] for c in drift.stale_connectors(s, org, now=NOW)] == ["github", "hrms", "aws"]  # longest first
        assert "aws" not in {c["source"] for c in drift.stale_connectors(s, org, now=NOW, days=21)}  # N is a parameter

        org.dpdp_na_sources = ["aws"]  # scoped out by the organisation: its own decision, not drift
        s.commit()
        assert "aws" not in {c["source"] for c in drift.stale_connectors(s, org, now=NOW)}


def test_a_source_never_used_is_not_gone_quiet(client, bootstrap):
    org_id, _ = bootstrap(client)
    with Session(db_module.engine) as s:
        assert drift.stale_connectors(s, s.get(Organization, org_id), now=NOW) == []


# ------------------------------------------------------------------ the weekly report


def test_the_weekly_report_counts_drift_and_names_nothing(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    make_ready(evidence_id)  # a policy reviewed until mid 2026, so it is inside the 30 day look-ahead on JUST_BEFORE
    _hist(org_id, "A.5.15", (10, "PASS"), (2, "FAIL"))
    _run(org_id, "aws", "COMPLETE", 20)
    now = datetime(JUST_BEFORE.year, JUST_BEFORE.month, JUST_BEFORE.day, 12, tzinfo=timezone.utc)
    # shift the history and the run to be relative to that clock instead of NOW
    with Session(db_module.engine) as s:
        for row in s.query(ControlVerdictChange).filter_by(clause="A.5.15"):
            row.at = row.at - NOW + now.replace(tzinfo=None)
        for run in s.query(CollectionRun):
            run.started_at = run.started_at - NOW + now.replace(tzinfo=None)
        s.commit()
        report = reports.build(s, s.get(Organization, org_id), now)
        quiet = reports.build(s, s.get(Organization, org_id), now - timedelta(days=200))

    assert report["drift"] == {"controls_worse": 1, "evidence_expiring": 1, "evidence_expired": 0, "expiry_days": 30,
                               "connectors_quiet": 1, "connector_days": 14}
    line = reports.text(report)
    assert ("Drift: 1 control turned worse this week, 1 evidence item expiring within 30 days, "
            "1 connector not refreshed in 14 days.") in line
    assert quiet["drift"]["controls_worse"] == 0
    assert "Drift: nothing turned worse, nothing expiring soon, no connector gone quiet." in reports.text(quiet)
    assert "Controls that turned worse this week: 1" in reports.markdown(report)

    # The framework table above it names frameworks by design (the trust page does too); the drift part names nothing.
    blob = (json.dumps(report["drift"]) + line.split(" Drift:")[1] + reports.markdown(report).split("## Drift")[1]).lower()
    for leaked in ("a.5.15", "iso-27001", "aws", "policy.txt", "m365"):  # no control, framework, source or file name
        assert leaked not in blob, leaked


def test_the_cron_records_every_control_before_it_counts(client, bootstrap, monkeypatch):
    """An auditor's lock runs no evaluation, so only the weekly snapshot can put it in the week's figures."""
    from app import monitor

    _sync(client, bootstrap, monkeypatch, "aws")
    with Session(db_module.engine) as s:
        org_id = s.query(Organization).first().id
        s.query(ControlVerdictChange).delete()  # as an organisation that existed before this shipped
        s.commit()
        assert reports.build(s, s.get(Organization, org_id))["drift"]["controls_worse"] == 0
    assert monitor._weekly_report() == 0
    with Session(db_module.engine) as s:
        assert s.query(ControlVerdictChange).count() > 0  # baseline written for the next run to compare against


# ------------------------------------------------------------------ the notifications feed


def test_notifications_show_worse_controls_to_those_who_may_see_them_and_quiet_connectors_to_all(client, bootstrap):
    org_id, _ = bootstrap(client)
    h = _admin(client, org_id)
    seen = client.post("/admin/controls", json={"org_id": org_id, "framework": "ISO-27001", "clause": "A.5.15"}).json()["id"]
    client.post("/admin/controls", json={"org_id": org_id, "framework": "ISO-27001", "clause": "A.8.5"})
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with Session(db_module.engine) as s:
        for clause in ("A.5.15", "A.8.5"):
            s.add(ControlVerdictChange(org_id=org_id, framework="ISO-27001", clause=clause, verdict="PASS", at=now - timedelta(days=10)))
            s.add(ControlVerdictChange(org_id=org_id, framework="ISO-27001", clause=clause, verdict="FAIL", at=now - timedelta(days=1)))
        s.add(CollectionRun(org_id=org_id, source="google-workspace", status="COMPLETE", expectation="NONE",
                            started_at=now - timedelta(days=20)))
        s.commit()

    items = client.get("/notifications", headers=h).json()["items"]
    worse = {i["message"]: i for i in items if i["kind"] == "CONTROL_WORSE"}
    assert set(worse) == {"ISO-27001 A.5.15 turned worse this week: PASS to FAIL",
                          "ISO-27001 A.8.5 turned worse this week: PASS to FAIL"}
    assert worse["ISO-27001 A.5.15 turned worse this week: PASS to FAIL"]["link"] == f"/controls/{seen}"
    assert all(i["severity"] == "high" for i in worse.values())
    quiet = [i for i in items if i["kind"] == "CONNECTOR_STALE"]
    assert [(q["message"], q["link"]) for q in quiet] == [("Google Workspace has not been refreshed in 20 days", "/connections")]

    owner = client.post("/admin/users", json={"email": "o@acme.test", "org_id": org_id, "role": "CONTROL_OWNER"}).json()["id"]
    client.post("/admin/control-assignments", json={"org_control_id": seen, "user_id": owner})
    mine = client.get("/notifications", headers={"authorization": f"user:{owner}"}).json()["items"]
    assert [i["message"] for i in mine if i["kind"] == "CONTROL_WORSE"] == ["ISO-27001 A.5.15 turned worse this week: PASS to FAIL"]

    other, _ = bootstrap(client)  # another organisation sees none of it
    assert not [i for i in client.get("/notifications", headers={"authorization": f"org:{other}"}).json()["items"]
                if i["kind"] in ("CONTROL_WORSE", "CONNECTOR_STALE")]
