"""The model reviewer (Phase 2 prototype, offline evaluation only): a self-hosted model reviews a
pull request's diff, reading related code through read-only tools, and returns findings in the
same shape as the rule engine (ADR-027).

It advises; it never decides (ADR-018). What ReviewBench's methodology says about where
reviewers fail is built in:
- recall comes from context, so the model can read and search the repository at the PR's head;
- precision comes from avoiding the known false-positive modes, which the prompt names;
- one finding per logical issue, a message that says what is wrong and why.

Safety: the tools read only inside the checkout (no path escapes, no symlinks out), never the
network, and their output is capped. Repository text can ask the model for anything; the
model can only read files and return findings, and nothing it returns can block a merge.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from app.review.diff import FileDiff

logger = logging.getLogger("app.review.agent")

PROMPT_VERSION = "review-agent:v1"
MAX_ROUNDS = 12                 # tool rounds per chunk
MAX_FINDINGS = 25               # per pull request: a reviewer that says everything says nothing
CHUNK_CHARS = 24_000            # diff characters per model conversation
TOOL_OUTPUT_CHARS = 12_000
SEARCH_MAX_HITS = 40
SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", "__pycache__", ".venv"}

SYSTEM = """You are a senior engineer reviewing a pull request. Report only issues a competent \
senior reviewer would expect the author to fix before merging: bugs, incorrect logic, security \
problems, data loss, concurrency and error-handling mistakes, broken contracts, and missing \
handling of real edge cases.

Before you report an issue, verify it. Use the tools to read the surrounding code, the callers \
and the definitions you depend on. An issue you have not verified against the code is not an \
issue.

Do NOT report:
- claims that are factually wrong, or that you could not verify in the code;
- issues outside this change that it neither introduces nor makes worse;
- duplicates: one finding per underlying issue, spanning its full line range;
- style, naming or formatting nits, or anything below a senior reviewer's bar;
- advice that would not make the change better.

Line numbers refer to the file at the pull request's head (the numbers after '+' in the diff \
hunks). Each message says what is wrong and why it matters, concretely, in one or two \
sentences. Reporting nothing is a correct answer when nothing is wrong.

When you are done, answer with JSON only, no prose:
{"findings": [{"file": "path", "start_line": 1, "end_line": 1, "severity": "high|medium|low",
"category": "correctness|security|performance|reliability|api-design|maintainability|test-quality|documentation|dependency-build",
"message": "..."}]}"""

TOOLS = [
    {"type": "function", "function": {
        "name": "read_file", "description": "Read lines of a file in the repository at the pull request's head.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "search", "description": "Search the repository for a regular expression; returns matching lines.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"}, "path_glob": {"type": "string"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "list_dir", "description": "List a directory in the repository.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}},
]


@dataclass
class ModelFinding:
    file: str
    start_line: int
    end_line: int
    message: str
    severity: str = "medium"
    category: str = "correctness"


@dataclass
class AgentStats:
    calls: int = 0
    tool_calls: int = 0
    chunks: int = 0
    dropped: list[str] = field(default_factory=list)   # why findings were discarded


class RepoTools:
    """Read-only tools over a checkout. Every path is resolved and must stay inside the root."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _path(self, path: str) -> Path:
        candidate = (self.root / str(path).lstrip("/")).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("path is outside the repository")
        return candidate

    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> dict:
        target = self._path(path)
        if not target.is_file():
            return {"error": f"no such file: {path}"}
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(start_line or 1))
        end = min(len(lines), int(end_line) if end_line else start + 199)
        body = "\n".join(f"{n}: {lines[n - 1]}" for n in range(start, end + 1))
        return {"path": path, "total_lines": len(lines), "content": body[:TOOL_OUTPUT_CHARS]}

    def search(self, pattern: str, path_glob: str = "**/*") -> dict:
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            return {"error": f"bad pattern: {exc}"}
        hits = []
        for target in sorted(self.root.glob(path_glob or "**/*")):
            if len(hits) >= SEARCH_MAX_HITS:
                break
            if not target.is_file() or any(p in SKIP_DIRS for p in target.relative_to(self.root).parts):
                continue
            try:
                target.resolve().relative_to(self.root)
                if target.stat().st_size > 1_000_000:
                    continue
                for n, line in enumerate(target.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if compiled.search(line[:1000]):
                        hits.append(f"{target.relative_to(self.root)}:{n}: {line.strip()[:200]}")
                        if len(hits) >= SEARCH_MAX_HITS:
                            break
            except (OSError, ValueError):
                continue
        return {"matches": hits, "truncated": len(hits) >= SEARCH_MAX_HITS}

    def list_dir(self, path: str = ".") -> dict:
        target = self._path(path or ".")
        if not target.is_dir():
            return {"error": f"no such directory: {path}"}
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir() if p.name not in SKIP_DIRS)
        return {"path": path, "entries": entries[:300]}

    def execute(self, name: str, args: dict) -> dict:
        if name == "read_file":
            return self.read_file(args.get("path", ""), args.get("start_line", 1), args.get("end_line"))
        if name == "search":
            return self.search(args.get("pattern", ""), args.get("path_glob") or "**/*")
        if name == "list_dir":
            return self.list_dir(args.get("path") or ".")
        return {"error": f"unknown tool {name}"}


