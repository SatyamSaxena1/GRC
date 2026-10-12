"""AI code review as change-control evidence (ADR-026): Qodo, PR-Agent, CodeRabbit, Copilot or
Codex reviews are recorded as advisory facts. An AI review never counts as the independent
approval, and none of these facts changes a verdict."""

from __future__ import annotations

from app import change_gate
from app.collectors import github_change_control as gcc

HEAD = "abc123"
PROTECTED = {"enabled": True, "required_approving_reviews": 1, "dismiss_stale_reviews": True,
             "enforce_admins": True, "allow_force_pushes": False}


def _pr(reviews=(), threads=(), comments=(), tickets=("ABC-1",), number=1):
    return {
        "number": number, "url": f"https://github.com/acme/app/pull/{number}",
        "merged_at": f"2026-10-0{number}T00:00:00Z",
        "author": {"login": "alice", "is_bot": False}, "head_sha": HEAD,
        "reviews": [{"user": {"login": who, "is_bot": who.endswith("[bot]")}, "state": state,
                     "commit_id": HEAD, "submitted_at": "2026-10-01T00:00:00Z"} for who, state in reviews],
        "commits": [{"sha": HEAD, "message": "change", "author_login": "alice", "committer_login": "web-flow"}],
        "checks": [{"name": "ci", "conclusion": "success"}],
        "comment_authors": list(comments),
        "review_threads": None if threads is None else [{"author": a, "resolved": r} for a, r in threads],
        "linked_tickets": None if tickets is None else list(tickets),
    }


def test_qodo_or_pr_agent_count_as_ai_review_and_humans_or_unknown_bots_do_not():
    assert gcc.ai_reviewed(_pr(reviews=[("qodo-merge-pro[bot]", "COMMENTED")]))
    assert gcc.ai_reviewed(_pr(comments=["codiumai-pr-agent[bot]"]))  # PR-Agent posts issue comments
    assert gcc.ai_reviewed(_pr(threads=[("coderabbitai[bot]", False)]))  # restored from GraphQL __typename
    assert not gcc.ai_reviewed(_pr(comments=["claude"]))  # a person may be called claude: bots only
    assert gcc.ai_reviewed(_pr(comments=["review-svc"]), extra_reviewers=["review-svc"])  # named: as given
    assert not gcc.ai_reviewed(_pr(reviews=[("bob", "APPROVED")]))
    assert not gcc.ai_reviewed(_pr(comments=["dependabot[bot]"]))
    # PR-Agent run as an Action posts as whichever account runs it: named per collector run.
    assert gcc.ai_reviewed(_pr(comments=["acme-reviewer[bot]"]), extra_reviewers=["acme-reviewer"])


def test_an_ai_review_is_never_the_independent_approval():
    only_ai = _pr(reviews=[("qodo-merge-pro[bot]", "APPROVED")])
    assert not gcc.has_independent_approval(only_ai)
    counts = gcc.summarize([{"protection": PROTECTED, "pulls": [only_ai], "default_commits": []}])
    assert counts["merges_without_independent_approval"] == 1 and counts["ai_reviewed_merges"] == 1


def test_unresolved_ai_findings_are_counted_and_human_threads_are_not():
    pr = _pr(threads=[("qodo-merge-pro[bot]", False), ("qodo-merge-pro[bot]", True), ("bob", False)])
    assert gcc.unresolved_ai_findings(pr) == 1
    counts = gcc.summarize([{"protection": PROTECTED, "pulls": [pr, _pr(threads=[], number=2)],
                             "default_commits": []}])
    assert counts["merges_with_unresolved_ai_review_findings"] == 1


def test_threads_that_could_not_be_read_are_unknown_never_zero():
    pr = _pr(threads=None, tickets=None)
    assert gcc.unresolved_ai_findings(pr) is None and gcc.has_linked_ticket(pr) is None
    counts = gcc.summarize([{"protection": PROTECTED, "pulls": [pr, _pr(number=2)], "default_commits": []}])
    assert counts["merges_with_unresolved_ai_review_findings"] is None
    assert counts["merges_without_linked_ticket"] is None


def test_ticket_keys_and_issue_numbers_only():
    assert gcc.ticket_keys("Fix login (ABC-123), see #45", "feature/OPS-9-retry") == ["#45", "ABC-123", "OPS-9"]
    assert gcc.ticket_keys("Use UTF-8 and SHA-256", None) == []  # one-letter-digit tokens are not keys
    assert gcc.ticket_keys("a&#39;b", None) == []                 # HTML entities are not issues


