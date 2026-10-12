"""Unified diffs into the per-file facts the review engine reads (ADR-027)."""

from __future__ import annotations

from app.review import diff

GIT_DIFF = """\
diff --git a/app/a.py b/app/a.py
index 111..222 100644
--- a/app/a.py
+++ b/app/a.py
@@ -1,3 +1,4 @@
 import os
-x = 1
+x = 2
++++ not a header
 y = 3
\\ No newline at end of file
diff --git a/old/name.py b/new/name.py
similarity index 90%
rename from old/name.py
rename to new/name.py
--- a/old/name.py
+++ b/new/name.py
@@ -10,2 +10,2 @@ def f():
-    return 1
+    return 2
     pass
diff --git a/gone.txt b/gone.txt
deleted file mode 100644
--- a/gone.txt
+++ /dev/null
@@ -1 +0,0 @@
-bye
diff --git a/new.txt b/new.txt
new file mode 100644
--- /dev/null
+++ b/new.txt
@@ -0,0 +1,2 @@
+hello
+
diff --git a/logo.png b/logo.png
Binary files a/logo.png and b/logo.png differ
"""


def test_a_git_diff_becomes_files_with_added_lines_and_their_numbers():
    files = {f.path: f for f in diff.parse(GIT_DIFF)}
    assert list(files) == ["app/a.py", "new/name.py", "gone.txt", "new.txt", "logo.png"]
    a = files["app/a.py"]
    # A content line that starts with '+++' is content, not a new file's header.
    assert a.added == [(2, "x = 2"), (3, "+++ not a header")] and a.removed == 1
    renamed = files["new/name.py"]
    assert (renamed.status, renamed.previous_path, renamed.added) == ("renamed", "old/name.py", [(10, "    return 2")])
    assert files["gone.txt"].status == "deleted" and files["gone.txt"].added == []
    assert files["new.txt"].status == "added" and files["new.txt"].added == [(1, "hello"), (2, "")]
    assert files["logo.png"].binary


def test_a_plain_diff_without_git_headers():
    files = diff.parse("--- a/x.txt\n+++ b/x.txt\n@@ -1 +1 @@\n-a\n+b\n--- a/y.txt\n+++ b/y.txt\n@@ -5,0 +6 @@\n+c\n")
    assert [(f.path, f.added) for f in files] == [("x.txt", [(1, "b")]), ("y.txt", [(6, "c")])]


def test_github_files_and_an_omitted_patch_is_never_read_as_unchanged():
    files = diff.from_github_files([
        {"filename": "a.py", "status": "modified", "patch": "@@ -1,2 +1,2 @@\n ctx\n-old\n+new", "additions": 1},
        {"filename": "huge.json", "status": "modified", "additions": 90000, "changes": 90000},
        {"filename": "b.py", "status": "renamed", "previous_filename": "c.py", "patch": "@@ -0,0 +1 @@\n+z"},
        {"filename": "img.png", "status": "added", "additions": 0, "changes": 0},
        {"filename": "d.py", "status": "removed", "changes": 4},
    ])
    by = {f.path: f for f in files}
    assert by["a.py"].added == [(2, "new")]
    assert by["huge.json"].too_large and not by["img.png"].too_large
    assert (by["b.py"].status, by["b.py"].previous_path) == ("renamed", "c.py")
    assert by["d.py"].status == "deleted" and not by["d.py"].too_large


def test_unusual_input_is_marked_not_dropped():
    text = (
        'diff --git "a/caf\\303\\251 menu.py" "b/caf\\303\\251 menu.py"\r\n'
        '--- "a/caf\\303\\251 menu.py"\r\n+++ "b/caf\\303\\251 menu.py"\r\n'
        "@@ -1 +1 @@\r\n-a\r\n+b\r\n"
        "diff --git a/link b/link\nnew file mode 120000\n--- /dev/null\n+++ b/link\n@@ -0,0 +1 @@\n+../target\n"
        "diff --git a/run.sh b/run.sh\nold mode 100644\nnew mode 100755\n"
        "diff --cc merged.py\nindex 1,2..3\n@@@ -1,1 -1,1 +1,1 @@@\n++x\n"
    )
    files = {f.path: f for f in diff.parse(text)}
    assert files["café menu.py"].added == [(1, "b")]             # quoted, octal-escaped UTF-8, CRLF
    assert files["link"].skipped == "symlink" and files["link"].added == []
    assert files["run.sh"].added == [] and files["run.sh"].skipped is None   # a mode change: nothing to read
    assert files["merged.py"].skipped == "unsupported"
