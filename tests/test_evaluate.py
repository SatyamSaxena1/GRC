"""The check the whole product hangs on: one policy, two frameworks, different verdicts."""

from datetime import date

import pytest

from app.content.load import load
from app.evaluate import evaluate

CONTENT = load()

# A real-ish Access Control Policy: fine for ISO, short of PCI on two specific points.
POLICY = {
    "approval_date": "2026-03-01",
    "approver_role": "Chief Information Security Officer",
    "effective_date": "2026-03-15",
    "systems_covered": ["Corporate IT", "HR Systems"],
    "password_min_length": 10,
    "mfa_required_for": ["Remote access", "Administrative access"],
    "access_review_frequency_days": 180,
}


def links_by_clause(frameworks):
    return {l.clause: l for l in evaluate(POLICY, "POLICY", frameworks, CONTENT)}


def test_iso_passes_outright():
    links = links_by_clause(["ISO-27001"])
    assert {c: l.verdict for c, l in links.items()} == {
        "A.5.15": "PASS", "A.5.17": "PASS", "A.5.18": "PASS"
    }
    assert all(not l.gaps for l in links.values())


def test_same_evidence_is_partial_on_pci_with_two_specific_gaps():
    links = links_by_clause(["PCI-DSS"])
    assert links["12.1.1"].verdict == "PARTIAL"  # scope
    assert links["8.3.6"].verdict == "PARTIAL"   # password length
    assert links["8.4.2"].verdict == "PASS"
    assert links["7.2.4"].verdict == "PASS"      # 180 <= 183

    gaps = [(l.clause, g.kind, g.attribute) for l in links.values() for g in l.gaps]
    assert gaps == [
        ("12.1.1", "DELTA", "systems_covered"),
        ("8.3.6", "DELTA", "password_min_length"),
    ]


def test_evidence_is_reused_across_both_frameworks_in_one_pass():
    links = evaluate(POLICY, "POLICY", ["ISO-27001", "PCI-DSS"], CONTENT)
    assert len(links) == 7
    assert {l.framework for l in links} == {"ISO-27001", "PCI-DSS"}


def test_remediating_the_gaps_flips_pci_to_pass():
    fixed = POLICY | {
        "password_min_length": 14,
        "systems_covered": ["Corporate IT", "Cardholder Data Environment"],
    }
    links = {l.clause: l for l in evaluate(fixed, "POLICY", ["PCI-DSS"], CONTENT)}
    assert not any(l.gaps for l in links.values())
    # 12.1.1's UCO coverage is PARTIAL, so one policy alone never fully satisfies it.
    assert links["12.1.1"].verdict == "PARTIAL"
    assert links["8.3.6"].verdict == "PASS"


def test_empty_evidence_fails_rather_than_passes():
    links = evaluate({}, "POLICY", ["ISO-27001", "PCI-DSS"], CONTENT)
    assert links and all(l.verdict == "FAIL" for l in links)


def test_unmatched_artefact_type_produces_no_links():
    assert evaluate(POLICY, "SCREENSHOT", ["ISO-27001"], CONTENT) == []


@pytest.mark.parametrize("value", [None, "twelve", ""])
def test_unparseable_extraction_never_silently_passes(value):
    link = {l.clause: l for l in evaluate(
        POLICY | {"password_min_length": value}, "POLICY", ["PCI-DSS"], CONTENT
    )}["8.3.6"]
    assert link.verdict != "PASS"


def test_cadence_words_convert_to_day_counts_deterministically():
    """Extraction reports the literal word ("quarterly"); code — not the model —
    decides that means 90 days."""
    links = {l.clause: l for l in evaluate(
        POLICY | {"access_review_frequency_days": "quarterly"}, "POLICY", ["ISO-27001", "PCI-DSS"], CONTENT
    )}
    assert links["A.5.18"].verdict == "PASS"  # 90 <= 365
    assert links["7.2.4"].verdict == "PASS"   # 90 <= 183

    stale = {l.clause: l for l in evaluate(
        POLICY | {"access_review_frequency_days": "annually"}, "POLICY", ["PCI-DSS"], CONTENT
    )}
    assert stale["7.2.4"].verdict == "PARTIAL"  # 365 > 183


def test_contains_all_matches_real_extracted_phrases_not_just_exact_tokens():
    """A real model returns natural phrases, not the canonical tokens a content-pack
    author typed. "remote access" must satisfy contains_all against a full sentence
    that mentions it, not require an exact list-item match."""
    natural = POLICY | {
        "mfa_required_for": [
            "remote access through the corporate VPN",
            "administrative access to cloud management consoles",
        ],
        "systems_covered": ["Corporate IT", "including the Cardholder Data Environment scope"],
    }
    links = {l.clause: l for l in evaluate(natural, "POLICY", ["PCI-DSS"], CONTENT)}
    assert links["8.4.2"].verdict == "PASS"
    assert links["12.1.1"].verdict == "PARTIAL"  # UCO coverage still PARTIAL by design
    assert not links["12.1.1"].gaps


