"""Auditor-only AI nutshell: field-level redaction, not object-level (see
docs/adr/012-auditor-only-ai-nutshell.md). The auditee must never see the key,
not just an empty value — that distinction is what the tests check.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import db as db_module
from app import service
from app.ai.schemas import ExtractedField, ExtractionRun
from app.models import OrgControl


def controls_for(org_id):
    with Session(db_module.engine) as s:
        return {(c.framework, c.clause): c.id
                for c in s.query(OrgControl).filter_by(org_id=org_id)}


def test_nutshell_present_for_auditor_absent_for_auditee(client, bootstrap, upload, monkeypatch):
    def fake_extract(text, names, method="native_text", gateway=None):
        # Only set the one scalar attribute a real requirement checks; leaving
        # every other requested attribute null avoids feeding a list-typed
        # attribute (systems_covered, etc.) a scalar and breaking quality scoring.
        values = {"password_min_length": 8}
        return ExtractionRun(
            fields={n: ExtractedField(value=values.get(n), confidence=1.0) for n in names},
            model="stub", provider="stub", status="OK",
        )

    def fake_nutshell(framework, clause, title, verdict, gaps, fields, gateway=None):
        return "TEST NUTSHELL: verdict explained in one sentence."

    monkeypatch.setattr(service, "extract_attributes", fake_extract)
    monkeypatch.setattr(service, "generate_nutshell", fake_nutshell)

    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]
    control_id = next(iter(controls_for(org_id).values()))

    as_org = client.get(f"/controls/{control_id}", headers={"authorization": f"org:{org_id}"}).json()
    as_auditor = client.get(f"/controls/{control_id}",
                            headers={"authorization": f"auditor:{engagement_id}"}).json()

    assert all("nutshell" not in link for link in as_org["links"])
    assert any(link.get("nutshell") == "TEST NUTSHELL: verdict explained in one sentence."
              for link in as_auditor["links"])

    # Same redaction on the evidence-scoped read.
    org_eval = client.get(f"/evidence/{evidence_id}/evaluations",
                          headers={"authorization": f"org:{org_id}"}).json()
    auditor_eval = client.get(f"/evidence/{evidence_id}/evaluations",
                              headers={"authorization": f"auditor:{engagement_id}"}).json()
    assert all("nutshell" not in link for link in org_eval)
    assert any("nutshell" in link for link in auditor_eval)


def test_nutshell_empty_but_pipeline_still_ready_when_model_unavailable(client, bootstrap, upload):
    """No StubGateway here — the real (unconfigured, unreachable in CI) OllamaGateway
    reports unavailable, exactly as it does for extraction itself."""
    org_id, engagement_id = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]

    status = client.get(f"/evidence/{evidence_id}/status",
                        headers={"authorization": f"org:{org_id}"}).json()
    assert status["status"] in ("READY", "NEEDS_REVIEW")

    control_id = next(iter(controls_for(org_id).values()))
    as_auditor = client.get(f"/controls/{control_id}",
                            headers={"authorization": f"auditor:{engagement_id}"}).json()
    for link in as_auditor["links"]:
        assert link.get("nutshell", "") == ""
