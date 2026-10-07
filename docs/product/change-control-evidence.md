# Change-control evidence for AI-written code — product brief

*Working title: **Gatekeeper**. Status: first slice built (ADR-020); everything below "What
exists today" is proposal.*

## The problem, in one paragraph
Every SOC 2, ISO 27001 and PCI DSS audit asks the same question about software: did changes
reach production only after someone authorized and tested them? Auditors answer it by
sampling: pull 25 merged changes, look for an approval and a green build. That method assumed a
person wrote each change and a different person read it. With coding agents, a single developer
can merge dozens of agent-written pull requests a day, the agent's bot account opens them, and
the developer who prompted the agent approves them. On paper the sample shows "author ≠
approver". In substance it is self-review. No current sampling method catches this, and the
volume makes sampling weaker every quarter.

## The product
A read-only connector that judges **every** merge in the audit period against
change-management rules, not a sample of 25:

1. **Connect.** The client installs a read-only GitHub token (later GitLab or Bitbucket). We read
   metadata only — never source code, never a write.
2. **Collect.** For each period, a deterministic collector records who opened, wrote, approved and
   merged each change; whether the approval covered the merged commit; whether checks ran and
   passed; any direct pushes; and branch-protection settings.
3. **Judge.** The platform's rule engine maps those facts onto SOC 2 CC8.1, ISO 27001 A.8.32 and
   PCI DSS 6.5.1 at once, with the usual cross-framework delta (ISO accepts what PCI does not).
4. **Remediate.** Each failed condition becomes a gap and a task: "3 AI-assisted merges were
   approved only by the person who prompted the agent."
5. **Lock.** The auditor reviews the exceptions and locks the change-control verdict for the
   period. The snapshot is hash-chained evidence that does not depend on GitHub keeping its
   history.

## Why this platform, and not a feature in someone else's
- **Same architecture, new evidence type.** The witness / rules / human-lock split (ADR-004)
  already exists, along with the connector contract, content packs, versioned evidence and the
  auditor workflow. The new parts are one collector, two control objectives and three clauses.
- **Independence by design.** We read the client's Git and never run it. That keeps the auditor
  independent, and it is the answer to "why not just switch VCS" (ADR-019, ADR-020).
- **Rules about AI that are defensible.** Our tests define "independent approval" exactly: a
  human, on the merged commit, who wrote none of it. An auditor can read that rule and accept it.
  Nothing a model says moves a verdict.
- **Portability.** GitHub's approvals do not travel with a clone. A locked snapshot here is the
  durable record of who approved what, held by the auditor, not the vendor.

## Who buys it
| Buyer | Pain | What they get |
|---|---|---|
| **Audit firms** (the platform's existing side) | Change-management testing is manual sampling, and AI volume makes samples less representative | Full-population testing of every merge, with exceptions listed; less fieldwork, a stronger opinion |
| **Engineering-heavy auditees** (SaaS, fintech) adopting coding agents | "Can we use agents and still pass SOC 2?" | A live answer before the audit, and the specific merges to fix |
| **Compliance leads** | No visibility into how agent use affects controls | AI-assisted merge counts and the self-review rate, per period |

## Rules catalogue
Built today (in all three packs unless noted):

| Fact | Rule |
|---|---|
| `default_branch_protected` | must be true in every repository in scope |
| `required_approving_reviews` | ≥ 1 |
| `merges_without_independent_approval` | = 0 |
| `merges_with_failing_or_missing_checks` | = 0 (no checks at all is not a pass) |
| `direct_pushes_to_default` | = 0 |
| `ai_assisted_merges_without_independent_approval` | = 0, reported as its own gap |
| `force_push_allowed_on_default` | must be false |
| `admins_can_bypass`, `stale_reviews_dismissed` | gate must hold for admins, and approvals must reset on new pushes; required by SOC 2 and PCI, SUPPORTING for ISO |
| `gate_path_merges_without_two_independent_approvals` | = 0 for SOC 2 and PCI: changes to CI, tests or ownership need two independent approvals |
| `deployments_not_from_default_branch`, `deployments_of_unreviewed_changes` | = 0 in all three: what ran in production must be what was approved |

Next, roughly in order of value:
1. ~~**Per-merge exceptions**~~: built. Every failing merge or push is listed with its rules,
   the reason in words, and a link to open it.
2. ~~**Gate liveness**~~: built. Required checks that never failed on any push in the period are
   listed for a canary run (advisory; no verdict changes), because a check that cannot go red is
   decoration (ADR-019 rule 1).
3. ~~**Gate-path changes**~~: built. Merges that touch CI workflows, tests, CODEOWNERS or hook
   config need two independent approvals under SOC 2 and PCI; removed gate files are flagged.
   Code-owner approval as an alternative is not yet read.
4. ~~**Rulesets**~~: built. Classic protection and active rulesets are combined, strictest wins.
5. ~~**Deploy reconciliation**~~: built. Production deployments (GitHub Deployments or named CI
   deploy jobs) are matched to the approved history; deploys from outside the default branch, of
   direct pushes, or of unapproved merges fail CC8.1, A.8.32 and 6.5.1.
6. ~~**GitLab**~~: built (gitlab.com and self-managed), same snapshot and rules. **Bitbucket** next.

## Pricing hypotheses (to test, not decided)
- Audit firms: per engagement, as an add-on to the existing platform.
- Auditees: per repository per month, with the continuous dashboard as the upsell.

## Risks, frankly
- **Approval is not understanding.** We prove that a separate person approved the exact code that
  shipped, not that they read it. Sell it as change-control evidence, never as code quality.
- **AI assistance is self-declared.** Agents that leave no trailer are invisible. The rules hold
  anyway, because independence is checked on every merge, AI-assisted or not.
- **Token risk.** A read-only, metadata-scoped token is a hard requirement; a write-capable token
  would make us a supply-chain target.
- **Competition.** Compliance-automation platforms already read branch-protection *settings*.
  Our difference is per-merge judgement, the agent-laundering rule, and auditor-locked evidence.
- **Personal data.** Logins and review timestamps are personal data under GDPR and DPDP. Keep
  counts in the snapshot, hold per-merge detail for the audit period only, and document retention.

## What exists today
- `app/collectors/github_change_control.py`: a pure `summarize()` (the rules on independent
  approval) plus a thin read-only `fetch()` over the GitHub REST API, runnable as a CLI that
  prints the collector JSON.
- The `github` source in `app/routers/connectors.py` (`CHANGE_CONTROL_SNAPSHOT`).
- UCO-CHG-001/002 and the three clauses in the SOC 2, ISO 27001 and PCI DSS packs.
- `GET /evidence/{id}/exceptions` and an Exceptions table on the evidence page, filterable by rule.
- `tests/test_change_control.py`: independence rules, check rules, a fake GitHub API, and
  connector-to-verdict tests across all three frameworks.

## A good first milestone
Run the collector against this repository for the last 90 days, put the snapshot through the
platform, and walk an auditor through the result. This repository is a good first customer: most
of its merges are AI co-authored, and ADR-019 already predicts what the snapshot will find.
