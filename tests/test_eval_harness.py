"""The evaluation harness's own plumbing: thermal brake and a rules-only run over
the full corpus (labelled cases plus the demo samples). The model-dependent half
is exercised by `python -m evaluation.runner`, never by CI."""

from __future__ import annotations

import sys

import pytest

from evaluation import runner, thermal


def test_wait_until_cool_returns_when_cool_and_gives_up_when_hot(monkeypatch):
    monkeypatch.setattr(thermal, "gpu_temp", lambda: 60)
    assert thermal.wait_until_cool(70, max_wait_s=1) is True
    monkeypatch.setattr(thermal, "gpu_temp", lambda: 85)
    monkeypatch.setattr(thermal.time, "sleep", lambda s: None)
    assert thermal.wait_until_cool(70, max_wait_s=0) is False   # a hot baseline must stop the run, not run hot


def test_no_nvidia_gpu_means_no_guard(monkeypatch):
    monkeypatch.setattr(thermal.shutil, "which", lambda name: None)
    assert thermal.gpu_temp() is None
    thermal.start_watchdog()  # must be a harmless no-op


def test_watchdog_stops_the_model_and_exits_when_hot(monkeypatch):
    calls = []
    monkeypatch.setattr(thermal, "gpu_temp", lambda: 91)
    monkeypatch.setattr(thermal.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    exited = []
    monkeypatch.setattr(thermal.os, "_exit", lambda code: exited.append(code))
    # run the watch loop body once, synchronously
    import threading
    started = []
    monkeypatch.setattr(threading.Thread, "start", lambda self: started.append(self))
    thermal.start_watchdog(trip_at=88, container="llm-ollama-1")
    class _Stop(Exception):
        pass

    def stop(_seconds):
        raise _Stop    # end the watch loop after one pass (a StopIteration would be rewritten by PEP 479 on 3.11)

    monkeypatch.setattr(thermal.time, "sleep", stop)
    with pytest.raises(_Stop):
        started[0].run()
    assert ["docker", "restart", "llm-ollama-1"] in calls and exited == [3]


def test_rules_only_run_over_the_whole_corpus_passes(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["runner", "--no-model"])
    assert runner.main() == 0
    out = capsys.readouterr().out
    assert "policy-asteron" in out and "scan-expired" in out   # the demo samples are part of the corpus


def test_every_sample_case_has_ground_truth():
    cases = runner.sample_cases()
    assert cases and all(c["attributes"] and c["verdicts"] for c in cases)
    assert all(c["name"] != "scan-misfiled" for c in cases)   # meant to be misread; measured by the guard


def test_watchdog_can_stop_an_lm_studio_model_and_log_temperatures(monkeypatch, tmp_path):
    calls = []
    temps = iter([70, 80, 91])
    monkeypatch.setattr(thermal, "gpu_temp", lambda: next(temps))
    monkeypatch.setattr(thermal.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    exited = []
    monkeypatch.setattr(thermal.os, "_exit", lambda code: exited.append(code))
    import threading
    started = []
    monkeypatch.setattr(threading.Thread, "start", lambda self: started.append(self))
    log = tmp_path / "temps.log"
    thermal.start_watchdog(trip_at=88, container=None, stop_cmd=["lms", "unload", "--all"], log_path=str(log))
    monkeypatch.setattr(thermal.time, "sleep", lambda s: None)

    class _Stop(Exception):
        pass

    n = {"i": 0}
    def sleep_then_stop(_s):
        n["i"] += 1
        if n["i"] > 5:
            raise _Stop
    monkeypatch.setattr(thermal.time, "sleep", sleep_then_stop)
    monkeypatch.setattr(thermal.os, "_exit", lambda code: (exited.append(code), (_ for _ in ()).throw(_Stop()))[0])
    with pytest.raises(_Stop):
        started[0].run()
    assert ["lms", "unload", "--all"] in calls and exited == [3] and ["docker", "restart", "llm-ollama-1"] not in calls
    # the first reading (70) is the "is there a GPU at all" probe; 80 is logged; 91 trips and is not
    assert [l.split()[1] for l in log.read_text().splitlines()] == ["80"]
