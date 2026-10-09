"""A local JevBench: candidate decision models on the platform's own typed decisions.

    python -m evaluation.decisions --model qwen2.5vl:7b --model h2o-lightning-4b
    python -m evaluation.decisions --model decider-12b --provider openai --base-url http://gpu:8000
    python -m evaluation.decisions --model h2o-lightning-4b --task quote --save

JevBench (benchmarkheaven.com/jev-models) ranks Jev-class models on intelligence, calibration,
speed and cost over general decisions. This asks the same of *our* decisions, with the exact
prompts production sends (app/ai/decision.py, ADR-025):

  type    which artefact type a document is (the upload suggestion and wrong-document guard)
  quote   does a cited quote state an extracted value (the hallucination check)
  rights  which kind of data-principal request a message is

Per model it reports accuracy (intelligence), Brier score and ECE (calibration), p50 latency
per model call (speed, on JevBench's log scale: 80 = 1 s, 90 = 316 ms), how often the top
answer changes with the option order (position stability), and what the production guards
would have done at their current thresholds. Self-hosted, so cost is the machine's, not a
price per call: it is not scored. Ground truth lives in evaluation/labels/, the demo samples
and evaluation/decision_cases/; when a model disagrees it is the model that is wrong.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from app import documents, service
from app.ai import decision
from app.ai.provider import decision_only
from app.routers.rights_requests import KIND_OPTIONS, KIND_QUESTION, kind_state
from evaluation import samples as demo_samples
from evaluation.runner import RESULTS, load_cases

CASES = Path(__file__).parent / "decision_cases"
STABILITY_ORDERS = 3  # every case is asked in at least this many orders, to measure stability
TASKS = ("type", "quote", "rights")


# ---------------------------------------------------------------- cases

def type_cases() -> list[dict]:
    """Every labelled document and demo sample, filed as what it is; misfiled samples also
    filed as what the presenter uploads them as, which the guard must catch."""
    cases = []
    for case in load_cases():
        text = documents.to_text(documents.parse(case["path"].name, case["path"].read_bytes()))
        if text.strip():
            cases.append({"name": case["name"], "filename": case["path"].name, "text": text,
                          "expected": case["artefact_type"], "declared": case["artefact_type"]})
    for r in demo_samples.rendered(runid="eval"):
        cases.append({"name": r["id"], "filename": r["filename"], "text": r["text"],
                      "expected": r["artefact_type"], "declared": r.get("upload_as") or r["artefact_type"]})
    return cases


def _fixture(name: str) -> list[dict]:
    return json.loads((CASES / f"{name}.json").read_text(encoding="utf-8"))["cases"]


def asks(task: str) -> list[dict]:
    """Each case as production would ask it: question, state, options, orders, truth."""
    if task == "type":
        return [{"name": c["name"], "question": service.CLASSIFY_QUESTION,
                 "state": service.classify_state(c["filename"], c["text"]), "options": service.ARTEFACT_TYPES,
                 "orders": service.CLASSIFY_ORDERS, "expected": c["expected"], "declared": c["declared"]}
                for c in type_cases()]
    if task == "quote":
        return [{"name": f"{c['attribute']}={c['value']!r}", "question": service.SUPPORT_QUESTION,
                 "state": service.support_state(c["attribute"], c["value"], c["quote"]),
                 "options": service.SUPPORT_OPTIONS, "orders": 1, "expected": c["expected"]}
                for c in _fixture("quote_support")]
    return [{"name": c["details"][:40], "question": KIND_QUESTION, "state": kind_state(c["details"]),
             "options": KIND_OPTIONS, "orders": 1, "expected": c["expected"]}
            for c in _fixture("rights_requests")]


# ---------------------------------------------------------------- metrics

def brier(probabilities: dict[str, float], truth: str, options) -> float:
    """Multi-class Brier score halved to 0..1: 0 is certain and right, 1 certain and wrong.
    No answer counts as the uniform distribution: it said nothing, so it knew nothing."""
    keys = list(options)
    p = probabilities or {k: 1 / len(keys) for k in keys}
    return sum((p.get(k, 0.0) - (k == truth)) ** 2 for k in keys) / 2


def ece(points: list[tuple[float, bool]], bins: int = 10) -> float:
    """Expected calibration error over (top confidence, was it right): how far stated
    confidence is from the accuracy actually achieved at that confidence."""
    if not points:
        return 0.0
    total = 0.0
    for b in range(bins):
        low, high = b / bins, (b + 1) / bins
        group = [(c, ok) for c, ok in points if low < c <= high or (b == 0 and c == 0)]
        if group:
            confidence = sum(c for c, _ in group) / len(group)
            accuracy = sum(ok for _, ok in group) / len(group)
            total += len(group) / len(points) * abs(confidence - accuracy)
    return total


def speed_score(p50_ms: float) -> float:
    """JevBench's median-latency scale: 100 at 100 ms, minus 20 per tenfold slower."""
    if p50_ms <= 0:
        return 100.0
    return max(0.0, min(100.0, 100 - 20 * math.log10(p50_ms / 100)))


def harmonic(*scores: float) -> float:
    return 0.0 if min(scores) <= 0 else len(scores) / sum(1 / s for s in scores)


# ---------------------------------------------------------------- running

