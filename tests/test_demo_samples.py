"""The demo sample library (frontend/src/demo/samples.json) must stay honest:
every story's expected verdicts are what the real rules engine produces from the
sample's own ground-truth attributes, and the token renderer matches the one the
browser runs. No model needed - this is the deterministic half of the guarantee;
how reliably the *model* reads each document is measured by evaluation/runner.py.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.content.load import load as load_content
from app.evaluate import evaluate
from app.service import ARTEFACT_TYPES
from evaluation import samples as lib

DOC = lib.load()
TODAY = date.fromisoformat(DOC["golden"]["today"])
CONTENT = load_content()


def test_golden_tokens_render_as_the_browser_renders_them():
    for case in DOC["golden"]["cases"]:
        assert lib.render(case["token"], TODAY, "RUNID") == case["text"]


@pytest.mark.parametrize("sample", DOC["samples"], ids=lambda s: s["id"])
def test_sample_is_well_formed(sample):
    assert sample["artefact_type"] in ARTEFACT_TYPES
    assert sample.get("upload_as", sample["artefact_type"]) in ARTEFACT_TYPES
    assert sample["body"] and sample["story"] and sample["watch"]
    assert "{{runid}}" in sample["filename"]  # a fresh run id keeps the sha256 unique (no 409 on re-upload)
    assert any("{{runid}}" in line for line in sample["body"])
    assert sample["filename"].startswith("demo-")  # lets a cleanup helper find demo uploads


@pytest.mark.parametrize("sample", [s for s in DOC["samples"] if not s.get("upload_as")], ids=lambda s: s["id"])
def test_expected_verdicts_are_what_the_rules_engine_says(sample):
    r = lib.render(sample, TODAY, "RUNID")
    links = evaluate(r["attrs"], r["artefact_type"], DOC["frameworks"], CONTENT,
                     as_of=TODAY, org_commitments=r.get("commitments"))
    assert {f"{l.framework} {l.clause}": l.verdict for l in links} == sample["expect"]


def test_attribute_ground_truth_is_actually_in_the_document():
    """The label must be recoverable from the text, or it measures nothing."""
    for r in lib.rendered(TODAY, "RUNID"):
        low = r["text"].lower()
        for name, value in r["attrs"].items():
            if value is None or isinstance(value, bool):
                continue
            items = value if isinstance(value, list) else [value]
            for item in items:
                if name.endswith("_date") and isinstance(item, str):
                    continue  # ISO label vs human-formatted date in the text; checked by the golden tokens
                if name == "access_review_frequency_days":
                    continue  # label is the word "quarterly"; text says it with the number too
                assert str(item).lower() in low, f"{r['id']}.{name}: {item!r} not found in the document"


def test_story_claims_hold():
    by_id = {s["id"]: s for s in DOC["samples"]}
    v1, v2 = by_id["policy-asteron"]["expect"], by_id["policy-asteron-v2"]["expect"]
    assert len(v1) == 24                      # "one policy, 24 clauses"
    assert v1["PCI-DSS 8.3.6"] == "PARTIAL" and v2["PCI-DSS 8.3.6"] == "PASS"
    assert v1["ISO-27001 A.5.17"] == "PASS"   # ISO accepts what PCI only partly does
    assert set(by_id["scan-expired"]["expect"].values()) == {"FAIL"}
    assert set(by_id["scan-current"]["expect"].values()) == {"PASS"}
    assert by_id["review-record-stale"]["expect"]["ISO-27001 A.5.18"] == "FAIL"
    assert by_id["review-record-fresh"]["expect"]["ISO-27001 A.5.18"] == "PASS"


def test_revises_points_at_a_real_sample_of_the_same_kind():
    by_id = {s["id"]: s for s in DOC["samples"]}
    for s in DOC["samples"]:
        if s.get("revises"):
            assert s["revises"] in by_id
            assert by_id[s["revises"]]["artefact_type"] == s["artefact_type"]  # a version of the same kind of document
