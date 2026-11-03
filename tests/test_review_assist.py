"""Advisory review help for drafted requirements (ADR-035): useful, labelled, and powerless."""

from __future__ import annotations

import copy
import json
import shutil

import yaml

from app.content.load import CONTENT_DIR, load
from tools import ingest_source as ing
from tools import review_assist as ra
from tools import review_drafts as rev
from test_source_ingestion import _GOOD, _provision

CFG = ing.FRAMEWORKS["eu-ai-act"]
PROVISIONS = {p["id"]: p for p in ing.read_provisions("eu-ai-act")}


def _entry(good=_GOOD, ref="Art. 26(6)"):
    return ing.check_draft(json.dumps(good), _provision(ref), CFG, load())


class StubGateway:
    model = "critic-model"

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def complete_json(self, system, user):
        self.calls.append((system, user))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer if isinstance(self.answer, str) else json.dumps(self.answer)


CRITIQUE = {"faithful": "partly", "concerns": ["Art. 26(6) says 'unless provided otherwise in applicable Union or national law'"],
            "missing_context": ["Art. 26(5) on monitoring"], "suggested_changes": ["mention the exception"]}


# ------------------------------------------------------------------ retrieval by id

def test_related_provisions_are_fetched_by_id_cited_first_then_neighbours():
    provision = PROVISIONS["eu-ai-act:art26.6"]
    got = ra.related(PROVISIONS, provision)
    assert [r["ref"] for r in got] == ["Art. 26(5)", "Art. 26(7)"]
    cites = next(p for p in PROVISIONS.values() if "Article 6(1)" in p["text"] and "." in p["id"].split(":")[1])
    refs = [r["ref"] for r in ra.related(PROVISIONS, cites)]
    assert "Art. 6(1)" in refs or "Art. 6" in refs  # what the provision cites comes first
    assert len(ra.related(PROVISIONS, cites, limit=2)) <= 2


def test_related_never_returns_the_provision_itself_or_a_missing_one_or_long_text():
    for pid in ("eu-ai-act:art26.1", "eu-ai-act:art4"):
        p = PROVISIONS[pid]
        got = ra.related(PROVISIONS, p)
        assert p["ref"] not in [r["ref"] for r in got]
        assert all(len(r["text"]) <= ra.MAX_CHARS for r in got)
    assert ra.related({}, PROVISIONS["eu-ai-act:art26.6"]) == []


# ------------------------------------------------------------------ mechanical checks

def _warns(checks):
    return [c["what"] for c in checks if c["level"] == "warn"]


def test_a_faithful_draft_passes_every_mechanical_check_except_the_derived_number():
    checks = ra.mechanical_checks(_entry(), _provision(), CFG, set())
    assert [c["what"] for c in checks if c["level"] == "ok"] == [
        "source text unchanged since drafting", "quotes the law word for word", "clause not yet in the pack"]
    (warn,) = _warns(checks)
    assert "183" in warn and "not written in the provision" in warn  # six months -> 183 is derived: say so


def test_each_mechanical_problem_is_flagged():
    base = _entry()
    changed = copy.deepcopy(base)
    changed["sha256"] = "0" * 64
    assert any("source text changed" in w for w in _warns(ra.mechanical_checks(changed, _provision(), CFG, set())))

    paraphrased = copy.deepcopy(base)
    paraphrased["requirement"]["text"] = "Keep logs for six months."
    assert any("not the law's own words" in w for w in _warns(ra.mechanical_checks(paraphrased, _provision(), CFG, set())))

    new_type = copy.deepcopy(base)
    new_type["new_artefact_types"] = ["AI_LOG_REGISTER"]
    assert any("new artefact type" in w for w in _warns(ra.mechanical_checks(new_type, _provision(), CFG, set())))

    assert any("already in the pack" in w for w in _warns(ra.mechanical_checks(base, _provision(), CFG, {"Art. 26(6)"})))

    no_reason = {"provision": "eu-ai-act:art26.3", "ref": "Art. 26(3)", "sha256": _provision("Art. 26(3)")["sha256"],
                 "status": "pending", "verdict_basis": "not documentable", "reason": " "}
    assert any("no reason" in w for w in _warns(ra.mechanical_checks(no_reason, _provision("Art. 26(3)"), CFG, set())))


def test_a_number_that_is_written_in_the_text_is_not_flagged():
    good = copy.deepcopy(_GOOD)
    good["requirement"]["mappings"][0]["delta_conditions"][0]["value"] = 6  # "at least six months" ... the digit 6 is in "26(6)"? no: in text only as a word
    entry = _entry(good)
    in_text = "6" in ra._numbers(_provision()["text"])
    flagged = any("not written" in w for w in _warns(ra.mechanical_checks(entry, _provision(), CFG, set())))
    assert flagged is (not in_text)


# ------------------------------------------------------------------ the critique

def test_a_critique_is_parsed_clamped_and_never_guessed():
    parsed = ra.parse_critique(json.dumps(CRITIQUE))
    assert parsed["faithful"] == "partly" and parsed["concerns"] and parsed["suggested_changes"] == ["mention the exception"]
    assert ra.parse_critique("```json\n" + json.dumps(CRITIQUE) + "\n```")["faithful"] == "partly"
    assert ra.parse_critique(json.dumps({"faithful": "definitely"}))["faithful"] == "cannot tell"
    assert len(ra.parse_critique(json.dumps({"concerns": [f"c{i}" for i in range(20)]}))["concerns"]) == 5
    assert "error" in ra.parse_critique("not json") and "error" in ra.parse_critique("[1, 2]")


