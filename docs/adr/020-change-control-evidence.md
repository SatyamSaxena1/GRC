# ADR-020: Change-control evidence from clients' repositories — read Git, never replace it

> **Status:** Proposed. A first slice is implemented: `app/collectors/github_change_control.py`,
> the `github` connector source, UCO-CHG-001/002, and SOC 2 CC8.1, ISO 27001 A.8.32 and
> PCI DSS 6.5.1 (`tests/test_change_control.py`). Product framing: `docs/product/change-control-evidence.md`.

## Context
AI agents now write a large share of production code, and the evidence auditors use for change
management has not kept up. A sample of approvals checks nothing about the pull request an agent
opened and its prompter approved. ADR-019 worked through this for our own repository and found
the gap is in verification and provenance, not in Git's storage.

The tempting product is a better version-control system that the platform runs for clients. We
rule it out: an auditor that operates the auditee's change-control system is no longer
independent, and converting history means altering the evidence it is supposed to preserve.

## Decision
The platform reads clients' repositories and judges them the way it judges an uploaded policy
(ADR-004):

- **Witness.** A collector reads GitHub's API and produces a `CHANGE_CONTROL_SNAPSHOT`: counts and
  settings, such as merges in the period, merges without an independent approval, merges whose
  checks failed or never ran, direct pushes, AI-assisted merges, and branch-protection settings.
  It reads metadata only: never source code, never a write. It runs as a collector behind the
  existing connector contract, so tokens stay server-side.
- **Rules decide.** Content packs map the snapshot onto two new control objectives, UCO-CHG-001
  (independent review and passing checks) and UCO-CHG-002 (gates hold for everyone). SOC 2 CC8.1
  and PCI DSS 6.5.1 require both; ISO 27001 A.8.32 treats admin-bypass and stale-approval
  settings as SUPPORTING. That gives the usual cross-framework delta from a single snapshot.
- **Human locks.** The auditor reviews the exceptions and locks the verdict for the period.

What "independent approval" means is fixed in code, in `summarize()`, and is deterministic:
- the approver is a human, not a bot;
- their latest review approves the exact commit that was merged;
- they authored or committed no part of the change.

The last rule closes the agent-laundering case: a person prompts an agent, the agent's bot account
opens the PR, and the same person approves it.

AI assistance is counted only where a tool **declares** it, through a co-author trailer or a bot
author. That is why no rule treats "not AI-assisted" as passing. The AI-specific condition (zero
AI-assisted merges without independent approval) is a subset of the general one, kept separate so
it is reported as its own gap.

## Alternatives considered
- **Host or convert clients' version control** (a Git replacement run by the platform). Rejected:
  it breaks auditor independence and chain of custody, and the arguments for it (ADR-019) point at
  verification, not storage.
- **Ask a model whether a change was properly reviewed.** Rejected by ADR-004. Every fact here is
  available from the API, so no model is needed at all.
- **Read source code to judge change quality.** Rejected: it multiplies the data we hold and the
  supply-chain risk, and change *control* is about the process, not the code's merit.
- **Detect undeclared AI code.** Rejected: there is no reliable signal, and a false "human-written"
  would be a false pass.

