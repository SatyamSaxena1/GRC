"""Unified diffs into the per-file facts the rule engine reads (ADR-027).

Two sources, one shape: a whole `git diff` (the "try it" box, tests) and GitHub's per-file
`patch` strings from `/pulls/{n}/files` (the App reviewer). Only added lines keep their text,
and only in memory: nothing here is stored.

Input the parser cannot fully read is marked, never dropped: a file is `skipped` with a reason
(too large for the source to include, binary, a symlink, a combined merge diff it does not
parse), and the engine reports the rules that could not look at it as incomplete.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "a": "\a", "b": "\b", "f": "\f", "r": "\r", "v": "\v"}

SKIP_REASONS = ("too_large", "binary", "symlink", "unsupported")


@dataclass
class FileDiff:
    path: str
    previous_path: str | None = None
    status: str = "modified"           # added | modified | deleted | renamed
    added: list[tuple[int, str]] = field(default_factory=list)   # (new line number, text)
    removed: int = 0
    skipped: str | None = None         # one of SKIP_REASONS: present, but its content was not read

    @property
    def binary(self) -> bool:
        return self.skipped == "binary"

    @property
    def too_large(self) -> bool:
        return self.skipped == "too_large"


def _unquote(name: str) -> str:
    """Git quotes paths with unusual characters C-style ("a/caf\\303\\251.py")."""
    if not (len(name) >= 2 and name[0] == name[-1] == '"'):
        return name
    raw, out, i = name[1:-1], bytearray(), 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            octal = raw[i + 1:i + 4]
            if len(octal) == 3 and all(c in "01234567" for c in octal):
                out.append(int(raw[i + 1:i + 4], 8))
                i += 4
                continue
            out.extend(_ESCAPES.get(nxt, nxt).encode())
            i += 2
            continue
        out.extend(ch.encode())
        i += 1
    return out.decode("utf-8", errors="replace")


def _strip(path: str) -> str | None:
    path = path.rstrip("\n").split("\t")[0].strip()
    path = _unquote(path)
    if path == "/dev/null":
        return None
    return path[2:] if path[:2] in ("a/", "b/") else path


def _git_header_paths(rest: str) -> tuple[str, str] | None:
    """`diff --git <a> <b>`, where either side may be quoted and paths may contain spaces."""
    if rest.startswith('"'):
        end = rest.index('"', 1) if '"' in rest[1:] else -1
        while end > 0 and rest[end - 1] == "\\":
            end = rest.index('"', end + 1)
        a, b = rest[:end + 1], rest[end + 2:]
    else:
        # Unquoted: the two paths are equal-length halves when the file was not renamed.
        half = (len(rest) - 1) // 2
        if rest[half] == " " and rest[:half][2:] == rest[half + 1:][2:]:
            a, b = rest[:half], rest[half + 1:]
        else:
            parts = rest.split(" b/", 1)
            if len(parts) != 2:
                return None
            a, b = parts[0], "b/" + parts[1]
    old, new = _strip(a), _strip(b)
    return (old or new or "", new or old or "") if (old or new) else None


def _read_hunks(lines: list[str], start: int, diff: FileDiff) -> int:
    """Read hunks from lines[start:] into `diff`; returns the index after the last hunk line.
    Hunk lengths come from the headers, so a content line that starts with '+++' or 'diff'
    is never mistaken for a new file."""
    i = start
    while i < len(lines):
        match = _HUNK.match(lines[i])
        if not match:
            return i
        old_left = int(match.group(2) or 1)
        new_left = int(match.group(4) or 1)
        new_line = int(match.group(3))
        i += 1
        while i < len(lines) and (old_left > 0 or new_left > 0):
            line = lines[i]
            tag = line[:1]
            if tag == "+":
                diff.added.append((new_line, line[1:]))
                new_line += 1
                new_left -= 1
            elif tag == "-":
                diff.removed += 1
                old_left -= 1
            elif tag == "\\":
                pass  # "\ No newline at end of file"
            else:  # context, including an empty line for an empty context line
                new_line += 1
                new_left -= 1
                old_left -= 1
            i += 1
        while i < len(lines) and lines[i].startswith("\\"):
            i += 1
    return i


def _lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def parse(text: str) -> list[FileDiff]:
    """A unified diff, with or without `diff --git` headers."""
    lines = _lines(text)
    files: list[FileDiff] = []
    current: FileDiff | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --cc ") or line.startswith("diff --combined "):
            current = FileDiff(path=_strip(line.split(" ", 2)[2]) or "", skipped="unsupported")
            files.append(current)
        elif line.startswith("diff --git "):
            paths = _git_header_paths(line[len("diff --git "):])
            current = FileDiff(path=paths[1] if paths else "")
            if paths and paths[0] != paths[1]:
                current.previous_path, current.status = paths[0], "renamed"
            files.append(current)
        elif line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            old, new = _strip(line[4:]), _strip(lines[i + 1][4:])
            if current is None or current.added or current.removed or (current.path not in (old, new)):
                current = FileDiff(path=new or old or "")
                files.append(current)
            current.path = new or old or current.path
            if old is None:
                current.status = "added"
            elif new is None:
                current.status = "deleted"
            elif old != new:
                current.previous_path, current.status = old, "renamed"
            i += 2
            continue
        elif current is not None:
            if line.startswith("new file mode"):
                current.status = "added"
                if line.rstrip().endswith("120000"):
                    current.skipped = "symlink"
            elif line.startswith("deleted file mode"):
                current.status = "deleted"
            elif line.startswith("new mode") and line.rstrip().endswith("120000"):
                current.skipped = "symlink"
            elif line.startswith("rename from "):
                current.previous_path, current.status = _unquote(line[len("rename from "):]), "renamed"
            elif line.startswith("rename to "):
                current.path = _unquote(line[len("rename to "):])
            elif line.startswith("Binary files ") or line == "GIT binary patch":
                current.skipped = "binary"
            elif line.startswith("@@@"):
                current.skipped = "unsupported"
            elif _HUNK.match(line):
                i = _read_hunks(lines, i, current)
                if current.skipped == "symlink":
                    current.added = []  # a link target is not code
                continue
        i += 1
    return [f for f in files if f.path]


_GITHUB_STATUS = {"added": "added", "removed": "deleted", "renamed": "renamed", "copied": "added"}


def from_github_files(files: list[dict]) -> list[FileDiff]:
    """GitHub's `/pulls/{n}/files` entries. GitHub leaves `patch` out of binary files and of
    very large diffs. A file with changed lines but no patch is marked too_large, never read as
    unchanged; one with no changed lines (a binary file, a pure rename) has nothing to read."""
    out = []
    for f in files:
        diff = FileDiff(path=f.get("filename") or "", previous_path=f.get("previous_filename"),
                        status=_GITHUB_STATUS.get(f.get("status") or "", "modified"))
        patch = f.get("patch")
        if patch:
            _read_hunks(_lines(patch), 0, diff)
        elif diff.status != "deleted" and (f.get("additions") or f.get("changes")):
            diff.skipped = "too_large"
        out.append(diff)
    return [f for f in out if f.path]
