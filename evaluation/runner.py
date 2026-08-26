"""Run the golden corpus and report whether automation is safe to enable.

    python -m evaluation.runner                 # whole corpus
    python -m evaluation.runner --no-model      # rules only, no extraction
    python -m evaluation.runner --case iso_pci_access_policy_v1

Each case is a document in evaluation/dataset/ plus a label file in
evaluation/labels/ naming the expected attributes, their source pages, and the
expected verdict per clause. Labels are ground truth: when the system disagrees,
the report says so — it is never the label that gets edited to make a run pass.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from app.content.load import load as load_content
from app.evaluate import evaluate
from app.ingest import extract_attributes, read_document
from evaluation.metrics import Report, values_match

DATASET = Path(__file__).parent / "dataset"
LABELS = Path(__file__).parent / "labels"
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


def run_case(case: dict, content, report: Report, use_model: bool) -> None:
    report.documents += 1
    expected_attributes = case.get("attributes", {})

    if use_model:
        text, method = read_document(case["path"].name, case["path"].read_bytes())
        run = extract_attributes(text, list(expected_attributes), method)
        actual = {name: field.value for name, field in run.fields.items()}
        pages = {name: [s.page for s in field.sources] for name, field in run.fields.items()}
        if run.status != "OK":
            report.failures.append(f"{case['name']}: extraction status {run.status}")
    else:
        actual = {k: v["value"] for k, v in expected_attributes.items()}
        pages = {k: v.get("pages", []) for k, v in expected_attributes.items()}

    for name, expectation in expected_attributes.items():
        ok = values_match(expectation["value"], actual.get(name))
        report.attribute.add(ok)
        if name in CRITICAL:
            report.critical_attribute.add(ok)
        if name in DATE_FIELDS:
            report.dates.add(ok)
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
        actual, case["artefact_type"], case["frameworks"], content, as_of=as_of)}

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
    args = parser.parse_args()

    content = load_content()
    cases = load_cases(args.case)
    if not cases:
        print("no cases found — add documents to evaluation/dataset and labels to evaluation/labels")
        return 1

    report = Report()
    for case in cases:
        run_case(case, content, report, use_model=not args.no_model)

    mode = "labels only (rule engine)" if args.no_model else "live extraction"
    print(f"\n=== golden evaluation: {report.documents} document(s), {mode} ===")
    for name, value in report.summary().items():
        print(f"  {name:32} {value}")

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

    return 0 if report.passed() else 2


if __name__ == "__main__":
    sys.exit(main())
