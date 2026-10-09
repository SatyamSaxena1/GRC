"""The local JevBench (evaluation/decisions.py): its metrics, and that it asks exactly what
production asks. The model-dependent half runs with `python -m evaluation.decisions`, never in CI."""

from __future__ import annotations

import math

import pytest

from evaluation import decisions


class Oracle:
    """Knows every case's answer and gives it `share` of the probability, in any order."""
    model, provider = "oracle", "fake"

    def __init__(self, truth: dict[str, str], share: float = 0.9):
        self.truth, self.share = truth, share

    def available(self):
        return True

    def next_token_logprobs(self, system, user, top=20):
        state = user.split("\n\nOptions:\n")[0]
        listing = user.split("Options:\n")[1].split("\n\n")[0].splitlines()
        answer = next(self.truth[s] for s in self.truth if s in state)
        letters = [line[0] for line in listing]
        rest = (1 - self.share) / (len(letters) - 1)
        return {l: math.log(self.share if f") {answer}:" in line else rest) for l, line in zip(letters, listing)}


class FirstListed(Oracle):
    """Always the first option: confident, and only ever right by position."""
    def next_token_logprobs(self, system, user, top=20):
        return {"A": math.log(0.95), "B": math.log(0.05)}


def _truth():
    return {a["state"]: a["expected"] for task in decisions.TASKS for a in decisions.asks(task)}


def test_the_corpus_is_there_and_asks_what_production_asks():
    from app import service
    types = decisions.asks("type")
    assert any(a["declared"] != a["expected"] for a in types)  # the misfiled scan is in it
    assert all(a["question"] == service.CLASSIFY_QUESTION and a["orders"] == service.CLASSIFY_ORDERS for a in types)
    quotes = decisions.asks("quote")
    assert {a["expected"] for a in quotes} == {"YES", "NO"}
    rights = decisions.asks("rights")
    assert "NOT_A_REQUEST" in {a["expected"] for a in rights}


def test_a_model_that_is_always_right_scores_top_marks_and_catches_everything():
    result = decisions.evaluate_model(Oracle(_truth()))
    for task in result["tasks"].values():
        assert task["accuracy"] == 1.0 and task["order_dependent"] == 0 and task["unanswered"] == 0
        assert task["guard"].get("false_alarms", 0) == 0
        assert task["guard"].get("caught", 0) == task["guard"].get("should_catch", 0)
    assert result["intelligence"] == 100 and result["calibration"] > 95


def test_a_position_biased_model_is_exposed():
    result = decisions.evaluate_model(FirstListed({}), tasks=("type", "quote"))
    assert result["tasks"]["type"]["order_dependent"] == result["tasks"]["type"]["cases"]
    assert result["tasks"]["type"]["unanswered"] == result["tasks"]["type"]["cases"]  # production says nothing
    quote = result["tasks"]["quote"]
    assert quote["order_dependent"] == quote["cases"] and quote["accuracy"] == pytest.approx(0.5, abs=0.1)


def test_brier_ece_and_speed():
    options = ["A", "B"]
    assert decisions.brier({"A": 1.0, "B": 0.0}, "A", options) == 0
    assert decisions.brier({"A": 0.0, "B": 1.0}, "A", options) == 1
    assert decisions.brier({}, "A", options) == 0.25  # no answer is the uniform guess
    assert decisions.ece([(0.9, True)] * 9 + [(0.9, False)]) == pytest.approx(0.0)
    assert decisions.ece([(1.0, False)] * 4) == pytest.approx(1.0)
    assert decisions.speed_score(1000) == pytest.approx(80)  # JevBench: 1 s is 80
    assert decisions.speed_score(316) == pytest.approx(90, abs=0.1)
    assert decisions.harmonic(50, 100) == pytest.approx(66.67, abs=0.01) and decisions.harmonic(0, 90) == 0


def test_the_command_reports_an_unreachable_model_and_fails(monkeypatch, capsys):
    class Down(Oracle):
        def available(self):
            return False
    monkeypatch.setattr(decisions, "decision_only", lambda *a: Down({}))
    assert decisions.main(["--model", "missing"]) == 1
    assert "not reachable" in capsys.readouterr().out