def test_the_model_is_given_only_the_provision_its_neighbours_and_the_draft():
    gateway = StubGateway(CRITIQUE)
    result = ra.assist(_entry(), _provision(), PROVISIONS, CFG, set(), gateway)
    system, user = gateway.calls[0]
    assert "argue against the draft" in system and "do not approve" in system.lower() or "do NOT approve" in system
    assert _provision()["text"] in user and "RELATED PROVISIONS" in user and "Art. 26(5)" in user
    assert "DRAFT:" in user and "ai_log_retention_days" in user
    assert result["critique"]["faithful"] == "partly" and result["model"] == "critic-model"
    assert result["related"] == ["Art. 26(5)", "Art. 26(7)"]


def test_an_unreachable_model_leaves_the_mechanical_checks_and_an_honest_note():
    result = ra.assist(_entry(), _provision(), PROVISIONS, CFG, set(), StubGateway(RuntimeError("down")))
    assert result["checks"] and "could not be reached" in result["critique"]["error"]
    assert "unavailable" in ra.render(result)
    no_model = ra.assist(_entry(), _provision(), PROVISIONS, CFG, set(), None)
    assert no_model["critique"] is None and "not requested" in ra.render(no_model)


def test_the_critique_is_cached_per_source_and_prompt_and_model():
    entry = _entry()
    gateway = StubGateway(CRITIQUE)
    entry["assist"] = ra.assist(entry, _provision(), PROVISIONS, CFG, set(), gateway)
    ra.assist(entry, _provision(), PROVISIONS, CFG, set(), gateway)
    assert len(gateway.calls) == 1  # not asked again
    other = StubGateway(CRITIQUE)
    other.model = "another-model"
    ra.assist(entry, _provision(), PROVISIONS, CFG, set(), other)
    assert len(other.calls) == 1  # a different reviewer model is a different critique
    ra.assist(entry, _provision(), PROVISIONS, CFG, set(), gateway, force=True)
    assert len(gateway.calls) == 2


def test_the_view_is_labelled_advisory_and_says_when_the_reviewer_is_the_drafter():
    text = ra.render(ra.assist(_entry(), _provision(), PROVISIONS, CFG, set(), StubGateway(CRITIQUE)), drafter="critic-model")
    assert "advisory: nothing here accepts or changes the draft" in text
    assert "faithful to the text? partly" in text and "same model as the drafter" in text
    assert "concern: Art. 26(6) says" in text and "missing context: Art. 26(5)" in text


# ------------------------------------------------------------------ the critique has no power

def _setup(tmp_path, entries):
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    shutil.copy(CONTENT_DIR / "uco.yaml", content_dir / "uco.yaml")
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / "eu-ai-act.yaml").write_text(yaml.safe_dump({"model": "drafter", "drafts": entries}), encoding="utf-8")
    return content_dir, drafts


def test_a_damning_critique_does_not_stop_or_force_an_acceptance(tmp_path, capsys):
    damning = {**CRITIQUE, "faithful": "no", "concerns": ["this contradicts the law"]}
    content_dir, drafts = _setup(tmp_path, [_entry()])
    counts = rev.review("eu-ai-act", ask=lambda _: "a", drafts=drafts, content_dir=content_dir,
                        assist=True, gateway=StubGateway(damning))
    assert counts == {"accepted": 1}  # the human accepted; the model's "no" changed nothing
    assert "this contradicts the law" in capsys.readouterr().out
    req = load(content_dir).requirement("EU-AI-ACT", "Art. 26(6)")
    assert req.mappings[0].delta_conditions[0].value == 183 and all(m.source == "EXPERT" for m in req.mappings)


def test_a_glowing_critique_does_not_accept_anything(tmp_path):
    glowing = {"faithful": "yes", "concerns": [], "missing_context": [], "suggested_changes": []}
    content_dir, drafts = _setup(tmp_path, [_entry()])
    counts = rev.review("eu-ai-act", ask=lambda _: "s", drafts=drafts, content_dir=content_dir,
                        assist=True, gateway=StubGateway(glowing))
    assert counts == {}
    doc = yaml.safe_load((drafts / "eu-ai-act.yaml").read_text(encoding="utf-8"))
    (entry,) = doc["drafts"]
    assert entry["status"] == "pending"                      # still waiting for a person
    assert entry["assist"]["critique"]["faithful"] == "yes"  # advice stored for the next session
    assert not (content_dir / CFG["pack"]).exists()


def test_assist_never_alters_the_draft_it_describes(tmp_path):
    entry = _entry()
    before = copy.deepcopy(entry)
    content_dir, drafts = _setup(tmp_path, [entry])
    rev.review("eu-ai-act", ask=lambda _: "s", drafts=drafts, content_dir=content_dir, assist=True,
               gateway=StubGateway(CRITIQUE))
    (after,) = yaml.safe_load((drafts / "eu-ai-act.yaml").read_text(encoding="utf-8"))["drafts"]
    after.pop("assist")
    assert after == before


def test_review_without_assist_behaves_exactly_as_before(tmp_path):
    content_dir, drafts = _setup(tmp_path, [_entry()])
    counts = rev.review("eu-ai-act", ask=lambda _: "a", drafts=drafts, content_dir=content_dir)
    (entry,) = yaml.safe_load((drafts / "eu-ai-act.yaml").read_text(encoding="utf-8"))["drafts"]
    assert counts == {"accepted": 1} and "assist" not in entry
