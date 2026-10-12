"""The model reviewer prototype and its ReviewBench adapter: read-only tools that cannot leave
the checkout, findings validated against real locations, and a findings file that passes the
benchmark's own format checks. The model is faked; real runs are offline (bench/reviewbench)."""

from __future__ import annotations

import json

import pytest

from app.review import agent, bench, diff

DIFF = """\
diff --git a/app/pool.py b/app/pool.py
--- a/app/pool.py
+++ b/app/pool.py
@@ -1,3 +1,4 @@
 def take(pool):
-    return pool.pop()
+    item = pool.pop()
+    return item
 # end
"""


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "pool.py").write_text("def take(pool):\n    item = pool.pop()\n    return item\n# end\n")
    (tmp_path / "app" / "use.py").write_text("from app.pool import take\nx = take([])\n")
    (tmp_path.parent / "secret.txt").write_text("outside")
    return tmp_path


class Scripted:
    """A fake chat model: replays a list of assistant messages and records what it was sent."""
    model, base_url = "fake", "http://fake/v1"

    def __init__(self, replies):
        self.replies, self.sent = list(replies), []

    def chat(self, messages, tools):
        self.sent.append((list(messages), tools))
        return self.replies.pop(0)


def _call(name, **args):
    return {"id": f"c-{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def test_tools_read_inside_the_checkout_and_never_outside(repo):
    tools = agent.RepoTools(repo)
    assert "item = pool.pop()" in tools.read_file("app/pool.py")["content"]
    assert tools.search(r"take\(")["matches"][0].startswith("app/")
    with pytest.raises(ValueError):
        tools.read_file("../secret.txt")
    assert tools.execute("read_file", {"path": "/etc/passwd"}) == {"error": "no such file: /etc/passwd"}  # rooted
    (repo / "link").symlink_to(repo.parent / "secret.txt")
    with pytest.raises(ValueError):
        tools.read_file("link")


def test_the_agent_uses_tools_then_keeps_only_findings_at_real_locations(repo):
    final = json.dumps({"findings": [
        {"file": "app/pool.py", "start_line": 2, "end_line": 2, "severity": "high", "category": "correctness",
         "message": "pop() on an empty pool raises IndexError; use.py calls take([])."},
        {"file": "app/pool.py", "start_line": 2, "end_line": 3, "category": "correctness", "message": "duplicate"},
        {"file": "app/pool.py", "start_line": 99, "message": "past the end"},
        {"file": "../secret.txt", "start_line": 1, "message": "outside"},
        {"file": "nope.py", "start_line": 1, "message": "made up"},
    ]})
    model = Scripted([{"content": "", "tool_calls": [_call("search", pattern="take\\(")]},
                      {"content": "```json\n" + final + "\n```"}])
    found, stats = agent.review(model, agent.RepoTools(repo), DIFF, diff.parse(DIFF))
    assert [(f.file, f.start_line, f.severity) for f in found] == [("app/pool.py", 2, "high")]
    assert stats.tool_calls == 1 and len(stats.dropped) == 3
    tool_message = model.sent[1][0][-1]
    assert tool_message["role"] == "tool" and "use.py" in tool_message["content"]
    assert "Do NOT report" in model.sent[0][0][0]["content"]  # the false-positive modes are in the prompt


def test_out_of_rounds_the_agent_asks_for_an_answer_without_tools(repo, monkeypatch):
    monkeypatch.setattr(agent, "MAX_ROUNDS", 2)
    model = Scripted([{"content": "", "tool_calls": [_call("list_dir", path="app")]}] * 2
                     + [{"content": '<think>done</think>{"findings": []}'}])
    found, stats = agent.review(model, agent.RepoTools(repo), DIFF, diff.parse(DIFF))
    assert found == [] and model.sent[-1][1] is None and stats.calls == 3


def test_the_adapter_writes_a_findings_file_the_benchmark_accepts(repo, tmp_path, monkeypatch):
    pr_dir = tmp_path / "pr"
    pr_dir.mkdir()
    (pr_dir / "diff.patch").write_text(DIFF + 'diff --git a/cfg.py b/cfg.py\n--- a/cfg.py\n+++ b/cfg.py\n'
                                             '@@ -0,0 +1 @@\n+KEY = "AKIAABCDEFGHIJKLMNOP"\n')
    (pr_dir / "pr.json").write_text(json.dumps({"title": "Pool", "body": ""}))
    out = tmp_path / "findings.json"
    for name, value in {"RB_NWO": "o/r", "RB_PR_NUMBER": "7", "RB_BASE": "b" * 40, "RB_HEAD": "h" * 40,
                        "RB_OUT": str(out), "RB_DIFF": str(pr_dir / "diff.patch"), "RB_PR_JSON": str(pr_dir / "pr.json"),
                        "RB_REPO": str(repo), "RB_AGENT": "grc-reviewer",
                        "RB_CONFIG_MODE": "both"}.items():
        monkeypatch.setenv(name, value)
    model = Scripted([{"content": json.dumps({"findings": [{"file": "app/pool.py", "start_line": 2, "end_line": 2,
                                                            "message": "IndexError on an empty pool."}]})}])
    monkeypatch.setattr(agent, "from_env", lambda: model)
    assert bench.main() == 0
    written = json.loads(out.read_text())
    assert written["pr"] == {"repo": "https://github.com/o/r", "pr_number": 7, "base": "b" * 40, "head": "h" * 40}
    assert {f["producer"] for f in written["findings"]} == {"grc-reviewer"}
    assert {(f["file"], f["start_line"]) for f in written["findings"]} == {("app/pool.py", 2), ("cfg.py", 1)}
    for f in written["findings"]:  # the same checks scripts/try-agent.sh applies
        assert isinstance(f["start_line"], int) and isinstance(f["end_line"], int) and f["message"]
        assert not f["file"].startswith(("./", "/"))
    assert "AKIA" not in out.read_text()  # the secret finding names the detector, not the key


def test_rules_only_mode_needs_no_model(repo, tmp_path, monkeypatch):
    pr = tmp_path / "d.patch"
    pr.write_text(DIFF)
    for name, value in {"RB_NWO": "o/r", "RB_PR_NUMBER": "1", "RB_BASE": "b", "RB_HEAD": "h",
                        "RB_OUT": str(tmp_path / "o.json"), "RB_DIFF": str(pr), "RB_REPO": str(repo),
                        "RB_CONFIG_MODE": "rules"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(agent, "from_env", lambda: pytest.fail("rules mode must not call a model"))
    assert bench.main() == 0
