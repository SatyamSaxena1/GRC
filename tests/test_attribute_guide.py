"""The attribute guide must stay consistent with the rules it describes and must
never smuggle a verdict into the prompt (what is *compliant* is the rules engine's call)."""

from __future__ import annotations

import re

from app.ai.guide import load_guide, render_guide
from app.ai.prompts import EXTRACTION_PROMPT_VERSION, build_user_prompt
from app.content.load import load
from app.service import required_attribute_names

CONTENT = load()
GUIDE = load_guide()
ALL = {a for t in ("POLICY", "SCAN_REPORT", "REVIEW_RECORD", "ENCRYPTION_POLICY", "LOGGING_POLICY", "PRIVACY_NOTICE")
       for a in required_attribute_names(CONTENT, [], t)}


def test_entries_are_well_typed():
    """An unquoted `Foo: bar` inside a list item parses as a mapping, not text."""
    for name, entry in GUIDE.items():
        assert isinstance(entry["means"], str), name
        assert all(isinstance(x, str) for x in entry.get("not_this", [])), name
        assert all(len(e) == 2 and isinstance(e[0], str) for e in entry.get("examples", [])), name


def test_every_entry_is_a_real_attribute():
    """A typo'd key would silently never be shown."""
    assert set(GUIDE) <= ALL, sorted(set(GUIDE) - ALL)


def test_the_documents_a_demo_uses_are_fully_described():
    for artefact_type in ("POLICY", "SCAN_REPORT", "REVIEW_RECORD"):
        missing = [a for a in required_attribute_names(CONTENT, [], artefact_type) if a not in GUIDE]
        assert not missing, (artefact_type, missing)


def test_entries_describe_how_to_read_never_what_is_good():
    """No threshold or verdict language: 8 characters being enough is the rules' call."""
    banned = re.compile(r"\b(compliant|non-compliant|sufficient|insufficient|strong enough|too (short|weak)|"
                        r"meets? the (requirement|standard)|should be at least)\b", re.I)
    for name, entry in GUIDE.items():
        text = " ".join(str(v) for v in entry.values())
        if name == "compliance_status":
            continue  # the attribute itself is the document's own stated overall result
        assert not banned.search(text), f"{name}: {banned.search(text).group(0)!r}"


def test_prompt_carries_exactly_the_requested_attributes_in_order():
    names = ["password_min_length", "access_review_frequency_days"]
    block = render_guide(names)
    assert block.index("password_min_length") < block.index("access_review_frequency_days")
    assert "mfa_required_for" not in block
    prompt = build_user_prompt("DOC", names)
    assert prompt.index("access_review_frequency_days:") < prompt.index("--- DOCUMENT TEXT")
    assert EXTRACTION_PROMPT_VERSION.endswith(":v4")


def test_unknown_attributes_still_work_and_add_nothing():
    assert render_guide(["not_a_real_attribute"]) == ""
    assert "What each attribute means" not in build_user_prompt("DOC", ["not_a_real_attribute"])


def test_the_cadence_entry_names_the_distractors_that_actually_failed():
    entry = GUIDE["access_review_frequency_days"]
    joined = " ".join(entry["not_this"]).lower()
    assert "policy itself" in joined          # "Review Frequency: Annual" in the document-control table
    assert "never a list" in " ".join(entry["report_as"].split()).lower()


def test_an_empty_answer_is_nothing_stated_not_a_stated_fact():
    """The regression the guide introduced: mfa_required_for came back [] for a
    document silent on MFA, which the rules judge as stated-and-wrong (PARTIAL)
    rather than missing (FAIL). Silence must be null whatever the model emits."""
    from app.ai.schemas import ExtractedField

    for empty in ([], (), {}, "", "   "):
        assert ExtractedField(value=empty).value is None, empty
    assert ExtractedField(value=0).value == 0          # zero is a stated value
    assert ExtractedField(value=False).value is False  # so is "no"
    assert ExtractedField(value=["remote access"]).value == ["remote access"]


def test_empty_mfa_list_no_longer_turns_a_missing_fact_into_a_partial_verdict():
    from app.ai.extraction import extract_attributes

    class G:
        model = "m"
        provider = "x"
        last_latency_ms = 0
        last_truncated = False

        def available(self):
            return True

        def complete_json(self, system, user):
            return '{"mfa_required_for": {"value": [], "confidence": 0.9, "sources": []}}'

    run = extract_attributes(G(), "text", ["mfa_required_for"])
    assert run.fields["mfa_required_for"].value is None


def test_the_guide_can_be_switched_off_without_a_deploy(monkeypatch):
    names = ["password_min_length"]
    assert "password_min_length:" in build_user_prompt("DOC", names)
    for off in ("0", "off", "false", "No"):
        monkeypatch.setenv("EXTRACTION_GUIDE", off)
        assert render_guide(names) == ""
        assert "What each attribute means" not in build_user_prompt("DOC", names)
    monkeypatch.setenv("EXTRACTION_GUIDE", "1")
    assert render_guide(names) != ""
