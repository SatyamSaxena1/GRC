"""Runs the real Asteron Access Control Policy sample through the deterministic
engine. The attribute dict below stands in for the LLM extraction step (no
ANTHROPIC_API_KEY in this environment) but is transcribed by hand from the
actual PDF text, not invented — see tests/fixtures/access_control_policy_v1.txt.

This is the go/no-go shape the plan calls for: one real policy, evaluated
against ISO and PCI independently, with the exact real-world gaps a careful
reviewer would flag.
"""

from pathlib import Path

from app.content.load import load
from app.evaluate import evaluate
from app.ingest import extract_text

FIXTURE = Path(__file__).parent / "fixtures" / "access_control_policy_v1.txt"
CONTENT = load()

# Transcribed from the document, not asserted by the LLM:
# - MFA is unconditional only for VPN/remote access; admin-console MFA is
#   conditional ("where the platform supports it"), so it's honest to extract
#   only "remote access" here rather than assume administrative MFA holds.
# - Review cadence is quarterly for critical systems but annual for the rest;
#   365 is the cadence actually governing most in-scope systems.
ATTRIBUTES = {
    "approval_date": "2026-03-12",
    "approver_role": "Chief Information Security Officer",
    "effective_date": "2026-03-12",
    "systems_covered": [
        "Corporate IT", "corporate identity platform", "email",
        "collaboration tools", "source-code repositories",
        "endpoint management systems", "internal business applications",
    ],
    "password_min_length": 8,
    "mfa_required_for": ["remote access"],
    "access_review_frequency_days": 365,
}


def test_native_text_extraction_reads_the_real_document():
    text = extract_text(FIXTURE.name, FIXTURE.read_bytes())
    assert "ISP-AC-001" in text
    assert "Cardholder Data Environment" in text


def test_iso_mostly_passes_on_this_policy():
    links = {l.clause: l for l in evaluate(ATTRIBUTES, "POLICY", ["ISO-27001"], CONTENT)}
    assert links["A.5.15"].verdict == "PASS"
    assert links["A.5.17"].verdict == "PASS"   # 8 >= ISO's 8-char minimum
    assert links["A.5.18"].verdict == "PASS"   # 365 <= 365-day cadence


def test_pci_surfaces_the_real_gaps_iso_misses():
    links = {l.clause: l for l in evaluate(ATTRIBUTES, "POLICY", ["PCI-DSS"], CONTENT)}

    assert links["12.1.1"].verdict == "PARTIAL"
    assert [g.attribute for g in links["12.1.1"].gaps] == ["systems_covered"]

    assert links["8.3.6"].verdict == "PARTIAL"  # 8 < PCI's 12-char minimum
    assert [g.attribute for g in links["8.3.6"].gaps] == ["password_min_length"]

    assert links["8.4.2"].verdict == "PARTIAL"  # admin-console MFA is conditional, not guaranteed
    assert [g.attribute for g in links["8.4.2"].gaps] == ["mfa_required_for"]

    assert links["7.2.4"].verdict == "PARTIAL"  # annual cadence fails PCI's 6-month requirement
    assert [g.attribute for g in links["7.2.4"].gaps] == ["access_review_frequency_days"]


def test_same_evidence_reused_across_both_frameworks_in_one_pass():
    links = evaluate(ATTRIBUTES, "POLICY", ["ISO-27001", "PCI-DSS"], CONTENT)
    assert len(links) == 7
    iso_pass = sum(l.verdict == "PASS" for l in links if l.framework == "ISO-27001")
    pci_partial = sum(l.verdict == "PARTIAL" for l in links if l.framework == "PCI-DSS")
    assert iso_pass == 3
    assert pci_partial == 4