## Consequences
- Each snapshot also stores the per-item rows behind its counts: every merge or push that failed
  a rule, the rules it failed, and why in words (for example "alice approved but wrote or committed
  part of the change"). The rows are produced by the same functions as the counts, stored inside the
  same hashed snapshot, served by `GET /evidence/{id}/exceptions` and shown on the evidence page.
  They carry identifiers, links and logins, never titles or diffs, and are capped at 500 per
  snapshot (the counts never are).
- **Gate liveness is advisory.** A gate check (the branch's required checks, or every check
  that ran on merged commits when none are required) is counted over every push of every PR
  merged in the period, because the merged head is green by construction. A check that never
  failed is listed as a `GATE_CHECK` row asking for a canary run, and counted in
  `gate_checks_never_seen_failing`, but no clause fails on it: a careful team can stay green, so
  "never failed" is unproven, not broken. Cancelled runs prove nothing either way. Two API calls
  per push, capped at the newest 30 pushes per PR. Without required checks the gate includes
  non-gate jobs (deploys, review bots), which is one more reason to require checks.
- **Protection is the combination of classic branch protection and every active ruleset**
  (repository and organisation level), combined the way GitHub enforces them: all layers apply,
  so the strictest setting wins. That means the most required approvals, stale approvals dismissed
  if any layer says so, force pushes blocked if any layer blocks them, and the union of required
  checks. Administrators count as bound if any layer that requires review binds them: classic
  protection with "include administrators", or a ruleset known to have no bypass list. The
  snapshot's protection names its sources (`classic`, `ruleset:<name>`).
- The rulesets endpoint needs only read access, so a ruleset-protected branch now reads correctly
  with a plain token. Two unknowns stay conservative, giving possible false gaps but never false
  passes: classic protection answers 404 to a token without administration read, and a ruleset's
  bypass list is shown only to callers who can edit it, so a hidden list counts as bypassable.
- **Gate paths need two independent approvals** (SOC 2 and PCI; recorded but not a condition
  for ISO, the same delta as admin bypass). Gate files are CI definitions, tests, CODEOWNERS and
  hook configuration (`GATE_PATTERNS`, extendable per client with `--gate-path`), matched on the
  PR's file list, file names and status only, never the diff, at one extra API call per PR.
  A rename out of a gate path counts. Removing a gate file is listed as advisory
  (`GATE_FILE_REMOVED`): deleting an obsolete test is normal, so it asks the auditor to check,
  rather than failing. Two approvals is our baseline reading of "authorized" for changes that can
  weaken every later check (ADR-019 rule 2), not quoted framework text. Direct pushes are not
  matched against gate paths; they are already exceptions in their own right.
- **Deploy reconciliation** compares what ran in production with what was approved. Deployments
  come from GitHub's Deployments API (environments named with `--environment`, default
  `production`) and from successful runs of CI jobs that deploy (`--deploy-job`), for teams that
  deploy through a hosting hook and never record a GitHub Deployment. A deployed commit that is not
  in the default branch's history is `DEPLOY_NOT_FROM_DEFAULT`: it was either shipped from another
  branch or later erased from the branch by a force push, and both are findings. A deployed direct
  push, or a deployed PR merged without an independent approval, is `DEPLOY_OF_UNREVIEWED_CHANGE`.
  Both are conditions in all three frameworks under UCO-CHG-001. Commits from before the period
  are not judged. No deployments at all counts as zero, not as a failure. History is checked
  with one compare call per distinct deployed commit; at most 200 Actions runs are read.
- Pagination follows the page number on the `/repos/<owner>/<name>` URL rather than GitHub's
  next links, which use `/repositories/<id>/` paths that some egress proxies refuse.
- The connector's environment-variable names carry the historical `DPDP_` prefix
  (`DPDP_GITHUB_COLLECTOR_URL`); renaming it is a separate change.
- **GitLab** (`app/collectors/gitlab_change_control.py`, connector source `gitlab`, gitlab.com or
  self-managed via `--url`) maps onto the same snapshot, and `summarize()`, `exceptions()` and the
  packs are reused unchanged. So a verdict means the same on either platform. Where GitLab records
  less, the mapping stays conservative:
  - Approvals carry no commit, so they count as covering the merged commit only when the project
    resets approvals on push; otherwise they are treated as possibly stale.
  - Commits carry a name, not a username, so an approver whose name matches a commit author is
    not independent.
  - Nobody may push directly to the branch → admins bound. "Pipelines must succeed" → every job
    is part of the gate. Jobs that are allowed to fail are not the gate going red.
  - Checks come from the MR's own pipelines (fork and "merged results" pipelines appear only
    there); the latest pipeline before the merge is the one that gated it.
  - File names come from the diffs endpoint, which also returns diff text; only names and status
    are kept.
  - Settings hidden from the token (401/403/404) read as unknown; hidden deployments print a
    warning instead of reading as none. The token needs `read_api` with at least Reporter access.
- Bitbucket still needs its own `fetch()`.
- The collector's token must be fine-grained and read-only: metadata, pull requests, contents
  read for commit metadata, and checks, plus administration read if classic branch protection
  is used (rulesets need none). A token that can write would make the platform a
  supply-chain target.
