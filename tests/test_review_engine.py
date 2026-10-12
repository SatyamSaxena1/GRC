"""The deterministic review engine (ADR-027): every rule kind, repeatable output, no code text in
any finding, and unknown never reading as a pass."""

from __future__ import annotations

import json

import pytest

from app.review import diff, engine, standards


def _std(*rules: str) -> standards.Standard:
    return standards.parse("name: test\nrules:\n" + "\n".join(rules))


def _files(*entries) -> list[diff.FileDiff]:
    """(path, [added lines]) or (path, [added lines], status)."""
    out = []
    for path, lines, *status in entries:
        out.append(diff.FileDiff(path=path, status=status[0] if status else "modified",
                                 added=[(i + 1, text) for i, text in enumerate(lines)]))
    return out


FORBID_PRINT = """  - id: no-print
    title: No print debugging
    kind: forbid_added
    pattern: '^\\s*print\\('
    paths: ["app/*.py"]
    exclude: ["app/scripts/*"]
    severity: medium
    action: block"""


def test_forbid_added_matches_added_lines_in_scope_only():
    files = _files(("app/x.py", ["x = 1", "print(x)"]), ("app/scripts/y.py", ["print(1)"]), ("lib/z.py", ["print(2)"]))
    result = engine.review(_std(FORBID_PRINT), files)
    assert [(f.path, f.line, f.rule_id, f.blocking) for f in result.findings] == [("app/x.py", 2, "no-print", True)]
    assert result.blocking


def test_a_secret_finding_carries_neither_the_value_nor_any_fingerprint_of_it(monkeypatch):
    monkeypatch.setenv("REVIEW_FINGERPRINT_KEY", "k")
    secret = 'KEY = "AKIAABCDEFGHIJKLMNOP"'
    result = engine.review(_std("""  - id: secrets
    title: No secrets
    kind: secret_scan"""), _files(("app/x.py", [secret])))
    assert "AKIA" not in json.dumps(result.as_dict())
    assert result.findings[0].fingerprint is None


def test_other_findings_carry_a_keyed_fingerprint_and_none_without_a_key(monkeypatch):
    files = _files(("app/x.py", ["print(1)"]))
    monkeypatch.delenv("REVIEW_FINGERPRINT_KEY", raising=False)
    assert engine.review(_std(FORBID_PRINT), files).findings[0].fingerprint is None  # never a plain hash
    monkeypatch.setenv("REVIEW_FINGERPRINT_KEY", "k1")
    one = engine.review(_std(FORBID_PRINT), files).findings[0].fingerprint
    monkeypatch.setenv("REVIEW_FINGERPRINT_KEY", "k2")
    assert one and one != engine.review(_std(FORBID_PRINT), files).findings[0].fingerprint


@pytest.mark.parametrize("line, detector", [
    ('aws = "AKIAABCDEFGHIJKLMNOP"', "aws_access_key"),
    ("token: ghp_" + "a" * 36, "github_token"),
    ("-----BEGIN RSA PRIVATE KEY-----", "private_key"),
    ("SLACK=xoxb-1234567890-abcdef", "slack_token"),
    ('password = "hunter2hunter2"', "password_literal"),
])
def test_each_secret_detector_fires(line, detector):
    result = engine.review(_std("""  - id: secrets
    title: No secrets
    kind: secret_scan"""), _files(("a.py", [line])))
    assert len(result.findings) == 1 and detector in result.findings[0].message


@pytest.mark.parametrize("line", ['password = os.environ["DB_PASSWORD"]', "AKIA is the prefix of AWS keys",
                                  'token = ""', "ghp_short", "# BEGIN PUBLIC KEY"])
def test_secret_look_alikes_do_not_fire(line):
    result = engine.review(_std("""  - id: secrets
    title: No secrets
    kind: secret_scan"""), _files(("a.py", [line])))
    assert result.findings == ()


def test_forbid_dependency_reads_each_manifest_kind():
    rule = """  - id: banned
    title: Banned packages
    kind: forbid_dependency
    packages: [left-pad, PyYAML_Unsafe, "@evil/pkg"]
    action: block"""
    files = _files(("requirements.txt", ["pyyaml-unsafe==1.0", "# left-pad", "requests"]),
                   ("web/package.json", ['    "left-pad": "^1.3.0",', '    "@evil/pkg": "1.0.0"']),
                   ("pyproject.toml", ['    "left_pad>=1",']),
                   ("app/x.py", ['import left_pad']))
    found = [(f.path, f.line) for f in engine.review(_std(rule), files).findings]
    assert found == [("pyproject.toml", 1), ("requirements.txt", 1), ("web/package.json", 1), ("web/package.json", 2)]


def test_require_companion_wants_a_test_change_with_code():
    rule = """  - id: tests
    title: Code needs tests
    kind: require_companion
    paths: ["app/*"]
    action: block"""
    assert engine.review(_std(rule), _files(("app/x.py", ["x"]))).blocking
    assert not engine.review(_std(rule), _files(("app/x.py", ["x"]), ("tests/test_x.py", ["t"]))).findings
    assert not engine.review(_std(rule), _files(("app/x.py", [], "deleted"))).findings  # deleting needs no test
    assert not engine.review(_std(rule), _files(("docs/x.md", ["d"]))).findings


def test_max_change_and_judged_rules_never_block():
    std = _std("""  - id: small
    title: Keep changes small
    kind: max_change
    max_added_lines: 2""", """  - id: names
    title: Clear names
    kind: judged
    text: Functions are named for what they do.""")
    result = engine.review(std, _files(("a.py", ["1", "2", "3"])))
    assert [f.rule_id for f in result.findings] == ["small"] and not result.blocking
    assert result.not_evaluated == ("names",)
    with pytest.raises(standards.StandardError, match="can never block"):
        _std("""  - id: names
    title: Clear names
    kind: judged
    text: x
    action: block""")


