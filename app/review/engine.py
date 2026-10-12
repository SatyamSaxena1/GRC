"""The deterministic review engine (ADR-027): a Review Standard over a pull request's diff.

Pure and repeatable: the same standard and the same diff give the same findings in the same
order. A finding names the rule, the file and the lines; never the code. Secret findings carry no
fingerprint at all; others carry a keyed HMAC of the matched lines when REVIEW_FINGERPRINT_KEY is
set, so a finding can be matched to code without the code, or the hash of a secret, being kept.

Every rule ends in an explicit outcome, and so does the review:

  rule:    pass | violation | not_evaluated | error     (+ how many in-scope files it skipped)
  review:  passed | violated | incomplete | error

`not_evaluated` and skipped files are never read as a pass. Whether an incomplete or errored
review blocks a merge is the standard's `on_incomplete` policy, decided by people, not here.
"""

from __future__ import annotations

import fnmatch
import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import asdict, dataclass

import regex

from app.review.diff import FileDiff
from app.review.standards import TEST_GLOBS, Rule, Standard

ENGINE_VERSION = "1"
PRODUCER = f"grc-rules/{ENGINE_VERSION}"
REGEX_TIMEOUT_S = 0.25      # per added line: an organisation's regex must not stall the reviewer
REGEX_BUDGET_S = 10.0       # for all of a review's regex work together
MAX_LINE_CHARS = 2000       # an organisation's regex sees this much of a line; longer lines make it incomplete
MAX_ADDED_LINES = 200_000   # beyond this a change is reviewed only in part, and says so

# Built-in secret detectors. Platform-owned patterns, so the standard library `re` is enough.
_DETECTORS = {
    "aws_access_key": (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "what looks like an AWS access key"),
    "github_token": (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{22,255})\b"),
                     "what looks like a GitHub token"),
    "private_key": (re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"), "a private key"),
    "slack_token": (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "what looks like a Slack token"),
    "password_literal": (re.compile(r"(?i)\b(?:pass(?:word|wd)?|secret|api[_-]?key|token)\b[\"']?\s*[:=]\s*"
                                    r"[\"'][^\"'\s]{8,}[\"']"), "a credential written as a literal"),
}
_REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_QUOTED_NAME = re.compile(r"[\"']\s*(@?[A-Za-z0-9][A-Za-z0-9._/-]*)")
_TOML_KEY = re.compile(r"^\s*[\"']?([A-Za-z0-9][A-Za-z0-9._-]*)[\"']?\s*=")
# Rules that read added lines cannot judge a file whose content was not read.
_READS_CONTENT = {"forbid_added", "secret_scan", "forbid_dependency", "max_change"}


@dataclass(frozen=True)
class Finding:
    """One logical issue. The shape follows ReviewBench's agent contract (file, start and end
    line, message, producer) plus the rule, severity, category and policy action."""
    rule_id: str
    kind: str
    category: str
    severity: str
    action: str                          # block | warn | info: policy, independent of severity
    path: str
    line: int | None
    end_line: int | None
    message: str
    fingerprint: str | None = None       # keyed HMAC of the matched lines; never for secrets
    producer: str = PRODUCER

    @property
    def blocking(self) -> bool:
        return self.action == "block"

    def as_dict(self) -> dict:
        return {**asdict(self), "blocking": self.blocking}


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    action: str
    outcome: str                          # pass | violation | not_evaluated | error
    reason: str | None = None
    evaluated_files: int = 0
    skipped_files: int = 0
    truncated_lines: int = 0              # lines an organisation's pattern saw only the start of

    @property
    def complete(self) -> bool:
        return self.outcome in ("pass", "violation") and self.skipped_files == 0 and self.truncated_lines == 0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Result:
    findings: tuple[Finding, ...]
    rules: tuple[RuleResult, ...]
    on_incomplete: str = "warn"
    skipped: tuple[tuple[str, str], ...] = ()        # (path, reason) for every file not read

    @property
    def outcome(self) -> str:
        """violated beats error beats incomplete beats passed. Only rules that can block count
        toward error and incomplete: an advisory rule that could not finish blocks nothing."""
        if any(f.blocking for f in self.findings):
            return "violated"
        enforcing = [r for r in self.rules if r.action == "block"]
        if any(r.outcome == "error" for r in enforcing):
            return "error"
        if any(not r.complete for r in enforcing):
            return "incomplete"
        return "passed"

    @property
    def blocks_merge(self) -> bool:
        return self.outcome == "violated" or (self.outcome in ("incomplete", "error")
                                              and self.on_incomplete == "block")

    @property
    def blocking(self) -> bool:
        """A blocking rule fired. Not the same as blocks_merge, which also applies on_incomplete."""
        return self.outcome == "violated"

    @property
    def not_evaluated(self) -> tuple[str, ...]:
        return tuple(r.rule_id for r in self.rules if r.outcome == "not_evaluated")

    @property
    def not_reviewed(self) -> tuple[str, ...]:
        return tuple(path for path, _ in self.skipped)

    def as_dict(self) -> dict:
        return {"engine_version": ENGINE_VERSION, "outcome": self.outcome, "blocks_merge": self.blocks_merge,
                "blocking": self.blocking, "on_incomplete": self.on_incomplete,
                "findings": [f.as_dict() for f in self.findings], "findings_hash": findings_hash(self.findings),
                "rules": [r.as_dict() for r in self.rules],
                "skipped": [{"path": p, "reason": why} for p, why in self.skipped],
                "not_evaluated": list(self.not_evaluated), "not_reviewed": list(self.not_reviewed)}


