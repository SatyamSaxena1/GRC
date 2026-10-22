"""Source-text ingestion (ADR-029 section 6): one check per stage. Parsing is deterministic,
a draft that fails the schema never reaches review, an accepted clause loads through the
real loader, and no copyrighted standard's text is stored under sources/."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import yaml

from app.content.load import CONTENT_DIR, load
from app.exceptions import rule_hash
from tools import ingest_source as ing
from tools import review_drafts as rev

AI_ACT = ing.FRAMEWORKS["eu-ai-act"]


# ------------------------------------------------------------------ stage 2: parse

def test_every_registered_source_parses_deterministically(tmp_path):
    for framework in ing.FRAMEWORKS:
        shutil.copytree(ing.SOURCES / framework, tmp_path / framework,
                        ignore=shutil.ignore_patterns("provisions.jsonl"))
        first = ing.parse(framework, sources=tmp_path).read_bytes()
        assert first == ing.parse(framework, sources=tmp_path).read_bytes(), framework
        # the committed file is what this source parses to
        assert first == ing.provisions_path(framework).read_bytes(), framework
        ids = [json.loads(line)["id"] for line in first.decode("utf-8").splitlines()]
        assert len(set(ids)) == len(ids), framework


def test_parse_cites_paragraphs_and_points():
    first = ing.provisions_path("eu-ai-act").read_bytes()

    rows = [json.loads(line) for line in first.decode("utf-8").splitlines()]
    by_ref = {r["ref"]: r for r in rows}
    gdpr = {r["ref"]: r for r in ing.read_provisions("gdpr")}
    assert "appropriate technical and organisational measures" in gdpr["Art. 32(1)"]["text"]
    assert "Art. 32(1)(a)" in gdpr
    assert "at least six months" in by_ref["Art. 26(6)"]["text"]
    assert by_ref["Art. 4"]["text"].startswith("Providers and deployers of AI systems")
    assert "Art. 5(1)(h)" in by_ref  # points are cited on their own too


# ------------------------------------------------------------------ stage 3: draft

_GOOD = {
    "verdict_basis": "documentable", "reason": "a logging policy states the retention period",
    "new_artefact_types": [],
    "requirement": {
        "title": "Keep high-risk AI system logs for at least six months", "guidance": "State it.",
        "evidence_requirements": [{"artefact_type": "LOGGING_POLICY",
                                   "required_attributes": ["ai_log_retention_days"]}],
        "mappings": [{"uco": "UCO-LOG-001", "coverage": "PARTIAL", "confidence": 0.8, "source": "EXPERT",
                      "delta_conditions": [{"attribute": "ai_log_retention_days", "operator": ">=",
                                            "value": 183}]}]},
}


def _provision(ref="Art. 26(6)"):
    return next(p for p in ing.read_provisions("eu-ai-act") if p["ref"] == ref)


def test_a_valid_draft_is_pending_with_the_law_as_its_text_and_ai_as_its_source():
    entry = ing.check_draft(json.dumps(_GOOD), _provision(), AI_ACT, load())
    assert entry["status"] == "pending"
    req = entry["requirement"]
    assert req["clause"] == "Art. 26(6)"
    assert req["text"] == _provision()["text"]          # quoted, not paraphrased by the model
    assert req["mappings"][0]["source"] == "AI"         # the model can't claim expert review


def test_a_draft_that_fails_the_schema_is_rejected_before_review():
    content = load()
    bad_uco = json.loads(json.dumps(_GOOD))
    bad_uco["requirement"]["mappings"][0]["uco"] = "UCO-MADE-UP"
    bad_operator = json.loads(json.dumps(_GOOD))
    bad_operator["requirement"]["mappings"][0]["delta_conditions"][0]["operator"] = "approximately"
    new_type_undeclared = json.loads(json.dumps(_GOOD))
    new_type_undeclared["requirement"]["evidence_requirements"][0]["artefact_type"] = "AI_IMPACT_ASSESSMENT"
    orphan_condition = json.loads(json.dumps(_GOOD))  # the condition tests something never extracted
    orphan_condition["requirement"]["mappings"][0]["delta_conditions"][0]["attribute"] = "ai_log_retention_months"
    for raw in ("not json", json.dumps({"verdict_basis": "maybe"}), json.dumps(bad_uco),
                json.dumps(bad_operator), json.dumps(new_type_undeclared), json.dumps(orphan_condition)):
        assert ing.check_draft(raw, _provision(), AI_ACT, content)["status"] == "schema_rejected", raw


# ------------------------------------------------------------------ stage 4: review gate

def test_an_accepted_clause_loads_with_its_source_ref_and_unchanged_rule_hash(tmp_path):
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    shutil.copy(CONTENT_DIR / "uco.yaml", content_dir / "uco.yaml")
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    provision = _provision()
    omitted = {"provision": "eu-ai-act:art26.3", "ref": "Art. 26(3)", "sha256": _provision("Art. 26(3)")["sha256"],
               "status": "pending", "verdict_basis": "not documentable", "reason": "a without-prejudice clause"}
    accepted = ing.check_draft(json.dumps(_GOOD), provision, AI_ACT, load())
    (drafts / "eu-ai-act.yaml").write_text(yaml.safe_dump({"drafts": [omitted, accepted]}), encoding="utf-8")

    answers = iter(["c", "a"])
    counts = rev.review("eu-ai-act", ask=lambda _: next(answers), drafts=drafts, content_dir=content_dir)
    assert counts == {"omitted": 1, "accepted": 1}

    pack_text = (content_dir / AI_ACT["pack"]).read_text(encoding="utf-8")
    assert "#   Art. 26(3): a without-prejudice clause" in pack_text  # omission recorded, not dropped
    req = load(content_dir).requirement("EU-AI-ACT", "Art. 26(6)")
    assert req.source_ref.provision == "eu-ai-act:art26.6"
    assert req.source_ref.sha256 == provision["sha256"]
    assert all(m.source == "EXPERT" for m in req.mappings)
    # provenance metadata stays out of the rule body, so ADR-022 rule hashes don't move
    assert "source_ref" not in req.model_dump(mode="json")
    assert rule_hash(load(content_dir), "EU-AI-ACT", "Art. 26(6)")

    statuses = [d["status"] for d in yaml.safe_load((drafts / "eu-ai-act.yaml").read_text())["drafts"]]
    assert statuses == ["omitted", "accepted"]


# ------------------------------------------------------------------ stage 1: sources

def test_no_copyrighted_standard_text_is_stored_under_sources():
    """ISO, PCI DSS and AICPA texts are copyrighted: those packs keep clause numbers and our own
    paraphrase only. Nothing under sources/ may name them as its source or carry their notices."""
    notices = ("© ISO", "ISO copyright office", "PCI Security Standards Council, LLC", "© AICPA",
               "American Institute of Certified Public Accountants")
    # Every file sits in a per-source folder whose SOURCE.md states its licence and its sha256,
    # registered with the pipeline or not yet (a PDF waiting for its parser still needs both).
    for path in Path(ing.SOURCES).rglob("*"):
        if not path.is_file():
            continue
        assert path.parent.parent == ing.SOURCES, f"{path} is not inside a sources/<name>/ folder"
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert not any(n in text for n in notices), path
        source_md = path.parent / "SOURCE.md"
        assert source_md.exists(), f"{path.parent.name} has no SOURCE.md"
        if path.name in ("SOURCE.md", "provisions.jsonl"):  # documentation and derived output
            continue
        md = source_md.read_text(encoding="utf-8")
        assert "Licence" in md
        assert hashlib.sha256(path.read_bytes()).hexdigest() in md, f"{path}: sha256 not recorded in SOURCE.md"
    for framework in ing.FRAMEWORKS:
        assert (ing.SOURCES / framework / "SOURCE.md").exists()
