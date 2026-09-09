"""The AI RMF pack, end to end.

AI RMF is outcome-based with no numeric thresholds, so almost every condition is
"the policy states X". What is worth testing is that this still produces a
specific, actionable gap rather than a vague one — and that the Playbook's
guidance reaches the person who has to fix it.
"""

from __future__ import annotations

from datetime import date

from app.content.load import load
from app.evaluate import evaluate
from app.service import _remediation

CONTENT = load()
AS_OF = date(2026, 9, 3)


class _Gap:
    """The shape app/service.py::_remediation consumes."""
    def __init__(self, kind, attribute, actual=None, required=None):
        self.kind, self.attribute = kind, attribute
        self.actual, self.required, self.detail = actual, required, ""


def test_pack_evaluates_and_a_compliant_policy_passes():
    attributes = {
        "ai_legal_requirements_documented": True,
        "ai_applicable_regulations": ["EU AI Act", "GDPR"],
    }
    links = evaluate(attributes, "AI_POLICY", ["NIST-AI-RMF"], CONTENT, AS_OF)
    govern_11 = next(l for l in links if l.clause == "GOVERN 1.1")
    assert govern_11.verdict == "PASS", govern_11.gaps


def test_a_silent_policy_names_the_attribute_it_failed_to_state():
    """The whole point: not 'insufficient evidence' but 'you never said X'."""
    links = evaluate({}, "AI_POLICY", ["NIST-AI-RMF"], CONTENT, AS_OF)
    govern_11 = next(l for l in links if l.clause == "GOVERN 1.1")
    assert govern_11.verdict == "FAIL"
    assert "ai_legal_requirements_documented" in {g.attribute for g in govern_11.gaps}


def test_inventory_clause_uses_its_own_artefact_type():
    """GOVERN 1.6 is evidenced by an inventory, not by the policy — uploading a
    policy must not silently satisfy it."""
    from_policy = evaluate({}, "AI_POLICY", ["NIST-AI-RMF"], CONTENT, AS_OF)
    assert not any(l.clause == "GOVERN 1.6" for l in from_policy)

    from_inventory = evaluate({}, "AI_INVENTORY", ["NIST-AI-RMF"], CONTENT, AS_OF)
    assert any(l.clause == "GOVERN 1.6" for l in from_inventory)


def test_playbook_guidance_is_appended_to_the_generic_remediation():
    """A gap keeps the sentence naming the concrete attribute — the framework's
    clause-level advice cannot know that — and gains the Playbook's advice."""
    requirement = CONTENT.requirement("NIST-AI-RMF", "GOVERN 1.6")
    gap = _Gap("MISSING_ATTRIBUTE", "ai_systems_inventoried")

    plain = _remediation(gap)
    withguide = _remediation(gap, requirement.guidance)

    assert "ai_systems_inventoried" in withguide      # the specific failure survives
    assert withguide.startswith(plain)                # guidance is additive, not a replacement
    assert "Framework guidance:" in withguide
    assert "inventory" in withguide.lower()


def test_guidance_is_absent_for_packs_that_do_not_publish_any():
    """Only the AI RMF has a Playbook; the other packs must not grow an empty
    'Framework guidance:' heading."""
    iso = CONTENT.requirement("ISO-27001", CONTENT.framework("ISO-27001").requirements[0].clause)
    assert iso.guidance == ""
    assert "Framework guidance" not in _remediation(_Gap("MISSING_ATTRIBUTE", "x"), iso.guidance)