def findings_hash(findings) -> str:
    body = json.dumps([f.as_dict() for f in findings], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def fingerprint(text: str) -> str | None:
    """A keyed HMAC, so a fingerprint of a short line cannot be reversed by guessing; None
    without a key rather than a plain hash."""
    key = os.environ.get("REVIEW_FINGERPRINT_KEY", "")
    if not key:
        return None
    return hmac.new(key.encode(), text.encode(), hashlib.sha256).hexdigest()


def _finding(rule: Rule, path: str, line: int | None, message: str, text: str | None = None,
             end_line: int | None = None) -> Finding:
    keep = text is not None and rule.kind != "secret_scan"  # never a fingerprint of a secret
    return Finding(rule_id=rule.id, kind=rule.kind, category=rule.resolved_category, severity=rule.severity,
                   action=rule.action, path=path, line=line, end_line=end_line if end_line is not None else line,
                   message=rule.message or message, fingerprint=fingerprint(text) if keep else None)


def _merge_runs(findings: list[Finding], texts: dict[tuple[str, int], str]) -> list[Finding]:
    """One finding per logical issue: hits of the same rule on consecutive lines of one file
    become one finding spanning them (a multi-line key, a block of debug prints)."""
    merged: list[Finding] = []
    for f in sorted(findings, key=lambda f: (f.path, f.line or 0)):
        last = merged[-1] if merged else None
        if (last and f.line is not None and last.end_line is not None and last.path == f.path
                and last.rule_id == f.rule_id and last.message == f.message and f.line == last.end_line + 1):
            span = "\n".join(texts[(f.path, n)] for n in range(last.line, f.line + 1))
            keep = last.kind != "secret_scan"
            merged[-1] = Finding(**{**asdict(last), "end_line": f.line,
                                    "fingerprint": fingerprint(span) if keep else None})
        else:
            merged.append(f)
    return merged


class _Budget:
    def __init__(self, seconds: float):
        self.seconds, self.spent = seconds, 0.0

    def left(self) -> float:
        return self.seconds - self.spent


def _cap(files: list[FileDiff]) -> list[FileDiff]:
    """Past MAX_ADDED_LINES the rest of the change is marked skipped: reviewed in part, and says so."""
    total, out = 0, []
    for f in files:
        if f.skipped is None and total + len(f.added) > MAX_ADDED_LINES:
            f = FileDiff(path=f.path, previous_path=f.previous_path, status=f.status, removed=f.removed,
                         skipped="too_large")
        total += len(f.added)
        out.append(f)
    return out


class _RuleError(Exception):
    def __init__(self, message: str, path: str | None = None, line: int | None = None):
        super().__init__(message)
        self.path, self.line = path, line


def review(standard: Standard, files: list[FileDiff], timeout: float = REGEX_TIMEOUT_S,
           budget_s: float = REGEX_BUDGET_S) -> Result:
    files = _cap(files)
    budget = _Budget(budget_s)
    findings: list[Finding] = []
    results: list[RuleResult] = []
    for rule in standard.rules:
        scoped = [f for f in files if rule.applies_to(f.path)]
        readable = [f for f in scoped if f.skipped is None]
        skipped = len(scoped) - len(readable) if rule.kind in _READS_CONTENT else 0
        base = {"rule_id": rule.id, "action": rule.action, "evaluated_files": len(scoped) - skipped,
                "skipped_files": skipped}
        if rule.kind == "judged":
            results.append(RuleResult(rule_id=rule.id, action=rule.action, outcome="not_evaluated",
                                      reason="checked by the model reviewer (Phase 2)"))
            continue
        truncated = (sum(1 for _, _, text in _lines(readable) if len(text) > MAX_LINE_CHARS)
                     if rule.kind == "forbid_added" else 0)
        try:
            found = _run(rule, readable, scoped, files, timeout, budget)
        except _RuleError as exc:
            results.append(RuleResult(**base, outcome="error", reason=str(exc)))
            # Shown where it happened, as information: the error is not a violation, and whether
            # it stops a merge is the standard's on_incomplete policy (Result.blocks_merge).
            noted = _finding(rule, exc.path or (scoped[0].path if scoped else ""), exc.line,
                             f"rule '{rule.id}' could not be checked: {exc}")
            findings.append(Finding(**{**asdict(noted), "action": "info", "kind": "rule_error",
                                       "message": f"rule '{rule.id}' could not be checked: {exc}"}))
            continue
        findings += found
        reasons = ([f"{skipped} file(s) in scope were not read"] if skipped else []) + (
            [f"{truncated} line(s) longer than {MAX_LINE_CHARS} characters were checked only in part"]
            if truncated else [])
        results.append(RuleResult(**base, outcome="violation" if found else "pass",
                                  reason="; ".join(reasons) or None, truncated_lines=truncated))
    findings.sort(key=lambda f: (f.path, f.line or 0, f.rule_id))
    skipped_files = tuple(sorted((f.path, f.skipped) for f in files if f.skipped))
    return Result(tuple(findings), tuple(results), standard.on_incomplete, skipped_files)


def _run(rule: Rule, readable: list[FileDiff], scoped: list[FileDiff], every: list[FileDiff],
         timeout: float, budget: _Budget) -> list[Finding]:
    if rule.kind == "forbid_added":
        return _forbid_added(rule, readable, timeout, budget)
    if rule.kind == "secret_scan":
        return _secret_scan(rule, readable)
    if rule.kind == "forbid_dependency":
        return _forbid_dependency(rule, readable)
    if rule.kind == "require_companion":
        return _require_companion(rule, scoped, every)   # needs paths only, never content
    if rule.kind == "max_change":
        added = sum(len(f.added) for f in readable)
        if added > (rule.max_added_lines or 0):
            return [_finding(rule, readable[0].path, None,
                             f"{added} lines added across {len(readable)} file(s), over the "
                             f"{rule.max_added_lines}-line limit; consider splitting the change")]
        return []
    raise _RuleError(f"unknown rule kind {rule.kind!r}")


def _lines(files: list[FileDiff]):
    for f in files:
        if f.status == "deleted":
            continue
        for number, text in f.added:
            yield f.path, number, text


def _forbid_added(rule: Rule, files: list[FileDiff], timeout: float, budget: _Budget) -> list[Finding]:
    pattern = regex.compile(rule.pattern or "")
    out, texts = [], {}
    for path, number, text in _lines(files):
        texts[(path, number)] = text
        if budget.left() <= 0:
            raise _RuleError("the review's pattern budget ran out before this rule finished", path, number)
        started = time.monotonic()
        try:
            hit = pattern.search(text[:MAX_LINE_CHARS], timeout=min(timeout, max(budget.left(), 0.001)))
        except TimeoutError:
            # Never a silent pass: the rule could not be checked, and says so.
            raise _RuleError("its pattern timed out; simplify the pattern", path, number) from None
        finally:
            budget.spent += time.monotonic() - started
        if hit:
            out.append(_finding(rule, path, number, f"added line matches the '{rule.id}' pattern", text))
    return _merge_runs(out, texts)


def _secret_scan(rule: Rule, files: list[FileDiff]) -> list[Finding]:
    detectors = rule.detectors or tuple(_DETECTORS)
    out, texts = [], {}
    for path, number, text in _lines(files):
        texts[(path, number)] = text
        for name in detectors:
            pattern, what = _DETECTORS[name]
            # The whole line: these platform patterns run in linear time, and a credential at
            # character 5,000 of a minified file is still a credential.
            if pattern.search(text):
                # The detector and the place, never the value or a hash of it: nothing a check
                # annotation, an audit event or a log line repeats can leak the credential.
                out.append(_finding(rule, path, number, f"added line contains {what} ({name})", text))
                break  # one finding per line
    return _merge_runs(out, texts)


def _norm(name: str) -> str:
    return name.lower().replace("_", "-")


def _dependency_names(path: str, text: str) -> set[str]:
    name = path.rsplit("/", 1)[-1]
    if name.startswith("requirements") and name.endswith(".txt"):
        match = _REQUIREMENT.match(text)
        return {match.group(1)} if match and not text.lstrip().startswith(("#", "-")) else set()
    if name == "package.json":
        match = re.match(r'^\s*"(@?[A-Za-z0-9][A-Za-z0-9._/-]*)"\s*:\s*"', text)
        return {match.group(1)} if match else set()
    if name == "pyproject.toml":
        # PEP 621 lists ("left-pad>=1") and Poetry tables (left-pad = "^1.3", or = { version … })
        names = {m.group(1) for m in _QUOTED_NAME.finditer(text)}
        if key := _TOML_KEY.match(text):
            names.add(key.group(1))
        return names
    return set()


def _forbid_dependency(rule: Rule, files: list[FileDiff]) -> list[Finding]:
    banned = {_norm(p) for p in rule.packages}
    out = []
    for path, number, text in _lines(files):
        for name in sorted(_dependency_names(path, text)):
            if _norm(name) in banned:
                out.append(_finding(rule, path, number, f"adds the banned dependency '{name}'", text))
    return out


def _require_companion(rule: Rule, scoped: list[FileDiff], every: list[FileDiff]) -> list[Finding]:
    changed = [f for f in scoped if f.status != "deleted"]
    if not changed:
        return []
    companions = rule.companions or TEST_GLOBS
    # Deleting a test is not supplying one.
    if any(fnmatch.fnmatchcase(f.path, g) for f in every if f.status != "deleted" for g in companions):
        return []
    shown = ", ".join(f.path for f in changed[:3]) + (f" (+{len(changed) - 3} more)" if len(changed) > 3 else "")
    return [_finding(rule, changed[0].path, None,
                     f"changes {shown} without a matching change to {', '.join(companions[:3])}")]