def test_advisory_rows_never_crowd_out_failed_rules():
    pulls = [_pr(reviews=[("bob", "APPROVED")], threads=[("qodo-merge[bot]", False)], tickets=(), number=n)
             for n in range(1, 6)]
    pulls.append(_pr(reviews=[], number=9))  # no approval: a real PULL_REQUEST row
    rows, left_out = gcc.exceptions([{"repo": "acme/app", "protection": PROTECTED, "pulls": pulls,
                                      "default_commits": []}], limit=3)
    # The failed rule first, then advisory rows in what room is left, gate rows always kept.
    assert [(r["kind"], r["ref"]) for r in rows] == [("PULL_REQUEST", "#9"), ("PULL_REQUEST_ADVISORY", "#5"),
                                                    ("GATE_CHECK", "ci")]
    assert left_out == 4
    assert {r["rule"] for r in rows[1]["reasons"]} == {"AI_FINDINGS_UNRESOLVED", "NO_LINKED_TICKET"}


def test_the_advisory_facts_never_change_a_verdict():
    from app.content.load import load as load_content
    from app.evaluate import evaluate
    content = load_content()
    clean = _pr(reviews=[("bob", "APPROVED")])
    noisy = _pr(reviews=[("bob", "APPROVED")], threads=[("qodo-merge[bot]", False)], tickets=())
    snap = lambda pr: gcc.summarize([{"protection": PROTECTED, "pulls": [pr],
                                      "default_commits": [{"sha": "m", "has_pull": True}]}])
    verdicts = [{(l.framework, l.clause): l.verdict
                 for l in evaluate(snap(pr), "CHANGE_CONTROL_SNAPSHOT", ["SOC-2", "ISO-27001", "PCI-DSS"], content)}
                for pr in (clean, noisy)]
    assert verdicts[0] == verdicts[1]


def test_the_gate_reports_ai_review_as_advisory_and_its_result_is_unchanged(capsys):
    from test_change_gate import _GitHub, _run
    clean = _run(_GitHub(reviews=[("bob", "h9")], closing=[12]), capsys=capsys)
    noisy = _run(_GitHub(reviews=[("bob", "h9")], threads=[("qodo-merge-pro", False)],
                         comments=["qodo-merge-pro[bot]"]), capsys=capsys)
    assert clean[0] == noisy[0] == change_gate.PASS
    assert clean[1]["advisory"] == {"ai_reviewed": False, "unresolved_ai_findings": 0, "linked_tickets": ["#12"]}
    assert noisy[1]["advisory"] == {"ai_reviewed": True, "unresolved_ai_findings": 1, "linked_tickets": []}
    line = change_gate._advisory_line(noisy[1]["advisory"])
    assert "AI review: yes, 1 unresolved finding" in line and "Ticket: none linked" in line


def test_the_connector_accepts_the_new_attributes():
    from app.routers import connectors
    allowed = connectors.SOURCES["github"][2]
    assert {"ai_reviewed_merges", "merges_without_ai_review", "merges_with_unresolved_ai_review_findings",
            "merges_without_linked_ticket"} <= set(allowed)


def test_unread_or_uncollected_sources_are_unknown_never_no_review():
    """Review fix: a comments read that failed, or a collector that gathers no comments at all
    (GitLab, Bitbucket), must not be counted as "no AI review"."""
    unread = {**_pr(), "comment_authors": None}
    assert gcc.ai_reviewed(unread) is None
    assert gcc.ai_reviewed({**unread, "reviews": [{"user": {"login": "coderabbitai", "is_bot": True},
                                                   "state": "COMMENTED", "commit_id": HEAD}]}) is True
    gitlab_shaped = {k: v for k, v in _pr().items() if k not in ("comment_authors", "review_threads")}
    assert gcc.ai_reviewed(gitlab_shaped) is None
    counts = gcc.summarize([{"protection": PROTECTED, "pulls": [gitlab_shaped, _pr(number=2)], "default_commits": []}])
    assert counts["ai_reviewed_merges"] is None and counts["merges_without_ai_review"] is None
    assert "AI review: unknown" in change_gate._advisory_line(
        {"ai_reviewed": None, "unresolved_ai_findings": None, "linked_tickets": None})
