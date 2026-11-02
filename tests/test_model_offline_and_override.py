"""Two trust fixes: a run that read nothing raises no gaps or tasks, and an auditor who
overrides the rules must say why."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app import db as db_module, service
from app.ai.schemas import ExtractedField, ExtractionRun
from app.models import AuditEvent, EvidenceControlLink, GapRow, TaskRow

GOOD = "reviewed the signed policy and the access review log; the missing items are covered elsewhere"


def count(model):
    with Session(db_module.engine) as s:
        return s.query(model).count()


@pytest.mark.model_unavailable
def test_a_run_that_read_nothing_raises_no_gaps_or_tasks_but_keeps_the_flagged_verdicts(client, bootstrap, upload):
    org_id, _ = bootstrap(client)  # no model in the test env: extraction is UNAVAILABLE
    evidence_id = upload(client, org_id).json()["evidence_id"]
    headers = {"authorization": f"org:{org_id}"}

    detail = client.get(f"/evidence/{evidence_id}", headers=headers).json()
    assert detail["status"] == "NEEDS_REVIEW" and detail["links"]
    assert all(l["verdict"] == "FAIL" for l in detail["links"])
    assert count(GapRow) == 0 and count(TaskRow) == 0
    assert client.get("/analytics/reuse", headers=headers).json()["effort_hours_saved"] == 0
    assert client.get("/gaps", headers=headers).json() == []


@pytest.mark.model_unavailable
def test_the_real_gaps_and_tasks_appear_once_the_model_is_back(client, bootstrap, upload, monkeypatch):
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    assert count(GapRow) == 0

    monkeypatch.setattr(service, "read_document", lambda filename, content, gateway=None: ("text", "native_text"))
    monkeypatch.setattr(service, "extract_attributes", lambda text, names, method="native_text", gateway=None: ExtractionRun(
        fields={n: ExtractedField(value=8 if n == "password_min_length" else None,
                                  confidence=0.9 if n == "password_min_length" else None,
                                  extraction_method="native_text" if n == "password_min_length" else "none")
                for n in names},
        model="stub", provider="stub", prompt_template_version="stub:v1"))
    assert client.post(f"/evidence/{evidence_id}/reprocess", headers={"authorization": f"org:{org_id}"}).status_code == 202
    assert count(GapRow) > 0 and count(TaskRow) > 0


@pytest.fixture()
def failing_link(client, bootstrap, upload):
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    with Session(db_module.engine) as s:
        link_id = s.query(EvidenceControlLink).filter_by(evidence_id=evidence_id).first().id
    return client, org_id, link_id, {"authorization": f"auditor:{engagement_id}"}


@pytest.mark.parametrize("path", ["verdict", "lock"])
@pytest.mark.parametrize("reason", ["", "ok", "see above", "two words"])
def test_overriding_the_rules_without_a_reason_is_refused_and_changes_nothing(failing_link, path, reason):
    client, _, link_id, headers = failing_link
    resp = client.post(f"/audit/links/{link_id}/{path}", headers=headers, json={"verdict": "COMPLIANT", "reason": reason})
    assert resp.status_code == 422 and "FAIL" in resp.json()["detail"]
    with Session(db_module.engine) as s:
        link = s.get(EvidenceControlLink, link_id)
        assert not link.locked and link.auditor_verdict is None and link.verdict == "FAIL"


@pytest.mark.parametrize("path", ["verdict", "lock"])
def test_an_override_with_a_reason_locks_and_the_trail_says_it_was_an_override(failing_link, path):
    client, _, link_id, headers = failing_link
    assert client.post(f"/audit/links/{link_id}/{path}", headers=headers,
                       json={"verdict": "COMPLIANT", "reason": GOOD}).status_code == 200
    with Session(db_module.engine) as s:
        locked = s.query(AuditEvent).filter_by(action="CONTROL_LOCKED").one()
        assert locked.detail["overrides_engine_verdict"] == "FAIL" and locked.reason == GOOD
        assert locked.detail["engine_verdict"] == "FAIL"


def test_agreeing_with_the_rules_needs_no_reason(failing_link):
    client, _, link_id, headers = failing_link
    assert client.post(f"/audit/links/{link_id}/verdict", headers=headers,
                       json={"verdict": "NON_COMPLIANT"}).status_code == 200


def test_the_control_page_keeps_the_rules_verdict_beside_the_auditors(failing_link):
    client, org_id, link_id, headers = failing_link
    client.post(f"/audit/links/{link_id}/lock", headers=headers, json={"verdict": "COMPLIANT", "reason": GOOD})
    with Session(db_module.engine) as s:
        link = s.get(EvidenceControlLink, link_id)
        framework, clause = link.framework, link.clause
    controls = client.get("/controls", headers={"authorization": f"org:{org_id}"}).json()
    control_id = next(c["id"] for c in controls if (c["framework"], c["clause"]) == (framework, clause))
    row = client.get(f"/controls/{control_id}", headers={"authorization": f"org:{org_id}"}).json()["links"][0]
    assert row["verdict"] == "COMPLIANT" and row["engine_verdict"] == "FAIL"
