# Branch rulesets

Rulesets are repository settings, so committing this file does not apply it. A repository admin
imports it once:

**Settings → Rules → Rulesets → New ruleset → Import a ruleset**, then pick `main-history.json`.

## `main-history.json`

Blocks force pushes to `main` and deletion of `main`, for everyone (no bypass list).

Why: on 28 September 2026, three commits were deployed to production and then vanished from
`main`'s history. The change-control collector's deploy reconciliation found this (ADR-020).
Code that ran in production should stay in the record.

It deliberately does **not** require pull requests: this repository is mostly worked on with
direct pushes, and requiring PRs would block that the moment the ruleset is applied. Requiring
PRs and approvals is a separate decision (ADR-019 rules 2–3).

`tests/test_change_control.py::test_the_repos_own_main_ruleset_blocks_force_pushes_for_everyone`
checks that the collector reads this file as "protected, force push blocked". After importing it,
the next change-control snapshot of this repository should show the same.
