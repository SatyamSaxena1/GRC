"""The risk register (ADR-057): fixed rules decide the score, tenancy and roles bound who sees what, every change is
audited, and a model can only draft wording."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app import db as db_module, ingest, reports, risks
from app.models import AuditEvent, Organization, Risk

H = lambda org: {"authorization": f"org:{org}"}  # noqa: E731
TODAY = date(2026, 11, 10)


# ---- the rules -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("likelihood,impact,points,band", [
    (1, 1, 1, "LOW"), (2, 2, 4, "LOW"),
    (1, 5, 5, "MEDIUM"), (3, 3, 9, "MEDIUM"),
    (2, 5, 10, "HIGH"), (4, 4, 16, "HIGH"),
    (5, 4, 20, "CRITICAL"), (5, 5, 25, "CRITICAL"), (4, 5, 20, "CRITICAL"),
])
def test_the_score_is_likelihood_times_impact_and_the_band_follows_the_score(likelihood, impact, points, band):
    assert risks.score(likelihood, impact) == points
    assert risks.band(points) == band
    assert risks.rating(likelihood, impact) == {
        "likelihood": likelihood, "impact": impact, "score": points, "band": band}


def test_every_possible_score_has_exactly_one_band():
    seen = {risks.band(risks.score(lk, im)) for lk in risks.SCALE for im in risks.SCALE}
    assert seen == {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


def test_a_risk_sits_at_its_residual_position_once_one_is_stated():
    r = Risk(inherent_likelihood=5, inherent_impact=5)
    assert risks.position(r) == (5, 5)
    r.residual_likelihood, r.residual_impact = 2, 3
    assert risks.position(r) == (2, 3)


def test_review_state_follows_the_date():
    day = lambda n: TODAY + timedelta(days=n)  # noqa: E731
    assert risks.review_state("CLOSED", day(-400), TODAY) == "CLOSED"
    assert risks.review_state("OPEN", day(-1), TODAY) == "OVERDUE"
    assert risks.review_state("OPEN", None, TODAY) == "OVERDUE"
    assert risks.review_state("OPEN", TODAY, TODAY) == "DUE_SOON"          # due today is not yet late
    assert risks.review_state("IN_TREATMENT", day(14), TODAY) == "DUE_SOON"
    assert risks.review_state("OPEN", day(15), TODAY) == "CURRENT"
    assert risks.review_state("OPEN", TODAY + timedelta(days=risks.REVIEW_EVERY_DAYS["CRITICAL"]), TODAY) == "CURRENT"


def test_the_heat_map_has_25_cells_and_counts_only_open_risks():
    open_risk = Risk(inherent_likelihood=5, inherent_impact=5, residual_likelihood=1, residual_impact=2, status="OPEN")
    closed = Risk(inherent_likelihood=5, inherent_impact=5, status="CLOSED")
    inherent, current = risks.heatmap([open_risk, closed], False), risks.heatmap([open_risk, closed], True)
    assert len(inherent) == len(current) == 25
    cell = lambda cells, lk, im: next(c for c in cells if (c["likelihood"], c["impact"]) == (lk, im))  # noqa: E731
    assert cell(inherent, 5, 5)["count"] == 1 and cell(inherent, 5, 5)["band"] == "CRITICAL"
    assert cell(current, 1, 2)["count"] == 1 and cell(current, 5, 5)["count"] == 0
    assert sum(c["count"] for c in inherent) == 1


# ---- the register ----------------------------------------------------------------------------------------------


def _add(client, org, **kw):
    body = {"title": "Laptop stolen with customer data", "category": "SECURITY", "owner_email": "Owner@A.test",
            "inherent_likelihood": 4, "inherent_impact": 4, **kw}
    return client.post("/risks", json=body, headers=H(org))


def _user(client, org, email, role):
    return {"authorization": "user:" + client.post("/admin/users", json={
        "email": email, "org_id": org, "role": role}).json()["id"]}


def test_adding_a_risk_computes_the_score_sets_a_review_date_and_is_audited(client, bootstrap, db):
    org, _ = bootstrap(client)
    created = _add(client, org)
    assert created.status_code == 201, created.text
    r = created.json()
    assert r["inherent"] == {"likelihood": 4, "impact": 4, "score": 16, "band": "HIGH"}
    assert r["residual"] is None and r["current"]["band"] == "HIGH"
    assert r["owner_email"] == "owner@a.test"  # stored lower case
    assert r["review_every_days"] == 90
    assert date.fromisoformat(r["next_review_date"]) == datetime.now(timezone.utc).date() + timedelta(days=90)
    event = db.query(AuditEvent).filter_by(action="RISK_ADDED", entity=r["id"]).one()
    assert event.after["inherent_likelihood"] == 4 and event.after["owner_email"] == "owner@a.test"
    assert event.actor == f"org:{org}"


def test_the_client_cannot_send_a_score_or_band(client, bootstrap):
    org, _ = bootstrap(client)
    r = _add(client, org, score=1, band="LOW", current={"band": "LOW"}).json()
    assert r["inherent"]["score"] == 16 and r["inherent"]["band"] == "HIGH"
    patched = client.patch(f"/risks/{r['id']}", json={"score": 1, "band": "LOW"}, headers=H(org)).json()
    assert patched["inherent"]["score"] == 16


@pytest.mark.parametrize("bad", [
    {"inherent_likelihood": 0}, {"inherent_impact": 6}, {"title": "no"}, {"owner_email": "not an email"},
    {"category": "NONSENSE"}, {"treatment": "IGNORE"}, {"residual_likelihood": 2},
])
def test_bad_input_is_refused(client, bootstrap, bad):
    org, _ = bootstrap(client)
    assert _add(client, org, **bad).status_code == 422


def test_residual_risk_moves_the_current_position_and_a_change_is_audited_with_before_and_after(client, bootstrap, db):
    org, _ = bootstrap(client)
    r = _add(client, org).json()
    out = client.patch(f"/risks/{r['id']}", headers=H(org), json={
        "treatment": "MITIGATE", "treatment_plan": "Full-disk encryption on every laptop",
        "residual_likelihood": 2, "residual_impact": 3, "status": "IN_TREATMENT"})
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["residual"]["score"] == 6 and body["current"]["band"] == "MEDIUM"
    assert body["inherent"]["band"] == "HIGH"  # the inherent position is never overwritten
    event = db.query(AuditEvent).filter_by(action="RISK_UPDATED", entity=r["id"]).one()
    assert event.before["residual_likelihood"] is None and event.after["residual_likelihood"] == 2
    assert event.before["status"] == "OPEN" and event.after["status"] == "IN_TREATMENT"


def test_a_change_that_alters_nothing_writes_nothing_and_closing_has_its_own_event(client, bootstrap, db):
    org, _ = bootstrap(client)
    r = _add(client, org).json()
    client.patch(f"/risks/{r['id']}", json={"title": r["title"]}, headers=H(org))
    assert db.query(AuditEvent).filter_by(action="RISK_UPDATED").count() == 0
    client.patch(f"/risks/{r['id']}", json={"status": "CLOSED"}, headers=H(org))
    assert db.query(AuditEvent).filter_by(action="RISK_CLOSED", entity=r["id"]).count() == 1
    assert client.get("/risks", headers=H(org)).json()["summary"]["open"] == 0


def test_residual_must_be_stated_as_a_pair_and_cannot_be_half_cleared(client, bootstrap):
    org, _ = bootstrap(client)
    r = _add(client, org, residual_likelihood=2, residual_impact=2).json()
    assert client.patch(f"/risks/{r['id']}", json={"residual_likelihood": None}, headers=H(org)).status_code == 422
    cleared = client.patch(f"/risks/{r['id']}", json={"residual_likelihood": None, "residual_impact": None},
                           headers=H(org))
    assert cleared.status_code == 200 and cleared.json()["residual"] is None
    other = _add(client, org).json()
    assert client.patch(f"/risks/{other['id']}", json={"residual_impact": 2}, headers=H(org)).status_code == 422


def test_a_required_field_cannot_be_blanked(client, bootstrap):
    org, _ = bootstrap(client)
    r = _add(client, org).json()
    for field in ("title", "status", "inherent_impact", "next_review_date", "owner_email"):
        resp = client.patch(f"/risks/{r['id']}", json={field: None}, headers=H(org))
        assert resp.status_code == 422, field


def test_an_overdue_review_is_flagged_and_counted_and_recording_one_resets_it(client, bootstrap, db):
    org, _ = bootstrap(client)
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    r = _add(client, org, next_review_date=yesterday).json()
    listing = client.get("/risks", headers=H(org)).json()
    assert listing["risks"][0]["review_state"] == "OVERDUE" and listing["summary"]["reviews_overdue"] == 1

    assert client.post(f"/risks/{r['id']}/review", json={"note": "ok"}, headers=H(org)).status_code == 422
    done = client.post(f"/risks/{r['id']}/review", headers=H(org),
                       json={"note": "Checked the encryption rollout with IT"})
    assert done.status_code == 200, done.text
    assert done.json()["review_state"] == "CURRENT" and done.json()["last_reviewed_at"]
    event = db.query(AuditEvent).filter_by(action="RISK_REVIEWED", entity=r["id"]).one()
    assert event.reason == "Checked the encryption rollout with IT"
    assert client.get("/risks", headers=H(org)).json()["summary"]["reviews_overdue"] == 0


def test_a_closed_risk_needs_no_review(client, bootstrap):
    org, _ = bootstrap(client)
    r = _add(client, org, status="CLOSED").json()
    assert r["review_state"] == "CLOSED"
    assert client.post(f"/risks/{r['id']}/review", json={"note": "checked it again"}, headers=H(org)).status_code == 409


def test_the_list_is_worst_first_with_closed_last_and_carries_the_heat_map(client, bootstrap):
    org, _ = bootstrap(client)
    _add(client, org, title="Minor thing", inherent_likelihood=1, inherent_impact=1)
    _add(client, org, title="Closed one", inherent_likelihood=5, inherent_impact=5, status="CLOSED")
    _add(client, org, title="Big thing", inherent_likelihood=5, inherent_impact=5)
    body = client.get("/risks", headers=H(org)).json()
    assert [r["title"] for r in body["risks"]] == ["Big thing", "Minor thing", "Closed one"]
    assert body["summary"] == {"open": 2, "by_band": {"CRITICAL": 1, "HIGH": 0, "MEDIUM": 0, "LOW": 1},
                               "reviews_overdue": 0}
    assert len(body["heatmap"]["inherent"]) == 25
    assert [b["band"] for b in body["bands"]] == ["CRITICAL", "HIGH", "MEDIUM", "LOW"]


# ---- tenancy and roles -----------------------------------------------------------------------------------------


def test_another_organisation_sees_nothing_and_cannot_change_anything(client, bootstrap):
    org, _ = bootstrap(client)
    other = client.post("/admin/organizations", json={"name": "Other", "frameworks": ["SOC-2"]}).json()["id"]
    r = _add(client, org).json()
    assert client.get("/risks", headers=H(other)).json()["risks"] == []
    assert client.patch(f"/risks/{r['id']}", json={"status": "CLOSED"}, headers=H(other)).status_code == 404
    assert client.post(f"/risks/{r['id']}/review", json={"note": "looked at it today"}, headers=H(other)).status_code == 404
    assert client.get("/risks", headers=H(org)).json()["risks"][0]["status"] == "OPEN"


def test_linking_controls_checks_they_are_this_organisations_own(client, bootstrap):
    org, _ = bootstrap(client)
    other = client.post("/admin/organizations", json={"name": "Other", "frameworks": ["ISO-27001"]}).json()["id"]
    mine = client.post("/admin/controls", headers=H(org),
                       json={"org_id": org, "framework": "ISO-27001", "clause": "A.5.1"}).json()["id"]
    theirs = client.post("/admin/controls", headers=H(other),
                         json={"org_id": other, "framework": "ISO-27001", "clause": "A.5.1"}).json()["id"]
    assert _add(client, org, control_ids=[theirs]).status_code == 422
    ok = _add(client, org, control_ids=[mine, mine]).json()
    assert ok["controls"] == [{"id": mine, "framework": "ISO-27001", "clause": "A.5.1"}]
    assert client.patch(f"/risks/{ok['id']}", json={"control_ids": [theirs]}, headers=H(org)).status_code == 422


def test_a_viewer_reads_everything_and_changes_nothing(client, bootstrap):
    org, _ = bootstrap(client)
    r = _add(client, org).json()
    viewer = _user(client, org, "v@a.test", "COMPLIANCE_VIEWER")
    seen = client.get("/risks", headers=viewer).json()
    assert [x["id"] for x in seen["risks"]] == [r["id"]] and (seen["can_write"], seen["can_write_all"]) == (False, False)
    assert client.post("/risks", json={"title": "Nope", "inherent_likelihood": 1, "inherent_impact": 1},
                       headers=viewer).status_code == 403
    assert client.patch(f"/risks/{r['id']}", json={"status": "CLOSED"}, headers=viewer).status_code == 403
    assert client.post("/risks/draft", json={"title": "Some risk"}, headers=viewer).status_code == 403


def test_a_control_owner_sees_and_updates_only_their_own_risks(client, bootstrap, db):
    org, _ = bootstrap(client)
    owner = _user(client, org, "owner@a.test", "CONTROL_OWNER")
    mine = _add(client, org, owner_email="Owner@a.test").json()
    theirs = _add(client, org, title="Someone else's risk", owner_email="boss@a.test").json()

    listing = client.get("/risks", headers=owner).json()
    assert [r["id"] for r in listing["risks"]] == [mine["id"]]
    assert (listing["can_write"], listing["can_write_all"]) == (True, False)
    ok = client.patch(f"/risks/{mine['id']}", json={"treatment": "ACCEPT", "status": "IN_TREATMENT"}, headers=owner)
    assert ok.status_code == 200 and ok.json()["treatment"] == "ACCEPT"
    assert db.query(AuditEvent).filter_by(action="RISK_UPDATED", entity=mine["id"]).one().actor.startswith("user:")

    # a risk that is not theirs is answered as absent, and the attempt is recorded
    assert client.patch(f"/risks/{theirs['id']}", json={"status": "CLOSED"}, headers=owner).status_code == 404
    assert client.post(f"/risks/{theirs['id']}/review", json={"note": "I looked at it"}, headers=owner).status_code == 404
    denied = db.query(AuditEvent).filter_by(action="AUTHORIZATION_DENIED").all()
    assert any(e.detail["resource"] == f"risk:{theirs['id']}" for e in denied)

    # only an admin adds risks, reassigns owners and links controls
    assert client.post("/risks", json={"title": "New one", "inherent_likelihood": 1, "inherent_impact": 1},
                       headers=owner).status_code == 403
    assert client.patch(f"/risks/{mine['id']}", json={"owner_email": "other@a.test"}, headers=owner).status_code == 403
    assert client.patch(f"/risks/{mine['id']}", json={"control_ids": []}, headers=owner).status_code == 403


def test_an_auditor_is_refused(client, bootstrap):
    org, engagement = bootstrap(client)
    _add(client, org)
    assert client.get("/risks", headers={"authorization": f"auditor:{engagement}"}).status_code == 403


# ---- the model only drafts -------------------------------------------------------------------------------------


class Drafter:
    model = "stub-gemma"

    def __init__(self, reply, available=True):
        self.reply, self._available, self.prompts = reply, available, []

    def available(self):
        return self._available

    def complete_json(self, system, user):
        self.prompts.append((system, user))
        return self.reply


def test_a_draft_is_wording_only_stores_nothing_and_cannot_carry_a_score(client, bootstrap, monkeypatch, db):
    org, _ = bootstrap(client)
    gateway = Drafter(json.dumps({"description": "A stolen laptop exposes customer files.",
                                  "treatment_plan": "Encrypt disks.\nEnrol laptops in device management.",
                                  "score": 25, "likelihood": 5, "impact": 5, "band": "CRITICAL"}))
    monkeypatch.setattr(ingest, "_tool_gateway", lambda: gateway)
    resp = client.post("/risks/draft", json={"title": "Laptop stolen", "context": "we have 20 laptops"}, headers=H(org))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"description", "treatment_plan", "model", "notice"}
    assert "edit" in body["notice"].lower() and body["model"] == "stub-gemma"
    assert "score" in gateway.prompts[0][0].lower()  # the model is told not to give one
    assert db.query(Risk).count() == 0
    event = db.query(AuditEvent).filter_by(action="RISK_DRAFTED").one()
    assert event.detail == {"title": "Laptop stolen", "model": "stub-gemma"}


def test_a_draft_with_the_model_offline_or_useless_is_a_clear_error(client, bootstrap, monkeypatch):
    org, _ = bootstrap(client)
    monkeypatch.setattr(ingest, "_tool_gateway", lambda: Drafter("", available=False))
    assert client.post("/risks/draft", json={"title": "Laptop stolen"}, headers=H(org)).status_code == 503
    monkeypatch.setattr(ingest, "_tool_gateway", lambda: Drafter("not json at all"))
    assert client.post("/risks/draft", json={"title": "Laptop stolen"}, headers=H(org)).status_code == 502
    monkeypatch.setattr(ingest, "_tool_gateway", lambda: Drafter("[1, 2, 3]"))
    assert client.post("/risks/draft", json={"title": "Laptop stolen"}, headers=H(org)).status_code == 502


# ---- the weekly report -----------------------------------------------------------------------------------------


def test_the_weekly_report_counts_risks_and_names_none(client, bootstrap):
    org, _ = bootstrap(client)
    with Session(db_module.engine) as s:
        assert reports.build(s, s.query(Organization).first())["risks"]["open"] == 0
        assert "Risks:" not in reports.text(reports.build(s, s.query(Organization).first()))
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    _add(client, org, title="Secret acquisition leak", next_review_date=yesterday)
    _add(client, org, title="Minor", inherent_likelihood=1, inherent_impact=1)
    _add(client, org, title="Done", status="CLOSED")
    with Session(db_module.engine) as s:
        report = reports.build(s, s.query(Organization).first())
    assert report["risks"] == {"open": 2, "high_or_critical": 1, "reviews_overdue": 1}
    assert "Risks: 2 open, 1 high or critical, 1 reviews overdue." in reports.text(report)
    assert "- High or critical: 1" in reports.markdown(report)
    blob = (json.dumps(report) + reports.text(report) + reports.markdown(report)).lower()
    assert "secret acquisition" not in blob and "owner@a.test" not in blob