# A scan that is still within its 90-day validity window at AUDIT_DATE, so these
# tests isolate compliance_status rather than accidentally testing freshness.
AUDIT_DATE = date(2023, 5, 1)
SCAN_REPORT = {
    "scan_completed_date": "2023-03-16",
    "scan_expiry_date": "2023-06-14",
    "asv_company": "Clone Systems, Inc.",
}


@pytest.mark.parametrize("compliant_value", [True, "pass", "Pass", "compliant"])
def test_scan_report_compliance_status_accepts_bool_or_word(compliant_value):
    """The extraction prompt tells the model to type yes/no facts as booleans, but a
    real model sometimes still returns the word it saw ("Pass"). Both must evaluate
    identically — this is a deterministic normalization, not the model deciding."""
    link = {l.clause: l for l in evaluate(
        SCAN_REPORT | {"compliance_status": compliant_value}, "SCAN_REPORT",
        ["PCI-DSS"], CONTENT, as_of=AUDIT_DATE,
    )}["11.3.2"]
    assert link.verdict == "PASS"
    assert not link.gaps


@pytest.mark.parametrize("failing_value", [False, "fail", "Fail", "non-compliant"])
def test_scan_report_compliance_status_failure_is_a_real_gap(failing_value):
    link = {l.clause: l for l in evaluate(
        SCAN_REPORT | {"compliance_status": failing_value}, "SCAN_REPORT",
        ["PCI-DSS"], CONTENT, as_of=AUDIT_DATE,
    )}["11.3.2"]
    assert link.verdict == "PARTIAL"
    assert [g.attribute for g in link.gaps] == ["compliance_status"]


# ------------------------------------------------- the wider framework library

NEW_FRAMEWORKS = ["SOC-2", "NIST-CSF", "HIPAA", "CIS-CONTROLS", "GDPR"]


def test_one_policy_is_reused_across_the_whole_framework_library():
    """The same POLICY fixture used for ISO/PCI above, evaluated against every
    added framework in one pass — this is the reuse pitch, proven at library scale."""
    links = evaluate(POLICY, "POLICY", NEW_FRAMEWORKS, CONTENT)
    assert {l.framework for l in links} == set(NEW_FRAMEWORKS)
    # Every new pack produced at least one real verdict, not silently zero links.
    for framework in NEW_FRAMEWORKS:
        assert any(l.framework == framework for l in links)


def test_strict_frameworks_reject_short_passwords_lenient_ones_accept():
    """CIS requires 14 chars without MFA; NIST/HIPAA's own baseline is 8 — the same
    document should read differently depending on which framework asks, exactly
    like the existing ISO-vs-PCI password-length split above."""
    links = links_by_clause(["CIS-CONTROLS", "NIST-CSF", "HIPAA"])
    assert links["5.2"].verdict == "PARTIAL"       # CIS: 10 < 14
    assert links["PR.AA-01"].verdict == "PASS"     # NIST: 10 >= 8 (plus policy attrs)
    assert links["164.312(d)"].verdict == "PASS"   # HIPAA: 10 >= 8


def test_encryption_and_logging_gaps_are_named_precisely():
    """An encryption or logging policy that says nothing must report precise
    missing-attribute gaps, never a pass — and passes once it states the facts."""
    enc = {l.clause: l for l in evaluate({}, "ENCRYPTION_POLICY", ["SOC-2"], CONTENT)}
    assert enc["CC6.7"].verdict == "FAIL"
    assert {g.attribute for g in enc["CC6.7"].gaps} == {"encryption_at_rest", "encryption_in_transit"}
    log = {l.clause: l for l in evaluate({}, "LOGGING_POLICY", ["NIST-CSF"], CONTENT)}
    assert log["PR.PT-01"].verdict == "FAIL"
    assert [g.attribute for g in log["PR.PT-01"].gaps] == ["log_retention_days"]

    stated_enc = {l.clause: l for l in evaluate(
        {"encryption_at_rest": True, "encryption_in_transit": True}, "ENCRYPTION_POLICY", ["SOC-2"], CONTENT)}
    stated_log = {l.clause: l for l in evaluate(
        {"log_retention_days": 120}, "LOGGING_POLICY", ["NIST-CSF"], CONTENT)}
    assert stated_enc["CC6.7"].verdict == "PASS"
    assert stated_log["PR.PT-01"].verdict == "PASS"


def test_a_pass_shows_what_it_passed_on():
    """Not just 'no gaps': the check list names the bound and the value that met it."""
    link = {l.clause: l for l in evaluate(POLICY | {"password_min_length": 14}, "POLICY",
                                          ["PCI-DSS"], CONTENT)}["8.3.6"]
    assert link.verdict == "PASS"
    assert [(c.attribute, c.operator, c.expected, c.actual, c.met) for c in link.checked] == [
        ("password_min_length", ">=", 12, 14, True)
    ]


