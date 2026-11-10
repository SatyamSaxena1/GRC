"""The first-week checklist and time-to-first-verdict (ADR-058).

The rule worth proving is that nothing on the checklist is hand-ticked: every step reads data that exists, so doing the
work ticks it and undoing the work un-ticks it, and only an organisation admin is shown it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app import db as db_module
from app.models import CollectionRun, Connection, Organization

STEPS = ("source", "policy", "scope", "people", "trust", "owner")


def _admin(client, org_id, email="admin@acme.test"):
    uid = client.post("/admin/users", json={"email": email, "org_id": org_id, "role": "ORG_ADMIN"}).json()["id"]
    return {"authorization": f"user:{uid}"}


def _get(client, h):
    body = client.get("/onboarding", headers=h).json()
    return {s["id"]: s["done"] for s in body["steps"]}, body


def _run(org_id, source, status, days_ago):
    with Session(db_module.engine) as s:
        s.add(CollectionRun(org_id=org_id, source=source, status=status, expectation="NONE",
                            started_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_ago)))
        s.commit()


def test_a_new_organisation_starts_with_nothing_done(client, bootstrap):
    org_id, _ = bootstrap(client)
    done, body = _get(client, _admin(client, org_id))
    assert done == dict.fromkeys(STEPS, False)
    assert (body["done"], body["total"], body["complete"]) == (0, 5, False)
    assert [s["id"] for s in body["steps"] if s["optional"]] == ["scope"]  # only if needed: it never blocks finishing
    assert body["first_verdict"] == {"at": None, "minutes_from_start": None}
    assert all(s["link"].startswith("/") for s in body["steps"])  # each step names the page to do it on


def test_each_step_is_read_from_real_data_and_undoing_it_unticks_it(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    h = _admin(client, org_id)

    upload(client, org_id)  # a POLICY: the first verdict comes from this
    assert _get(client, h)[0]["policy"] is True

    # one person invited is not two; the admin does not count as someone they invited
    client.post("/admin/users", headers=h, json={"email": "a@acme.test", "role": "CONTROL_OWNER"})
    done, body = _get(client, h)
    assert done["people"] is False and "1 of 2" in next(s for s in body["steps"] if s["id"] == "people")["hint"]
    mate = client.post("/admin/users", headers=h, json={"email": "b@acme.test", "role": "COMPLIANCE_VIEWER"}).json()["id"]
    assert _get(client, h)[0]["people"] is True
    client.patch(f"/admin/users/{mate}", headers=h, json={"active": False})  # someone switched off is not a person invited
    assert _get(client, h)[0]["people"] is False

    assert client.post("/trust-settings/publish", headers=h).status_code == 200
    assert _get(client, h)[0]["trust"] is True
    client.post("/trust-settings/unpublish", headers=h)
    assert _get(client, h)[0]["trust"] is False  # taking the page down un-ticks it: there is no stored flag

    with Session(db_module.engine) as s:  # a chat webhook is a place to send alerts, not a source of evidence
        s.add(Connection(org_id=org_id, kind="CHAT_WEBHOOK", config_encrypted="x"))
        s.commit()
    assert _get(client, h)[0]["source"] is False
    with Session(db_module.engine) as s:
        s.add(Connection(org_id=org_id, kind="AWS_PUSH", config_encrypted="x"))
        s.commit()
    assert _get(client, h)[0]["source"] is True

    control = client.get("/controls", headers=h).json()[0]["id"]
    owner = client.post("/admin/users", headers=h, json={"email": "c@acme.test", "role": "CONTROL_OWNER"}).json()["id"]
    assert _get(client, h)[0]["owner"] is False
    assert client.post("/admin/control-assignments", json={"org_control_id": control, "user_id": owner}).status_code == 200
    assert _get(client, h)[0]["owner"] is True


def test_it_is_complete_when_the_required_steps_are_done_whatever_the_optional_one_says(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    h = _admin(client, org_id)
    upload(client, org_id)
    for i in range(2):
        client.post("/admin/users", headers=h, json={"email": f"p{i}@acme.test", "role": "CONTROL_OWNER"})
    client.post("/trust-settings/publish", headers=h)
    with Session(db_module.engine) as s:
        s.add(Connection(org_id=org_id, kind="GITHUB_CHANGE_CONTROL", config_encrypted="x"))
        s.commit()
    client.post("/admin/control-assignments", json={
        "org_control_id": client.get("/controls", headers=h).json()[0]["id"],
        "user_id": client.get("/admin/users", headers=h).json()[1]["id"]})
    done, body = _get(client, h)
    assert done["scope"] is False  # nothing has run, so nothing was settled: optional, and not blocking
    assert body["complete"] is True and (body["done"], body["total"]) == (5, 5)


def test_a_partial_collection_waits_for_a_person_and_a_clean_run_settles_it(client, bootstrap):
    org_id, _ = bootstrap(client)
    h = _admin(client, org_id)
    _run(org_id, "github", "PARTIAL", 2)
    done, body = _get(client, h)
    assert done["scope"] is False and "1 waiting" in next(s for s in body["steps"] if s["id"] == "scope")["hint"]
    _run(org_id, "github", "COMPLETE", 0)  # a later complete run (a real one, or an accepted scope, ADR-046)
    assert _get(client, h)[0]["scope"] is True
    _run(org_id, "aws", "PARTIAL", 0)  # another source that has not been settled
    assert _get(client, h)[0]["scope"] is False


@pytest.mark.parametrize("role", ["CONTROL_OWNER", "COMPLIANCE_VIEWER"])
def test_only_an_organisation_admin_is_shown_it(client, bootstrap, role):
    org_id, engagement_id = bootstrap(client)
    uid = client.post("/admin/users", json={"email": "x@acme.test", "org_id": org_id, "role": role}).json()["id"]
    assert client.get("/onboarding", headers={"authorization": f"user:{uid}"}).status_code == 403
    assert client.get("/onboarding", headers={"authorization": f"auditor:{engagement_id}"}).status_code == 403


def test_one_organisations_work_does_not_tick_anothers(client, bootstrap, upload):
    a, _ = bootstrap(client)
    b, _ = bootstrap(client)
    upload(client, a)
    client.post("/trust-settings/publish", headers=_admin(client, a))
    done, _ = _get(client, _admin(client, b, "admin@b.test"))
    assert done == dict.fromkeys(STEPS, False)


def test_time_to_first_verdict_is_started_at_creation_and_stopped_once(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    h = _admin(client, org_id)
    with Session(db_module.engine) as s:
        org = s.get(Organization, org_id)
        assert org.created_at is not None and org.first_verdict_at is None  # the clock starts when the organisation exists

    upload(client, org_id)
    with Session(db_module.engine) as s:
        first = s.get(Organization, org_id).first_verdict_at
    assert first is not None
    assert _get(client, h)[1]["first_verdict"]["minutes_from_start"] == 0  # seconds in a test, so rounds to 0

    upload(client, org_id, content=b"a second, different policy", name="second.txt")
    with Session(db_module.engine) as s:
        assert s.get(Organization, org_id).first_verdict_at == first  # the first one stands

    with Session(db_module.engine) as s:  # the figure is the gap between the two stamps
        org = s.get(Organization, org_id)
        org.created_at = org.first_verdict_at - timedelta(minutes=17, seconds=20)
        s.commit()
    assert _get(client, h)[1]["first_verdict"]["minutes_from_start"] == 17
    listed = next(o for o in client.get("/admin/organizations").json() if o["id"] == org_id)  # the operator reads it too
    assert listed["minutes_to_first_verdict"] == 17 and listed["first_verdict_at"] is not None


def test_an_organisation_that_predates_the_clock_has_no_figure_rather_than_an_invented_one(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    with Session(db_module.engine) as s:
        s.get(Organization, org_id).created_at = None  # what every row that existed before ADR-058 looks like
        s.commit()
    upload(client, org_id)
    assert _get(client, _admin(client, org_id))[1]["first_verdict"]["minutes_from_start"] is None
    with Session(db_module.engine) as s:
        assert s.get(Organization, org_id).first_verdict_at is not None  # the verdict is still stamped


@pytest.mark.model_unavailable
def test_a_run_that_read_nothing_is_not_a_first_verdict(client, bootstrap, upload):
    """With the model down every verdict rests on no facts (ADR-004), so it must not stop the activation clock."""
    org_id, _ = bootstrap(client)
    upload(client, org_id)
    with Session(db_module.engine) as s:
        assert s.get(Organization, org_id).first_verdict_at is None


def test_a_sign_in_naming_an_organisation_that_is_not_here_is_a_404_not_a_crash(client):
    ghost = {"authorization": "org:no-such-organisation"}
    assert client.get("/onboarding", headers=ghost).status_code == 404
    assert client.get("/notifications", headers=ghost).status_code == 200  # the feed just has nothing in it