def run_task(gateway, task: str) -> dict:
    rows, call_ms = [], []
    for ask in asks(task):
        orders = max(ask["orders"], STABILITY_ORDERS)
        start = time.monotonic()
        results = decision.passes(gateway, ask["question"], ask["state"], ask["options"], orders)
        elapsed = (time.monotonic() - start) * 1000
        if results:
            call_ms += [elapsed / len(results)] * len(results)
        # The answer production would have given: the same first passes, combined the same way.
        answer = decision.combine(results[:ask["orders"]])
        top = decision.top(answer)
        rows.append({
            "case": ask["name"], "expected": ask["expected"], "answer": top,
            "confidence": answer.get(top, 0.0) if top else 0.0, "correct": top == ask["expected"],
            "brier": brier(answer, ask["expected"], ask["options"]),
            "unanswered": not answer, "order_dependent": bool(results) and not decision.stable(results),
            "probabilities": answer, "declared": ask.get("declared"),
        })
    return summarise(task, rows, call_ms)


def summarise(task: str, rows: list[dict], call_ms: list[float]) -> dict:
    n = len(rows) or 1
    accuracy = sum(r["correct"] for r in rows) / n
    mean_brier = sum(r["brier"] for r in rows) / n
    p50 = statistics.median(call_ms) if call_ms else 0.0
    summary = {
        "task": task, "cases": len(rows), "accuracy": accuracy, "brier": mean_brier,
        "ece": ece([(r["confidence"], r["correct"]) for r in rows if not r["unanswered"]]),
        "unanswered": sum(r["unanswered"] for r in rows),
        "order_dependent": sum(r["order_dependent"] for r in rows),
        "p50_call_ms": p50,
        "intelligence": accuracy * 100, "calibration": (1 - mean_brier) * 100, "speed": speed_score(p50),
        "guard": guard(task, rows), "rows": rows,
    }
    summary["score"] = harmonic(summary["intelligence"], summary["calibration"], summary["speed"])
    return summary


def guard(task: str, rows: list[dict]) -> dict:
    """What production would have flagged at today's thresholds (app/service.py)."""
    if task == "type":
        flags = [(r["declared"] != r["expected"], service.mismatch(r["probabilities"], r["declared"]) is not None)
                 for r in rows]
        rule = f"MISMATCH_TOP={service.MISMATCH_TOP}, MISMATCH_DECLARED_MAX={service.MISMATCH_DECLARED_MAX}"
    elif task == "quote":
        flags = [(r["expected"] == "NO", r["probabilities"].get("NO", 0.0) >= service.UNSUPPORTED_MIN)
                 for r in rows]
        rule = f"UNSUPPORTED_MIN={service.UNSUPPORTED_MIN}"
    else:
        return {}
    return {"rule": rule,
            "caught": sum(bad and flagged for bad, flagged in flags), "should_catch": sum(bad for bad, _ in flags),
            "false_alarms": sum(flagged and not bad for bad, flagged in flags),
            "fine": sum(not bad for bad, _ in flags)}


def evaluate_model(gateway, tasks=TASKS) -> dict:
    per_task = {task: run_task(gateway, task) for task in tasks}
    axes = {axis: statistics.mean(t[axis] for t in per_task.values())
            for axis in ("intelligence", "calibration", "speed")}
    return {"model": getattr(gateway, "model", ""), "provider": getattr(gateway, "provider", ""),
            **axes, "score": harmonic(*axes.values()), "tasks": per_task}


# ---------------------------------------------------------------- report

def report(result: dict) -> None:
    print(f"\n  {result['model']} ({result['provider']})  score {result['score']:.1f}  |  intelligence "
          f"{result['intelligence']:.1f}  calibration {result['calibration']:.1f}  speed {result['speed']:.1f}")
    for t in result["tasks"].values():
        print(f"    {t['task']:<7} {t['cases']:>3} cases  accuracy {t['accuracy']:.0%}  brier {t['brier']:.3f}"
              f"  ece {t['ece']:.3f}  p50 {t['p50_call_ms']:.0f} ms/call  order-dependent {t['order_dependent']}"
              f"  unanswered {t['unanswered']}")
        g = t["guard"]
        if g:
            print(f"            guard ({g['rule']}): caught {g['caught']}/{g['should_catch']},"
                  f" false alarms {g['false_alarms']}/{g['fine']}")
        for r in t["rows"]:
            if not r["correct"]:
                print(f"            x {r['case']}: expected {r['expected']}, answered {r['answer']}"
                      f" ({r['confidence']:.2f})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", action="append", required=True, help="a model to measure (repeatable)")
    parser.add_argument("--provider", default="", help="ollama or openai (default: LLM_DECISION_PROVIDER, "
                                                       "then LLM_PROVIDER)")
    parser.add_argument("--base-url", default="", help="the model server (default: LLM_DECISION_BASE_URL, "
                                                       "then the provider's own)")
    parser.add_argument("--task", action="append", choices=TASKS, help="limit to these tasks (repeatable)")
    parser.add_argument("--save", action="store_true", help="write a JSON result to evaluation/results/")
    args = parser.parse_args(argv)

    results = []
    for model in args.model:
        gateway = decision_only(model, args.provider, args.base_url)
        if not gateway.available():
            print(f"  ! {model}: the model server is not reachable, or the model is not loaded")
            continue
        result = evaluate_model(gateway, tuple(args.task or TASKS))
        report(result)
        results.append(result)

    if len(results) > 1:
        print("\n  ranking (harmonic mean of intelligence, calibration, speed)")
        for i, r in enumerate(sorted(results, key=lambda r: -r["score"]), 1):
            print(f"    {i}. {r['model']:<32} {r['score']:5.1f}")
    if args.save and results:
        RESULTS.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out = RESULTS / f"decisions-{stamp}.json"
        out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        print(f"\n  saved {out}")
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
