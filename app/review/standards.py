"""Review Standards (ADR-027): an organisation's code-review rules, as versioned, hashed YAML.

A standard is data, like a content pack: validated strictly (unknown keys are errors), stored
immutably per version, and identified by the hash of its canonical body, so a review result can
always name the exact rules it was judged by.

Rules that only a model can check (`judged`) are stored now and evaluated in Phase 2. They can
never block a merge, and neither can `max_change`: the rule engine decides, a model only advises
(ADR-018).
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any, Literal

import regex
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.collectors.github_change_control import GATE_PATTERNS
from app.provenance import _body_hash

Severity = Literal["low", "medium", "high", "critical"]
# ReviewBench's category taxonomy (docs/METHODOLOGY.md §5.2), so findings can be stratified the
# same way and scored against its corpus without translation.
Category = Literal["correctness", "security", "performance", "reliability", "api-design", "maintainability",
                   "test-quality", "documentation", "style", "dependency-build"]
DEFAULT_CATEGORY = {"secret_scan": "security", "forbid_dependency": "dependency-build",
                    "require_companion": "test-quality", "max_change": "maintainability",
                    "forbid_added": "maintainability", "judged": "maintainability"}
Kind = Literal["forbid_added", "require_companion", "forbid_dependency", "secret_scan", "max_change", "judged"]
Action = Literal["block", "warn", "info"]
NEVER_BLOCKING = {"judged", "max_change"}
MAX_RULES = 200

MAX_PATTERN_LENGTH = 500
# The test globs the change-control gate already knows (app/collectors/github_change_control.py).
TEST_GLOBS = tuple(p for p in GATE_PATTERNS if "test" in p)
MANIFEST_GLOBS = ("requirements*.txt", "*/requirements*.txt", "pyproject.toml", "*/pyproject.toml",
                  "package.json", "*/package.json")
SECRET_DETECTORS = ("aws_access_key", "github_token", "private_key", "slack_token", "password_literal")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Rule(_Model):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    title: str = Field(min_length=1, max_length=200)
    kind: Kind
    # How bad a violation is, and what policy does about it, are separate: a critical finding need
    # not block, and an incomplete mandatory scan can block with nothing found.
    severity: Severity = "medium"
    action: Action = "warn"
    category: Category | None = None           # defaults by kind (DEFAULT_CATEGORY)
    rationale: str = ""
    message: str = ""
    # Framework clauses the rule supports, as "<FRAMEWORK> <clause>" (checked against the packs).
    clauses: tuple[str, ...] = ()
    # Which changed files the rule looks at: fnmatch globs on the repository path ("*" crosses "/").
    paths: tuple[str, ...] = ("*",)
    exclude: tuple[str, ...] = ()
    pattern: str | None = None                 # forbid_added: a regex over each added line
    companions: tuple[str, ...] = ()           # require_companion: one of these must change too
    packages: tuple[str, ...] = ()             # forbid_dependency
    detectors: tuple[str, ...] = ()            # secret_scan: a subset; empty means all
    max_added_lines: int | None = Field(default=None, gt=0)   # max_change
    text: str = ""                             # judged: the rule in plain language, for the model

    @field_validator("clauses")
    @classmethod
    def _clause_shape(cls, clauses: tuple[str, ...]) -> tuple[str, ...]:
        for clause in clauses:
            if " " not in clause.strip():
                raise ValueError(f"clause {clause!r} must read '<FRAMEWORK> <clause>', e.g. 'SOC-2 CC8.1'")
        return clauses

    @model_validator(mode="after")
    def _kind_fields(self) -> "Rule":
        need = {"forbid_added": ("pattern", self.pattern), "forbid_dependency": ("packages", self.packages),
                "max_change": ("max_added_lines", self.max_added_lines), "judged": ("text", self.text.strip())}
        if self.kind in need and not need[self.kind][1]:
            raise ValueError(f"a {self.kind} rule needs `{need[self.kind][0]}`")
        if self.kind in NEVER_BLOCKING and self.action == "block":
            raise ValueError(f"a {self.kind} rule can never block a merge (ADR-018: the model only advises)")
        if self.pattern is not None:
            if len(self.pattern) > MAX_PATTERN_LENGTH:
                raise ValueError(f"pattern is longer than {MAX_PATTERN_LENGTH} characters")
            try:
                regex.compile(self.pattern)
            except regex.error as exc:
                raise ValueError(f"pattern does not compile: {exc}") from exc
        unknown = set(self.detectors) - set(SECRET_DETECTORS)
        if unknown:
            raise ValueError(f"unknown detector(s) {sorted(unknown)}; known: {list(SECRET_DETECTORS)}")
        return self

    @property
    def blocking(self) -> bool:
        return self.action == "block"

    @property
    def resolved_category(self) -> str:
        return self.category or DEFAULT_CATEGORY[self.kind]

    def applies_to(self, path: str) -> bool:
        return (any(fnmatch.fnmatchcase(path, g) for g in self.scope())
                and not any(fnmatch.fnmatchcase(path, g) for g in self.exclude))

    def scope(self) -> tuple[str, ...]:
        if self.kind == "forbid_dependency" and self.paths == ("*",):
            return MANIFEST_GLOBS
        return self.paths


class Standard(_Model):
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    owner: str = ""                             # who answers for this standard (a team or a person)
    # What a review that could not be completed (a file too large to read, a rule that errored)
    # does to a merge. "warn" keeps merging possible when GRC cannot see everything; "block" makes
    # a mandatory scan that did not finish stop the merge.
    on_incomplete: Literal["block", "warn"] = "warn"
    rules: tuple[Rule, ...] = Field(min_length=1, max_length=MAX_RULES)

    @model_validator(mode="after")
    def _unique_ids(self) -> "Standard":
        seen = set()
        for rule in self.rules:
            if rule.id in seen:
                raise ValueError(f"rule id {rule.id!r} is used twice")
            seen.add(rule.id)
        return self


class StandardError(ValueError):
    """Why a standard was rejected: [{"line": n | None, "message": str}], one per problem."""

    def __init__(self, problems: list[dict]):
        self.problems = problems
        super().__init__("; ".join((f"line {p['line']}: " if p["line"] else "") + p["message"] for p in problems))


def parse(text: str, content=None) -> Standard:
    """Validate a standard's YAML. With `content`, every clause must exist in a loaded pack."""
    try:
        data = yaml.safe_load(text)
        root = yaml.compose(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        raise StandardError([{"line": mark.line + 1 if mark else None, "message": f"not valid YAML: {exc}"}]) from exc
    if not isinstance(data, dict):
        raise StandardError([{"line": None, "message": "a standard is a mapping with `name` and `rules`"}])
    try:
        standard = Standard(**data)
    except ValidationError as exc:
        problems = []
        for err in exc.errors():
            loc = tuple(p for p in err["loc"] if p != "__root__")
            where = ".".join(str(p) for p in loc) or "standard"
            message = err["msg"].removeprefix("Value error, ")
            problems.append({"line": _line_of(root, loc), "message": f"{where}: {message}"})
        raise StandardError(problems) from exc
    if content is not None:
        problems = [{"line": _line_of(root, ("rules", i, "clauses")), "message": f"rules.{i}.clauses: unknown clause {c!r}"}
                    for i, rule in enumerate(standard.rules) for c in rule.clauses
                    if content.requirement(*c.split(" ", 1)) is None]
        if problems:
            raise StandardError(problems)
    return standard


def _line_of(node, loc: tuple) -> int | None:
    """1-based line of the YAML node at `loc`, or of its nearest existing parent."""
    line = node.start_mark.line + 1 if node is not None else None
    for part in loc:
        if isinstance(node, yaml.MappingNode):
            node = next((v for k, v in node.value if k.value == part), None)
        elif isinstance(node, yaml.SequenceNode) and isinstance(part, int) and part < len(node.value):
            node = node.value[part]
        else:
            node = None
        if node is None:
            break
        line = node.start_mark.line + 1
    return line


def body(standard: Standard) -> dict[str, Any]:
    return standard.model_dump(mode="json")


def body_hash(standard: Standard) -> str:
    """The same canonical hashing as content-pack rules (app/provenance.py)."""
    return _body_hash(body(standard))


DEFAULT_YAML = """\
name: GRC default
description: >
  What every repository gets until its organisation publishes a standard. Advisory only:
  nothing here blocks a merge until an administrator decides it should.
rules:
  - id: no-secrets
    title: No credentials in code
    kind: secret_scan
    severity: critical
    action: warn
    clauses: ["SOC-2 CC8.1"]
    rationale: A credential in a repository is exposed to everyone who can read it, forever.
  - id: code-needs-tests
    title: Code changes come with test changes
    kind: require_companion
    severity: low
    paths: ["*.py", "*.ts", "*.tsx", "*.js", "*.go", "*.java", "*.rb", "*.cs"]
    exclude: ["docs/*", "*.md"]
    companions: [{companions}]
""".replace("{companions}", ", ".join(f'"{g}"' for g in TEST_GLOBS))


def default() -> Standard:
    return parse(DEFAULT_YAML)


PACKS_DIR = Path(__file__).parent / "packs"


def packs() -> list[dict]:
    """Built-in policy packs: starting points an organisation copies, edits and publishes as its
    own standard. Each is validated like any standard, so a broken pack fails the test suite."""
    out = []
    for path in sorted(PACKS_DIR.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        std = parse(text)
        out.append({"id": path.stem, "name": std.name, "description": std.description.strip(),
                    "rules": len(std.rules), "yaml": text, "body_hash": body_hash(std)})
    return out
