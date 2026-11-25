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

## `main-pull-requests.json`

Applied to this repository on 25 Nov 2026 (ruleset id 28054386), beside `main-history.json`.

- Every change to `main` arrives by pull request. Nobody can push straight to it, and there is no bypass list.
- The checks `backend`, `frontend`, `rls` and `change-control gate` must pass before a merge.
- Approvals that predate a new push are dismissed.
- **Does not require an approving review** (`required_approving_review_count` is 0): GitHub does not let a person approve
  their own pull request, so a one-person team would be locked out. Raise it to 1 when a second reviewer exists, and
  say so in the risk register. Until then, "merges without independent approval" stays a recorded gap.
- If a required check shows a duplicate cancelled run, re-run it; a cancelled required check blocks a merge.

Why: the platform's own GitHub collection (25 Nov 2026) found 75 direct pushes and 17 merges with failing or missing checks
in 90 days. The counts fall as old months age out of the window.

## `main-classic-protection.json` (classic branch protection, applied 25 Nov 2026)

Applied with `gh api -X PUT repos/SatyamSaxena1/GRC/branches/main/protection --input main-classic-protection.json`.

It repeats what `main-pull-requests.json` enforces (pull requests, the four required checks, stale approvals dismissed, no
force-push or deletion) and adds **"include administrators"**. The duplication is deliberate and is about *evidence*, not
safety:

- GitHub shows a ruleset's bypass list only to callers who can edit it. A read-only connection (a fine-grained token, or the
  GitHub App with read permissions) therefore cannot see that our ruleset has no bypass list, and the change-control
  collector, which never lets a hidden value pass, reports `admins_can_bypass: yes`.
- Classic protection shows `enforce_admins` to a read-only caller, so the collector can read it and close that gap.

For a customer using rulesets with a read-only connection, the same applies: to prove administrators cannot bypass,
use classic protection with "Include administrators", or the check will read as a gap.

Still zero required approving reviews, for the one-person reason above. Raise both settings together when a second reviewer
exists.
