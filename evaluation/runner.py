"""Run the golden corpus and report whether automation is safe to enable.

    python -m evaluation.runner                 # whole corpus (labels + demo samples)
    python -m evaluation.runner --no-model      # rules only, no extraction
    python -m evaluation.runner --case policy-asteron --repeats 5 --model qwen2.5vl:7b
    python -m evaluation.runner --repeats 3 --save   # writes evaluation/results/<time>.json

Each case is a document in evaluation/dataset/ plus a label file in
evaluation/labels/ naming the expected attributes, their source pages, and the
expected verdict per clause. Labels are ground truth: when the system disagrees,
the report says so — it is never the label that gets edited to make a run pass.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import time

from app.content.load import load as load_content
from app.evaluate import evaluate
from app.ingest import extract_attributes, gateway_for, read_document
from app.service import _restore_cadence_words, required_attribute_names
from evaluation import samples as demo_samples
from evaluation import thermal
from evaluation.metrics import Report, values_match

DATASET = Path(__file__).parent / "dataset"
LABELS = Path(__file__).parent / "labels"
RESULTS = Path(__file__).parent / "results"
CRITICAL = {"password_min_length", "approval_date", "effective_date", "scan_expiry_date",
            "systems_covered", "mfa_required_for", "access_review_frequency_days",
            "compliance_status", "scan_completed_date"}
DATE_FIELDS = {"approval_date", "effective_date", "issue_date", "review_date",
               "next_review_date", "expiry_date", "scan_completed_date", "scan_expiry_date"}


def load_cases(only: str | None = None) -> list[dict]:
    cases = []
    for label_path in sorted(LABELS.glob("*.json")):
        case = json.loads(label_path.read_text(encoding="utf-8"))
        case["name"] = label_path.stem
        case["path"] = DATASET / case["document"]
        if only and case["name"] != only:
            continue
        if not case["path"].exists():
            print(f"  ! missing document for {case['name']}: {case['path']}")
            continue
        cases.append(case)
    return cases


def sample_cases(only: str | None = None) -> list[dict]:
    """The demo library as cases: the same documents a presenter uploads, with their
    ground-truth attributes and rule-derived verdicts. Samples that are *meant* to be
    misread (a file uploaded as the wrong type) are measured by the guard, not here."""
    today = date.today()
    cases = []
    for r in demo_samples.rendered(today, runid="eval"):
        if r.get("upload_as") or (only and r["id"] != only):
            continue
        cases.append({
            "name": r["id"], "text": r["text"], "filename": r["filename"],
            "artefact_type": r["artefact_type"], "frameworks": demo_samples.load()["frameworks"],
            "as_of": today.isoformat(), "commitments": r.get("commitments"),
            "attributes": {k: {"value": v} for k, v in r["attrs"].items()},
            "verdicts": r["expect"], "closed_world": True,
        })
    return cases


def run_case(case: dict, content, report: Report, use_model: bool, gateway=None,
             repeats: int = 1, guard: bool = False) -> None:
    report.documents += 1
    expected_attributes = case.get("attributes", {})

    seen: dict[str, list] = {}          # attribute -> the value each repeat returned
    if use_model:
        if "text" in case:
            text, method = case["text"], "native_text"
        else:
            text, method = read_document(case["path"].name, case["path"].read_bytes(), gateway=gateway)
        # Ask exactly what production asks (every attribute any pack wants of this
        # type), not only the labelled few: neighbours and position change what the
        # model returns, so a trimmed question measures a different system.
        asked = required_attribute_names(content, case["frameworks"], case["artefact_type"])
        for _ in range(repeats):
            if guard and not thermal.wait_until_cool(70):
                raise SystemExit("GPU will not cool below 70C (an overlay or other load?) - stopping.")
            run = extract_attributes(text, asked, method, gateway=gateway)
            _restore_cadence_words(run)  # the production pipeline does this before evaluating
            report.runs += 1
            report.latencies_ms.append(run.latency_ms)
            if run.status in ("UNAVAILABLE", "ERROR"):
                # The model never answered: scoring the resulting nulls would print a
                # plausible-looking accuracy for a run that measured nothing.
                raise SystemExit(f"model unreachable ({run.status}) on {case['name']} - aborting, "
                                 f"nothing was measured. Check the host / tunnel / loaded model.")
            if run.status != "OK":
                report.invalid_runs += run.status == "INVALID_OUTPUT"
                report.failures.append(f"{case['name']}: extraction status {run.status}")
            for name in expected_attributes:
                field = run.fields.get(name)
                seen.setdefault(name, []).append(field.value if field else None)
            if case.get("closed_world"):
                # A sample's label lists every fact its text states, so any other
                # attribute the model fills in was invented (the label cannot say
                # "absent" for a real document it only partly annotates).
                for name, field in run.fields.items():
                    if name not in expected_attributes and field.value is not None:
                        report.spurious.add(True)
                        report.spurious_list.append(f"{case['name']}.{name}: {field.value!r}")
                    elif name not in expected_attributes:
                        report.spurious.add(False)
            last = run
        actual = {name: field.value for name, field in last.fields.items()}
        pages = {name: [s.page for s in field.sources] for name, field in last.fields.items()}
    else:
        actual = {k: v["value"] for k, v in expected_attributes.items()}
        pages = {k: v.get("pages", []) for k, v in expected_attributes.items()}

    for name, expectation in expected_attributes.items():
        # Every repeat is scored (a flaky attribute must cost accuracy); the stability
        # table then shows which attributes disagreed with themselves.
        for value in (seen.get(name) or [actual.get(name)]):
            ok_run = report.add_attribute(name, expectation["value"], value)
            report.attribute.add(ok_run)
            if name in CRITICAL:
                report.critical_attribute.add(ok_run)
            if name in DATE_FIELDS:
                report.dates.add(ok_run)
        runs_seen = seen.get(name, [])
        # "quarterly", 90 and "every 90 days" are one answer: only a real disagreement is unstable.
        if any(not values_match(runs_seen[0], v) for v in runs_seen[1:]):
            report.unstable.append(f"{case['name']}.{name}: {seen[name]!r}")
        report.unstable_total += 1 if seen.get(name) else 0
        ok = values_match(expectation["value"], actual.get(name))
        if not ok:
            report.failures.append(
                f"{case['name']}.{name}: expected {expectation['value']!r}, got {actual.get(name)!r}")
        if expectation.get("pages") and use_model:
            got = pages.get(name) or []
            if not set(expectation["pages"]) & set(got):
                report.failures.append(
                    f"{case['name']}.{name}: expected page(s) {expectation['pages']}, got {got}")

    # Freshness is relative: a case declares the audit date it is judged against,
    # so "stale" is reproducible instead of drifting with the calendar.
    as_of = date.fromisoformat(case["as_of"]) if case.get("as_of") else None
    links = {(l.framework, l.clause): l for l in evaluate(
        actual, case["artefact_type"], case["frameworks"], content, as_of=as_of,
        org_commitments=case.get("commitments"))}

    for key, expected_verdict in case.get("verdicts", {}).items():
        framework, clause = key.split(" ", 1)
        link = links.get((framework, clause))
        got = link.verdict if link else "NO_LINK"
        correct = got == expected_verdict
        report.verdicts.add(correct)
        if not correct:
            report.failures.append(f"{case['name']}: {key} expected {expected_verdict}, got {got}")

        # Auto-accept precision: of what we would accept unreviewed, how much was right.
        if got == "PASS":
            report.auto_accept.add(expected_verdict == "PASS")

    for key, attributes in case.get("gap_attributes", {}).items():
        framework, clause = key.split(" ", 1)
        link = links.get((framework, clause))
        got = sorted({g.attribute for g in link.gaps}) if link else []
        report.gap_reasons.add(got == sorted(attributes))
        if got != sorted(attributes):
            report.failures.append(f"{case['name']}: {key} gaps expected {sorted(attributes)}, got {got}")

    for key in case.get("stale", []):
        framework, clause = key.split(" ", 1)
        link = links.get((framework, clause))
        detected = bool(link) and any(g.kind == "STALE" for g in link.gaps)
        report.stale_detection.add(detected)
        if not detected:
            report.failures.append(f"{case['name']}: {key} expected a STALE gap, none raised")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", help="run a single case by name")
    parser.add_argument("--no-model", action="store_true",
                        help="use labelled attributes instead of calling the model; "
                             "isolates rule-engine accuracy from extraction accuracy")
    parser.add_argument("--repeats", type=int, default=1,
                        help="extract each document N times and report run-to-run stability")
    parser.add_argument("--model", help="Ollama model name (default: OLLAMA_MODEL)")
    parser.add_argument("--no-samples", action="store_true", help="skip the demo-sample corpus")
    parser.add_argument("--save", action="store_true", help="write a JSON result to evaluation/results/")
    parser.add_argument("--no-thermal", action="store_true",
                        help="disable the GPU thermal guard (start <=70C, trip at 88C)")
    parser.add_argument("--no-cooldown", action="store_true",
                        help="do not wait for the GPU to cool between extractions (the watchdog stays on): "
                             "the worst case a busy upload produces, for measuring sustained heat")
    parser.add_argument("--trip-at", type=int, default=88)
    parser.add_argument("--guard-container", default="llm-ollama-1",
                        help="container restarted when the watchdog trips, to stop generation ('' for none)")
    parser.add_argument("--guard-stop", default="",
                        help="command run when the watchdog trips, e.g. 'lms unload --all' for LM Studio")
    parser.add_argument("--temp-log", default="", help="append a GPU temperature sample every 0.25 s to this file")
    args = parser.parse_args()

    guard = not args.no_model and not args.no_thermal and thermal.gpu_temp() is not None
    if not args.no_model:
        if guard:
            print(f"thermal guard on: start <=70C, trip at {args.trip_at}C (restarts {args.guard_container})")
            thermal.start_watchdog(args.trip_at, args.guard_container or None, 0.25,
                                   args.guard_stop.split() or None, args.temp_log or None)
        else:
            print("NOTE: running without the thermal guard (no NVIDIA GPU visible, or --no-thermal)")
    gateway = gateway_for(args.model) if args.model else None

    content = load_content()
    cases = load_cases(args.case) + ([] if args.no_samples else sample_cases(args.case))
    if not cases:
        print("no cases found — add documents to evaluation/dataset and labels to evaluation/labels")
        return 1

    report = Report()
    for case in cases:
        started = time.monotonic()
        run_case(case, content, report, use_model=not args.no_model, gateway=gateway,
                 repeats=args.repeats, guard=guard and not args.no_cooldown)
        print(f"  ran {case['name']} ({time.monotonic() - started:.0f}s)", flush=True)

    mode = "labels only (rule engine)" if args.no_model else "live extraction"
    print(f"\n=== golden evaluation: {report.documents} document(s), {mode} ===")
    for name, value in report.summary().items():
        print(f"  {name:32} {value}")

    if not args.no_model:
        model = gateway.model if gateway else "default"
        mean_ms = sum(report.latencies_ms) / len(report.latencies_ms) if report.latencies_ms else 0
        print(f"\n  model {model} | {report.runs} extraction run(s) | invalid/truncated {report.invalid_runs}"
              f" | mean {mean_ms / 1000:.1f}s | missed {report.missed.hits} (said nothing)"
              f" vs wrong {report.wrong.hits} (said something false)")
        if report.spurious.total:
            print(f"  invented (stated nowhere in the sample): {report.spurious.hits} of {report.spurious.total} "
                  f"attribute answers that should have been null")
            for line in report.spurious_list[:12]:
                print(f"    ! {line}")
        print("\n  per attribute (worst first)")
        for name, acc, hits, total in report.attribute_table():
            print(f"    {acc:5.0%}  {hits:>3}/{total:<3} {name}")
        if args.repeats > 1:
            print(f"\n  unstable across {args.repeats} repeats: {len(report.unstable)} of {report.unstable_total}")
            for line in report.unstable[:20]:
                print(f"    ~ {line}")

    gates = report.gate_results()
    if gates:
        print("\n  quality gates")
        for name, ok in gates.items():
            print(f"    {'PASS' if ok else 'FAIL'}  {name} >= {Report.GATES[name]}")
    else:
        print("\n  quality gates: not evaluated (no scored cases)")

    if report.failures:
        print(f"\n  {len(report.failures)} discrepancy(ies):")
        for failure in report.failures[:40]:
            print(f"    - {failure}")

    if not args.no_model and report.documents < 20:
        print(f"\n  NOTE: {report.documents} documents is below the 20-30 the gates assume. "
              f"Treat these numbers as indicative, not as clearance for auto-accept.")

    if args.save:
        RESULTS.mkdir(exist_ok=True)
        tag = re.sub(r"[^A-Za-z0-9._-]+", "_", gateway.model if gateway else "default")  # model names contain : and /
        out = RESULTS / f"{time.strftime('%Y%m%d-%H%M%S')}-{tag}.json"
        out.write_text(json.dumps({
            "summary": report.summary(), "repeats": args.repeats, "runs": report.runs,
            "invalid_runs": report.invalid_runs, "missed": report.missed.hits, "wrong": report.wrong.hits,
            "per_attribute": {n: {"accuracy": round(a, 4), "hits": h, "total": t}
                              for n, a, h, t in report.attribute_table()},
            "unstable": report.unstable, "failures": report.failures,
            "invented": report.spurious.hits, "invented_of": report.spurious.total,
            "invented_list": report.spurious_list,
        }, indent=1), encoding="utf-8")
        print(f"\n  saved {out}")

    return 0 if report.passed() else 2


if __name__ == "__main__":
    sys.exit(main())
