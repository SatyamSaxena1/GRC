import pytest

from app.content import load as content_load
from app.content.load import load


def test_load_is_deterministic_and_references_resolve():
    assert load() == load()  # frozen models; loading twice is identical
    content = load()
    known = {u.code for u in content.ucos}
    assert known
    for pack in content.packs:
        assert pack.requirements
        for req in pack.requirements:
            assert req.mappings and req.evidence_requirements
            assert all(m.uco in known for m in req.mappings)


def test_unknown_uco_reference_is_rejected(tmp_path):
    (tmp_path / "uco.yaml").write_text(
        "ucos:\n  - {code: UCO-X, title: t, domain: d}\n"
    )
    (tmp_path / "bad.yaml").write_text("""
framework: {code: F, version: "1"}
requirements:
  - clause: "1"
    title: t
    text: t
    evidence_requirements: [{artefact_type: POLICY, required_attributes: [a]}]
    mappings: [{uco: UCO-NOPE, coverage: FULL, confidence: 1.0, source: EXPERT}]
""")
    with pytest.raises(ValueError, match="UCO-NOPE"):
        load(tmp_path)


def test_both_frameworks_are_present():
    content = load()
    assert content.framework("ISO-27001").framework.version == "2022"
    assert content.framework("PCI-DSS").framework.version == "4.0.1"
    assert content_load.CONTENT_DIR.is_dir()


def test_framework_library_is_present():
    """The broader pack library added alongside ISO/PCI — same schema, same
    load-time validation (see test_load_is_deterministic_and_references_resolve)."""
    content = load()
    codes = {pack.framework.code for pack in content.packs}
    assert codes == {"ISO-27001", "PCI-DSS", "SOC-2", "NIST-CSF", "HIPAA", "CIS-CONTROLS",
                     "GDPR", "NIST-AI-RMF", "DPDP"}


def test_new_frameworks_reuse_existing_iam_and_vuln_ucos():
    """The point of a shared UCO layer: a new framework pack should mostly map onto
    UCOs the existing packs already use, not invent a parallel taxonomy.

    NIST-AI-RMF is deliberately excluded — see test_ai_rmf_owns_a_new_uco_domain.
    """
    content = load()
    shared = {"UCO-IAM-001", "UCO-IAM-002", "UCO-IAM-011", "UCO-IAM-012", "UCO-IAM-020", "UCO-VULN-001"}
    for code in ("SOC-2", "NIST-CSF", "HIPAA", "CIS-CONTROLS", "GDPR"):
        pack = content.framework(code)
        used = {m.uco for req in pack.requirements for m in req.mappings}
        assert used & shared, f"{code} shares no UCO with the existing packs"


def test_ai_rmf_owns_a_new_uco_domain():
    """AI governance genuinely is a new domain — the existing UCOs cover IAM,
    vulnerability management, data protection and logging, none of which an AI
    inventory or a human-oversight policy maps onto. So this pack is the one
    exception to "reuse the existing taxonomy", and it pays for that by owning a
    domain the next AI framework (ISO/IEC 42001, the EU AI Act) can reuse.
    """
    content = load()
    ai_ucos = {u.code for u in content.ucos if u.domain == "AI_GOVERNANCE"}
    assert len(ai_ucos) >= 9
    used = {m.uco for req in content.framework("NIST-AI-RMF").requirements for m in req.mappings}
    assert used and used <= ai_ucos, "AI-RMF should map only onto AI-governance UCOs"


def test_ai_rmf_carries_playbook_guidance():
    """The Playbook's suggested actions are the reason a gap on this pack can say
    something more useful than the generic per-gap-kind wording."""
    pack = load().framework("NIST-AI-RMF")
    assert all(r.guidance.strip() for r in pack.requirements)
    # Guidance must be advice, not a restatement of the outcome text.
    assert not any(r.guidance.strip() == r.text.strip() for r in pack.requirements)


def test_report_artefact_type_is_mapped_in_cis_controls():
    """Phase 2: REPORT is a real artefact type in the upload form now — this
    pins that at least one requirement actually accepts it as evidence,
    matching what app/routers/evidence.py::ARTEFACT_TYPES allows to upload."""
    pack = load().framework("CIS-CONTROLS")
    req = next(r for r in pack.requirements if r.clause == "7.5-7.6")
    types = {e.artefact_type for e in req.evidence_requirements}
    assert "REPORT" in types
    assert "SCAN_REPORT" in types  # the original requirement still holds too