def test_a_pattern_that_times_out_is_a_finding_never_a_pass():
    std = _std("""  - id: slow
    title: Catastrophic
    kind: forbid_added
    pattern: '(x+x+)+y'
    action: block""")
    result = engine.review(std, _files(("a.py", ["x" * 5000, "x" * 5000])), timeout=0.05)
    assert len(result.findings) == 1 and result.findings[0].kind == "rule_error"
    assert "timed out" in result.findings[0].message and result.outcome == "error"


def test_a_file_too_large_to_read_is_reported_not_reviewed():
    files = [diff.FileDiff(path="package-lock.json", skipped="too_large")]
    result = engine.review(standards.default(), files)
    assert result.not_reviewed == ("package-lock.json",)
    secrets = next(r for r in result.rules if r.rule_id == "no-secrets")
    assert (secrets.outcome, secrets.skipped_files, secrets.complete) == ("pass", 1, False)


SECRETS_BLOCK = """  - id: secrets
    title: No secrets
    kind: secret_scan
    action: block"""


@pytest.mark.parametrize("on_incomplete, blocks", [("warn", False), ("block", True)])
def test_an_incomplete_mandatory_scan_is_incomplete_and_on_incomplete_decides(on_incomplete, blocks):
    std = standards.parse(f"name: t\non_incomplete: {on_incomplete}\nrules:\n{SECRETS_BLOCK}")
    result = engine.review(std, [diff.FileDiff(path="big.env", skipped="too_large")])
    assert (result.outcome, result.blocks_merge) == ("incomplete", blocks)
    assert result.findings == ()  # nothing was found; the review is still not a pass


def test_an_advisory_rule_that_could_not_finish_blocks_nothing():
    std = _std("""  - id: secrets
    title: No secrets
    kind: secret_scan
    action: warn""")
    result = engine.review(std, [diff.FileDiff(path="big.env", skipped="too_large")])
    assert result.outcome == "passed" and not result.blocks_merge


def test_outcomes_violated_error_and_passed():
    files = _files(("app/x.py", ['k = "AKIAABCDEFGHIJKLMNOP"']))
    assert engine.review(_std(SECRETS_BLOCK), files).outcome == "violated"
    assert engine.review(_std(SECRETS_BLOCK), _files(("app/x.py", ["ok"]))).outcome == "passed"
    slow = _std("""  - id: slow
    title: Catastrophic
    kind: forbid_added
    pattern: '(x+x+)+y'
    action: block""")
    errored = engine.review(slow, _files(("a.py", ["x" * 5000])), timeout=0.05)
    assert errored.outcome == "error" and errored.rules[0].outcome == "error"  # never a silent pass
    assert errored.findings[0].kind == "rule_error" and not errored.findings[0].blocking
    assert not errored.blocks_merge  # on_incomplete: warn (the default) decides
    strict = standards.parse("name: t\non_incomplete: block\nrules:\n" + """  - id: slow
    title: Catastrophic
    kind: forbid_added
    pattern: '(x+x+)+y'
    action: block""")
    assert engine.review(strict, _files(("a.py", ["x" * 5000])), timeout=0.05).blocks_merge


def test_the_review_wide_pattern_budget_stops_runaway_standards():
    std = _std(FORBID_PRINT)
    result = engine.review(std, _files(("app/x.py", ["y = 1"] * 50)), budget_s=0.0)
    assert result.rules[0].outcome == "error" and "budget" in result.rules[0].reason


def test_a_huge_change_is_reviewed_in_part_and_says_so(monkeypatch):
    monkeypatch.setattr(engine, "MAX_ADDED_LINES", 3)
    result = engine.review(_std(SECRETS_BLOCK), _files(("a.py", ["1", "2"]), ("b.py", ["3", "4"])))
    assert result.skipped == (("b.py", "too_large"),) and result.outcome == "incomplete"


def test_same_standard_same_diff_same_result_and_hash():
    std = _std(FORBID_PRINT, """  - id: secrets
    title: No secrets
    kind: secret_scan""")
    files = _files(("app/b.py", ["print(1)"]), ("app/a.py", ["print(2)", 'k = "AKIAABCDEFGHIJKLMNOP"']))
    first, second = engine.review(std, files), engine.review(std, list(reversed(files)))
    assert first.as_dict() == second.as_dict()
    assert [(f.path, f.line) for f in first.findings] == [("app/a.py", 1), ("app/a.py", 2), ("app/b.py", 1)]


def test_one_finding_per_logical_issue_spanning_consecutive_lines():
    """ReviewBench's contract: one entry per logical issue, not one per line."""
    files = _files(("app/x.py", ["print(1)", "print(2)", "x = 1", "print(3)"]))
    found = [(f.line, f.end_line) for f in engine.review(_std(FORBID_PRINT), files).findings]
    assert found == [(1, 2), (4, 4)]


def test_findings_carry_a_category_and_producer_for_benchmark_scoring():
    std = _std("""  - id: secrets
    title: No secrets
    kind: secret_scan""", """  - id: deps
    title: No left-pad
    kind: forbid_dependency
    packages: [left-pad]
    category: security""")
    result = engine.review(std, _files(("requirements.txt", ["left-pad==1", 'pw = "AKIAABCDEFGHIJKLMNOP"'])))
    assert {(f.rule_id, f.category) for f in result.findings} == {("deps", "security"), ("secrets", "security")}
    assert all(f.producer == f"grc-rules/{engine.ENGINE_VERSION}" for f in result.findings)
    with pytest.raises(standards.StandardError, match="category"):
        _std("""  - id: s
    title: S
    kind: secret_scan
    category: vibes""")
