"""Activity, control history and task history carry a human display name beside the raw actor
label; the label stays the record, the display name is only for reading."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app import db as db_module
from app.actor_names import resolve_actors
from app.models import AuditFirm, EvidenceControlLink, User
from app.routers import connectors

REASON = "reviewed the signed policy and the review log; accepting it with a compensating control"


def test_every_label_shape_resolves_and_unknown_ones_pass_through(client, bootstrap):
    org_id, engagement_id = bootstrap(client)
    with Session(db_module.engine) as s:
        firm = s.query(AuditFirm).first()
        s.add_all([User(id="u-org", email="owner@acme.test", org_id=org_id, role="ORG_ADMIN"),
                   User(id="u-aud", email="aud@bigfour.test", audit_firm_id=firm.id, role="AUDITOR")])
        s.commit()
        names = resolve_actors(s, [
            "user:u-org", f"auditor:{engagement_id}/user:u-aud", f"auditor:{engagement_id}", f"org:{org_id}",
            f"firm:{firm.id}", "admin", "system", "system:monitor", "monitor:retry-extractions",
            "user:missing", "something-else", ""])
    assert names["user:u-org"] == "owner@acme.test"
    assert names[f"auditor:{engagement_id}/user:u-aud"] == "aud@bigfour.test (auditor, BigFour)"
    assert names[f"auditor:{engagement_id}"] == "Auditor · BigFour"
    assert names[f"org:{org_id}"] == "Acme (organisation)"
    assert names[f"firm:{firm.id}"] == "BigFour (firm)"
    assert (names["admin"], names["system"], names["system:monitor"]) == ("Operator", "System", "Scheduled monitor")
    assert names["monitor:retry-extractions"] == "Scheduled monitor"
    assert names["user:missing"] == "user:missing" and names["something-else"] == "something-else"
    assert "" not in names


def test_activity_and_control_history_show_who_in_words_and_keep_the_raw_label(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    with Session(db_module.engine) as s:
        link = s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id, framework="PCI-DSS").first()
        link_id, framework, clause = link.id, link.framework, link.clause
    client.post(f"/audit/links/{link_id}/lock", headers={"authorization": f"auditor:{engagement_id}"},
                json={"verdict": "COMPLIANT", "reason": REASON})
    org = {"authorization": f"org:{org_id}"}

    locked = next(e for e in client.get("/activity", headers=org).json() if e["action"] == "CONTROL_LOCKED")
    assert locked["actor"] == f"auditor:{engagement_id}" and locked["actor_display"] == "Auditor · BigFour"
    assert locked["reason"] == REASON and locked["after"]["locked"] is True and locked["before"]["locked"] is False

    controls = client.get("/controls", headers=org).json()
    control_id = next(c["id"] for c in controls if (c["framework"], c["clause"]) == (framework, clause))
    history = client.get(f"/controls/{control_id}/history", headers=org).json()
    assert {e["actor_display"] for e in history if e["action"] == "CONTROL_LOCKED"} == {"Auditor · BigFour"}


def test_connector_run_history_lists_runs_newest_first_and_is_org_scoped(client, bootstrap, monkeypatch):
    org_id, _ = bootstrap(client)
    other_org, _ = bootstrap(client)
    monkeypatch.setenv("DPDP_GITHUB_COLLECTOR_URL", "http://collector.test/github")
    reply = {"attributes": {"repositories_in_scope": 2, "merges_in_period": 5}}

    class R:
        content = json.dumps(reply).encode()
        def raise_for_status(self): pass
        def json(self): return reply

    monkeypatch.setattr(connectors.requests, "get", lambda url, **kw: R())
    for declared in (None, {"truncated": True}):
        reply = {**reply, "collection": declared} if declared else reply
        with Session(db_module.engine) as s:
            connectors.sync_connector_for_org(s, org_id, "system:test", "", "github")

    runs = client.get("/connectors/github/runs", headers={"authorization": f"org:{org_id}"}).json()
    assert [r["status"] for r in runs] == ["PARTIAL", "COMPLETE"]
    assert "truncated" in runs[0]["signals"][0] and runs[0]["expectation"] == "REPORTED+HISTORY"
    assert client.get("/connectors/github/runs", headers={"authorization": f"org:{other_org}"}).json() == []
    assert client.get("/connectors/nope/runs", headers={"authorization": f"org:{org_id}"}).status_code == 404
