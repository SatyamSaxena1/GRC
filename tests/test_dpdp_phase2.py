"""DPDP Phase 2: the document duties sit on the AI-assessed lane (ADR-069); nothing with a fixed rule moved."""

from __future__ import annotations

import json

from app.content.load import load
from test_ai_assessments import Stub, _setup

DPDP = load().framework("DPDP").requirements
BY = {r.clause: r for r in DPDP}
NEW = {  # clause -> artefact type
    "Act s.5(3) & s.6(3) - languages": "PRIVACY_NOTICE",
    "Rule 8(3) / Act s.8(7) - held apart": "RETENTION_POLICY",
    "Act s.6(6) / s.8(7)(b)": "VENDOR_CONTRACT",
    "Act s.8(2) / Rule 6(1)(f)": "VENDOR_CONTRACT",
    "Act s.8(1)-(2) - onward sharing": "VENDOR_CONTRACT",
}
CONTRACT = ("Data processing agreement. The vendor shall erase all personal data on our instruction and when the purpose ends. "
            "This contract is in force from 1 April. The vendor applies the security safeguards in Schedule 2. "
            "Scope: customer support records only.")


def test_the_five_new_clauses_are_assessable_with_no_fixed_rule():
    for clause, typ in NEW.items():
        r = BY[clause]
        assert r.ai_assessable and not r.attestation_only
        assert {e.artefact_type for e in r.evidence_requirements} == {typ}
        assert not any(m.delta_conditions for m in r.mappings)


def test_phase_one_and_the_fixed_rules_are_untouched():
    assert not BY["Rule 7"].ai_assessable and any(m.delta_conditions for m in BY["Rule 7"].mappings)
    assert BY["Act s.5(2)"].attestation_only and not BY["Act s.5(2)"].ai_assessable
    assert len([r for r in DPDP if r.ai_assessable]) == 3 + len(NEW)
    assert len({r.clause for r in DPDP}) == len(DPDP)   # the replacement left no duplicate


def test_a_vendor_clause_refuses_a_document_of_the_wrong_type(client, monkeypatch):
    h, admin, _ = _setup(client, monkeypatch, Stub())      # only a PRIVACY_NOTICE is uploaded
    r = client.post("/assessments", headers=h(admin), json={"framework": "DPDP", "clause": "Act s.8(2) / Rule 6(1)(f)"})
    assert r.status_code == 422
    nid = client.get("/evidence", headers=h(admin)).json()
    nid = (nid["items"] if isinstance(nid, dict) else nid)[0]["id"]
    r = client.post("/assessments", headers=h(admin), json={"framework": "DPDP", "clause": "Act s.8(2) / Rule 6(1)(f)",
                                                            "evidence_id": nid})
    assert r.status_code == 422 and "VENDOR_CONTRACT" in r.text


class ContractStub(Stub):
    def __init__(self, quotes=None):
        super().__init__(quotes=quotes)
        self.points = [e.required_attributes for e in BY["Act s.8(2) / Rule 6(1)(f)"].evidence_requirements][0]

    def complete_json(self, system, user):
        good = {"contract_in_force": "This contract is in force from 1 April",
                "security_safeguards_terms": "applies the security safeguards in Schedule 2",
                "processing_scope": "customer support records only"}
        good.update(self.quotes)
        return json.dumps({"outcome": "MET", "points": [
            {"point": p, "result": "yes", "reason": "stated", "quote": good[p], "page": 1} for p in self.points]})


def _vendor_run(client, h, who):
    r = client.post("/evidence", headers=h(who), params={"artefact_type": "VENDOR_CONTRACT"},
                    files={"file": ("dpa.txt", CONTRACT.encode(), "text/plain")})
    assert r.status_code in (200, 201, 202), r.text
    return client.post("/assessments", headers=h(who), json={"framework": "DPDP", "clause": "Act s.8(2) / Rule 6(1)(f)"})


def test_a_contract_is_assessed_with_quotes_and_awaits_a_person(client, monkeypatch):
    h, admin, _ = _setup(client, monkeypatch, ContractStub())
    body = _vendor_run(client, h, admin).json()
    assert body["outcome"] == "MET" and body["confirmed_at"] is None
    assert all(p["quote"] and p["page"] == 1 for p in body["points"])


def test_a_forged_quote_on_a_new_point_needs_review(client, monkeypatch):
    h, admin, _ = _setup(client, monkeypatch, ContractStub({"security_safeguards_terms": "all data is encrypted with AES-256"}))
    body = _vendor_run(client, h, admin).json()
    assert body["outcome"] == "NEEDS_REVIEW" and "security_safeguards_terms" in body["reason"]
