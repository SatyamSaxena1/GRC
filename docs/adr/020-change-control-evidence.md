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
- The snapshot is a single document per period. Per-merge exceptions (which PRs failed) are the
  next step; the auditor needs the list, not only the count.
- Branch *rulesets* are not yet read, only classic branch protection. A repository protected only
  by rulesets will read as unprotected, which is a false gap but never a false pass.
- GitHub answers the branch-protection endpoint with 404 to any token without administration
  read access, so an under-scoped token also reads as "unprotected". First run against this
  repository (2026-10-07, unauthenticated) showed exactly that. Protection facts need either
  that scope or the rulesets endpoint, which plain read access can see.
- The connector's environment-variable names carry the historical `DPDP_` prefix
  (`DPDP_GITHUB_COLLECTOR_URL`); renaming it is a separate change.
- GitLab and Bitbucket need their own `fetch()`; `summarize()` and the packs are reused unchanged.
- The collector's token must be fine-grained and read-only: metadata, pull requests, contents
  read for commit metadata, and checks. A token that can write would make the platform a
  supply-chain target.