def test_silence_is_an_unmet_presence_check_not_a_missing_row():
    link = {l.clause: l for l in evaluate({}, "POLICY", ["PCI-DSS"], CONTENT)}["8.3.6"]
    assert [(c.attribute, c.operator, c.met) for c in link.checked] == [("password_min_length", "present", False)]


@pytest.mark.parametrize("attrs", [
    POLICY, {},
    POLICY | {"password_min_length": 3, "mfa_required_for": ["nobody"], "systems_covered": []},
])
def test_checked_never_disagrees_with_gaps(attrs):
    """`checked` is a second pass over the same rules; if it drifted from the gaps the
    evaluator reported, a PASS would show its working wrongly."""
    frameworks = ["ISO-27001", "PCI-DSS", "SOC-2", "NIST-CSF", "HIPAA", "CIS-CONTROLS", "GDPR"]
    for link in evaluate(attrs, "POLICY", frameworks, CONTENT):
        unmet = {c.attribute for c in link.checked if not c.met}
        assert unmet <= {g.attribute for g in link.gaps}, (link.framework, link.clause)
        if link.verdict == "PASS":
            assert all(c.met for c in link.checked), (link.framework, link.clause)


ALL_FRAMEWORKS = ["ISO-27001", "PCI-DSS", "SOC-2", "NIST-CSF", "HIPAA", "CIS-CONTROLS", "GDPR"]
TOPIC_ATTRS = {"encryption_at_rest", "encryption_in_transit", "log_retention_days"}


def test_an_access_policy_is_not_judged_on_encryption_or_logging():
    """Encryption and logging have their own artefact types, so an access-control policy
    (POLICY) neither passes nor fails them — it is simply not evidence for them."""
    for link in evaluate(POLICY, "POLICY", ALL_FRAMEWORKS, CONTENT):
        assert not TOPIC_ATTRS & {c.attribute for c in link.checked}, (link.framework, link.clause)
        assert not TOPIC_ATTRS & {g.attribute for g in link.gaps}, (link.framework, link.clause)


@pytest.mark.parametrize("artefact_type,attrs", [
    ("ENCRYPTION_POLICY", {"encryption_at_rest", "encryption_in_transit"}),
    ("LOGGING_POLICY", {"log_retention_days"}),
])
def test_topic_policies_are_judged_only_on_their_topic(artefact_type, attrs):
    links = evaluate({}, artefact_type, ALL_FRAMEWORKS, CONTENT)
    assert links and all(l.verdict == "FAIL" for l in links)  # silence still fails, on-topic
    assert {g.attribute for l in links for g in l.gaps} == attrs


def test_topic_policies_also_extract_document_control_facts_for_quality():
    from app.service import required_attribute_names
    asked = required_attribute_names(CONTENT, ALL_FRAMEWORKS, "ENCRYPTION_POLICY")
    assert {"encryption_at_rest", "approval_date", "approver_role"} <= set(asked)
    assert "password_min_length" not in asked


def test_extraction_prompt_names_the_yes_no_attributes_from_the_packs():
    """A pack testing `encryption_at_rest == true` is what makes it a yes/no fact; the model
    must be told, or it reports the method ("AES-256") and a correct policy stays PARTIAL."""
    from app.ai.prompts import build_user_prompt
    prompt = build_user_prompt("doc", ["encryption_at_rest", "password_min_length"])
    assert "Yes/no attributes: ['encryption_at_rest']" in prompt
    assert "password_min_length'] --" not in prompt
    assert "Yes/no" not in build_user_prompt("doc", ["password_min_length"])
    # A model once reported affected_person_notification=true from the quote "No specific
    # notification process ... is mentioned"; the hint must rule that reading out.
    assert "affirmatively states" in prompt and "never true" in prompt


def test_an_ai_policy_must_commit_to_fairness():
    """GOVERN 1.2: a policy naming valid, safe, secure and transparent but saying nothing about
    fairness or harmful bias is not enough; the same policy that does say it passes."""
    def govern_1_2(characteristics):
        links = evaluate({"trustworthy_ai_characteristics_addressed": characteristics},
                         "AI_POLICY", ["NIST-AI-RMF"], CONTENT)
        return next(l for l in links if l.clause == "GOVERN 1.2")

    without = govern_1_2(["valid and reliable", "safe", "secure and resilient", "transparent and accountable"])
    assert without.verdict == "PARTIAL"
    assert [(g.kind, g.attribute) for g in without.gaps] == [("DELTA", "trustworthy_ai_characteristics_addressed")]

    with_fairness = govern_1_2(["valid and reliable", "safe", "secure and resilient",
                                "transparent and accountable", "fairness and harmful bias management"])
    assert with_fairness.verdict == "PASS" and not with_fairness.gaps