class ChatModel:
    """An OpenAI-compatible chat endpoint (LM Studio, vLLM, llama.cpp): RB_MODEL_BASE_URL style,
    i.e. a base URL that already ends in /v1."""

    def __init__(self, base_url: str, model: str, api_key: str = "", timeout_s: float = 600,
                 reasoning_effort: str = ""):
        self.base_url, self.model, self.api_key = base_url.rstrip("/"), model, api_key
        self.timeout_s, self.reasoning_effort = timeout_s, reasoning_effort

    def chat(self, messages: list[dict], tools: list[dict] | None) -> dict:
        payload = {"model": self.model, "messages": messages, "temperature": 0}
        if tools:
            payload["tools"] = tools
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        resp = requests.post(f"{self.base_url}/chat/completions", json=payload, headers=headers,
                             timeout=self.timeout_s)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]


def chunks(files: list[FileDiff], diff_text: str) -> list[str]:
    """Split a unified diff by file into conversations of at most CHUNK_CHARS each."""
    parts = re.split(r"(?m)^(?=diff --git )", diff_text)
    parts = [p for p in parts if p.strip()]
    out, current = [], ""
    for part in parts:
        if len(part) > CHUNK_CHARS:
            part = part[:CHUNK_CHARS] + "\n[... this file's diff is truncated ...]\n"
        if current and len(current) + len(part) > CHUNK_CHARS:
            out.append(current)
            current = ""
        current += part
    if current:
        out.append(current)
    return out


_JSON = re.compile(r"\{.*\}", re.S)


def parse_findings(text: str) -> list[dict]:
    """The model's final answer, tolerant of code fences, thinking tags and leading prose."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    match = _JSON.search(text)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    items = data.get("findings") if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def _valid(item: dict, files: dict[str, FileDiff], tools: RepoTools, stats: AgentStats) -> ModelFinding | None:
    """Keep a finding only if it points at a real place: a file the PR changed (or one that
    exists at head), and lines that exist. Nonsense locations are dropped, and counted."""
    try:
        path = str(item["file"]).removeprefix("./").lstrip("/")
        if path[:2] in ("a/", "b/") and path[2:] in files:
            path = path[2:]  # copied from a diff header
        start, end = int(item["start_line"]), int(item.get("end_line") or item["start_line"])
        message = str(item["message"]).strip()
    except (KeyError, TypeError, ValueError):
        stats.dropped.append("malformed")
        return None
    if not message or start < 1:
        stats.dropped.append("empty message or bad line")
        return None
    try:
        target = tools._path(path)
    except ValueError:
        stats.dropped.append("path outside repository")
        return None
    if path not in files and not target.is_file():
        stats.dropped.append(f"unknown file {path}")
        return None
    if target.is_file():
        total = len(target.read_text(encoding="utf-8", errors="replace").splitlines())
        if start > total:
            stats.dropped.append(f"line {start} past end of {path}")
            return None
        end = min(max(end, start), total)
    severity = str(item.get("severity", "medium")).lower()
    return ModelFinding(file=path, start_line=start, end_line=end, message=message[:1000],
                        severity=severity if severity in ("high", "medium", "low") else "medium",
                        category=str(item.get("category", "correctness")))


def review(model: ChatModel, tools: RepoTools, diff_text: str, files: list[FileDiff], title: str = "",
           body: str = "", deadline: float | None = None) -> tuple[list[ModelFinding], AgentStats]:
    """Review every chunk of the diff in its own tool-using conversation."""
    stats = AgentStats()
    by_path = {f.path: f for f in files}
    found: list[ModelFinding] = []
    header = f"Pull request: {title}\n\n{(body or '')[:4000]}\n\n" if title or body else ""
    for chunk in chunks(files, diff_text):
        if deadline and time.monotonic() > deadline:
            stats.dropped.append("deadline reached before every chunk was reviewed")
            break
        stats.chunks += 1
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"{header}Review this diff:\n\n{chunk}"}]
        answer = ""
        for _ in range(MAX_ROUNDS):
            stats.calls += 1
            message = model.chat(messages, TOOLS)
            answer = message.get("content") or answer
            calls = message.get("tool_calls") or []
            if not calls:
                break
            messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": calls})
            for call in calls:
                stats.tool_calls += 1
                fn = call.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                    result = tools.execute(fn.get("name", ""), args if isinstance(args, dict) else {})
                except Exception as exc:  # noqa: BLE001 - a bad tool call is the model's problem, not a crash
                    result = {"error": type(exc).__name__}
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                                 "content": json.dumps(result)[:TOOL_OUTPUT_CHARS]})
        else:
            # Out of rounds: ask once more for the answer, without tools.
            messages.append({"role": "user", "content": "Stop using tools. Answer now with the JSON only."})
            stats.calls += 1
            answer = model.chat(messages, None).get("content") or answer
        for item in parse_findings(answer):
            if isinstance(item, dict) and (finding := _valid(item, by_path, tools, stats)):
                found.append(finding)
    return _dedupe(found)[:MAX_FINDINGS], stats


def _dedupe(findings: list[ModelFinding]) -> list[ModelFinding]:
    """Drop a finding whose lines overlap an earlier one in the same file and category."""
    kept: list[ModelFinding] = []
    for f in findings:
        if any(k.file == f.file and k.category == f.category and k.start_line <= f.end_line
               and f.start_line <= k.end_line for k in kept):
            continue
        kept.append(f)
    return kept


def from_env() -> ChatModel:
    return ChatModel(
        base_url=os.environ.get("RB_MODEL_BASE_URL") or os.environ.get("REVIEW_MODEL_BASE_URL")
        or "http://host.docker.internal:1234/v1",
        model=os.environ.get("RB_CONFIG_MODEL") or os.environ.get("REVIEW_MODEL") or "qwen/qwen3.8-27b",
        api_key=os.environ.get("REVIEW_MODEL_API_KEY") or os.environ.get("OPENAI_API_KEY", ""),
        reasoning_effort=os.environ.get("RB_CONFIG_EFFORT", ""),
    )
