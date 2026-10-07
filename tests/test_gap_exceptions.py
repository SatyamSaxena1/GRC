"""Gap exceptions that cannot quietly widen (ADR-021): requested by the auditee, decided by an
auditor, never by the requester, and retired automatically by expiry, a rule change or a change
in the gap's value."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import exceptions as exc_rules
from app.collectors import github_change_control as gcc
from app.models import AuditEvent, GapException
from app.routers import connectors

# Small local copies of helpers from test_change_control.py and test_firm.py: tests/ is not a
# package, so test modules cannot import each other on CI.
HEAD = "abc123"
PROTECTED = {"enabled": True, "required_approving_reviews": 1, "dismiss_stale_reviews": True,
             "enforce_admins": True, "allow_force_pushes": False}


def _pr(reviews=()):
    return {"number": 1, "author": {"login": "alice", "is_bot": False}, "head_sha": HEAD,
            "reviews": [{"user": {"login": who, "is_bot": False}, "state": "APPROVED",
                         "commit_id": HEAD, "submitted_at": "2026-10-01T00:00:00Z"} for who in reviews],
            "commits": [{"sha": HEAD, "message": "change", "author_login": "alice", "committer_login": "web-flow"}],
            "checks": [{"name": "ci", "conclusion": "success"}]}


def _approved():
    return _pr(reviews=["bob"])


def as_user(user_id, engagement_id=None):
    headers = {"authorization": f"user:{user_id}"}
    if engagement_id:
        headers["x-engagement-id"] = engagement_id
    return headers


def firm_with_admin(client):
    firm = client.post("/admin/audit-firms", json={"name": "Gemba"}).json()["id"]
    admin = client.post("/admin/users", json={"email": "admin@gemba.test", "audit_firm_id": firm,
                                              "role": "FIRM_ADMIN"}).json()["id"]
    return firm, admin


def auditor(client, firm_id):
    return client.post("/admin/users", json={"email": "krishna@gemba.test", "audit_firm_id": firm_id,
                                             "role": "AUDITOR"}).json()["id"]


def request_onboarding(client, firm_id, frameworks=("SOC-2",)):
    return client.post("/firm/onboarding-requests", json={
        "audit_firm_id": firm_id, "org_name": "Acme Corp", "contact_email": "ciso@acme.test",
        "frameworks": list(frameworks)}).json()["id"]

SOON = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
WHY = "Solo developer; every merge reviewed after a 24h cooling-off period (ADR-019)."


class _Response:
    content = b"{}"

    def __init__(self, attributes):
        self._a = attributes

    def raise_for_status(self):
        return None

    def json(self):
        return {"attributes": self._a}


def _snapshot(unapproved: int):
    pulls = [_approved()] + [_pr(reviews=[]) for _ in range(unapproved)]
    return gcc.summarize([{"protection": PROTECTED, "pulls": pulls, "default_commits": []}])


def _sync(client, monkeypatch, org_id, unapproved=4):
    monkeypatch.setenv(connectors._env_key("github", "URL"), "https://collector.test/github")
    monkeypatch.setattr(connectors.requests, "get", lambda url, **_: _Response(_snapshot(unapproved)))
    assert client.post("/connectors/github/sync", headers={"authorization": f"org:{org_id}"}).status_code == 202


def _gap(client, org_id):
    gaps = client.get("/gaps", headers={"authorization": f"org:{org_id}"}, params={"status": "OPEN"}).json()
    return next(g for g in gaps if g["framework"] == "SOC-2" and g["attribute"] == "merges_without_independent_approval")


@pytest.fixture()
def setup(client, bootstrap, monkeypatch):
    org_id, engagement_id = bootstrap(client, frameworks=["SOC-2"])
    _sync(client, monkeypatch, org_id)
    return org_id, engagement_id, _gap(client, org_id)


def _request(client, org_id, gap_id, **overrides):
    body = {"justification": WHY, "compensating_control": "24h cooling-off, logged", "expires_at": SOON}
    return client.post(f"/gaps/{gap_id}/exceptions", headers={"authorization": f"org:{org_id}"},
                       json={**body, **overrides})


def _approve(client, engagement_id, exception_id, note="Accepted for this period"):
    return client.post(f"/exceptions/{exception_id}/approve",
                       headers={"authorization": f"auditor:{engagement_id}"}, json={"note": note})


def test_an_approved_exception_waives_exactly_its_gap(client, setup):
    org_id, engagement_id, gap = setup
    assert gap["waived"] is False
    exc = _request(client, org_id, gap["id"]).json()
    assert exc["status"] == "REQUESTED" and exc["state"] == "REQUESTED"
    assert _gap(client, org_id)["waived"] is False          # requested is not accepted

    assert _approve(client, engagement_id, exc["id"]).json()["state"] == "ACTIVE"
    waived = _gap(client, org_id)
    assert waived["waived"] is True and waived["status"] == "OPEN"   # the gap itself is untouched
    assert waived["exception"]["id"] == exc["id"]
    others = [g for g in client.get("/gaps", headers={"authorization": f"org:{org_id}"}).json()
              if g["id"] != gap["id"]]
    assert not any(g["waived"] for g in others)


def test_a_bigger_number_is_not_covered_by_the_accepted_one(client, setup, monkeypatch):
    org_id, engagement_id, gap = setup
    exc = _request(client, org_id, gap["id"]).json()
    _approve(client, engagement_id, exc["id"])
    _sync(client, monkeypatch, org_id, unapproved=5)     # a new snapshot: 5, not 4
    assert _gap(client, org_id)["waived"] is False


def test_changing_the_rule_retires_the_exception(client, setup, monkeypatch):
    org_id, engagement_id, gap = setup
    exc = _request(client, org_id, gap["id"]).json()
    _approve(client, engagement_id, exc["id"])
    monkeypatch.setattr(exc_rules, "rule_hash", lambda *a: "a-different-rule")
    assert _gap(client, org_id)["waived"] is False
    states = {e["id"]: e["state"] for e in client.get("/exceptions", headers={"authorization": f"org:{org_id}"}).json()}
    assert states[exc["id"]] == "RULE_CHANGED"


def test_a_rule_changed_after_the_request_cannot_be_approved(client, setup, monkeypatch):
    from app.routers import exceptions as exc_router
    org_id, engagement_id, gap = setup
    exc = _request(client, org_id, gap["id"]).json()
    monkeypatch.setattr(exc_router, "rule_hash", lambda *a: "a-different-rule")
    assert _approve(client, engagement_id, exc["id"]).status_code == 409


def test_an_expired_exception_stops_applying(client, setup, db):
    org_id, engagement_id, gap = setup
    exc = _request(client, org_id, gap["id"]).json()
    _approve(client, engagement_id, exc["id"])
    row = db.get(GapException, exc["id"])
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert _gap(client, org_id)["waived"] is False


def test_expiry_must_be_set_and_bounded(client, setup):
    org_id, _, gap = setup
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    too_far = (datetime.now(timezone.utc) + timedelta(days=exc_rules.MAX_DAYS + 1)).isoformat()
    assert _request(client, org_id, gap["id"], expires_at=past).status_code == 422
    assert _request(client, org_id, gap["id"], expires_at=too_far).status_code == 422
    assert _request(client, org_id, gap["id"], justification="because").status_code == 422


def test_only_the_auditee_requests_and_only_an_auditor_decides(client, setup):
    org_id, engagement_id, gap = setup
    as_auditor = {"authorization": f"auditor:{engagement_id}"}
    assert client.post(f"/gaps/{gap['id']}/exceptions", headers=as_auditor,
                       json={"justification": WHY, "expires_at": SOON}).status_code == 403
    exc = _request(client, org_id, gap["id"]).json()
    assert client.post(f"/exceptions/{exc['id']}/approve", headers={"authorization": f"org:{org_id}"},
                       json={"note": "self-service"}).status_code == 403
    assert _approve(client, engagement_id, exc["id"]).status_code == 200
    assert _approve(client, engagement_id, exc["id"]).status_code == 409     # decided once


def test_the_requester_can_never_decide_their_own_exception(client, monkeypatch):
    """Requester and approver sit on different sides, so this cannot normally happen; the check
    still holds if the two ever share an identity."""
    firm_id, admin_id = firm_with_admin(client)
    auditor_id = auditor(client, firm_id)
    approved = client.post(f"/firm/onboarding-requests/{request_onboarding(client, firm_id, frameworks=('SOC-2',))}/approve",
                           headers=as_user(admin_id), json={}).json()
    org_id, engagement_id = approved["org_id"], approved["engagement_id"]
    client.post(f"/firm/engagements/{engagement_id}/auditors", headers=as_user(admin_id), json={"user_id": auditor_id})
    _sync(client, monkeypatch, org_id)
    exc_id = _request(client, org_id, _gap(client, org_id)["id"]).json()["id"]

    from sqlalchemy.orm import Session

    from app import db as db_module
    with Session(db_module.engine) as s:
        s.get(GapException, exc_id).requested_by_user_id = auditor_id   # forge a shared identity
        s.commit()
    refused = client.post(f"/exceptions/{exc_id}/approve", headers=as_user(auditor_id, engagement_id),
                          json={"note": "mine"})
    assert refused.status_code == 403 and "requested" in refused.json()["detail"]


def test_revoking_ends_the_waiver_and_everything_is_on_the_record(client, setup, db):
    org_id, engagement_id, gap = setup
    exc = _request(client, org_id, gap["id"]).json()
    _approve(client, engagement_id, exc["id"])
    assert client.post(f"/exceptions/{exc['id']}/revoke", headers={"authorization": f"org:{org_id}"},
                       json={"note": "cooling-off stopped"}).json()["state"] == "REVOKED"
    assert _gap(client, org_id)["waived"] is False
    actions = [e.action for e in db.query(AuditEvent).filter_by(entity=exc["id"]).order_by(AuditEvent.seq)]
    assert actions == ["EXCEPTION_REQUESTED", "EXCEPTION_APPROVED", "EXCEPTION_REVOKED"]


def test_another_tenant_cannot_see_or_touch_an_exception(client, setup, bootstrap):
    org_id, engagement_id, gap = setup
    exc = _request(client, org_id, gap["id"]).json()
    other_org, other_engagement = bootstrap(client, frameworks=["SOC-2"])
    assert client.get("/exceptions", headers={"authorization": f"org:{other_org}"}).json() == []
    assert _approve(client, other_engagement, exc["id"]).status_code == 404
    assert _request(client, other_org, gap["id"]).status_code == 404
