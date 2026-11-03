"""The migration history must be one straight line: unique revision ids, every parent present, one head.

A duplicated id makes Alembic report a cycle and refuse to run, which fails a deploy at start-up after CI
has already passed (the unit tests build tables directly and never read this graph)."""

from __future__ import annotations

import ast
import collections
from pathlib import Path

VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _graph():
    ids, parents = collections.defaultdict(list), {}
    for path in sorted(VERSIONS.glob("*.py")):
        revision = down = None
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                name, value = node.targets[0].id, node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name, value = node.target.id, node.value
            else:
                continue
            if name == "revision":
                revision = ast.literal_eval(value)
            elif name == "down_revision":
                down = ast.literal_eval(value)
        assert revision, f"{path.name} has no revision id"
        ids[revision].append(path.name)
        parents[revision] = [down] if isinstance(down, str) else list(down or [])
    return ids, parents


def test_every_revision_id_is_used_once():
    ids, _ = _graph()
    assert {k: v for k, v in ids.items() if len(v) > 1} == {}


def test_every_parent_exists_and_there_is_exactly_one_head():
    ids, parents = _graph()
    missing = {r: [p for p in ps if p not in ids] for r, ps in parents.items() if any(p not in ids for p in ps)}
    assert missing == {}
    heads = [r for r in ids if not any(r in ps for ps in parents.values())]
    assert len(heads) == 1, heads
