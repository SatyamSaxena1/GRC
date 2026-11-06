# ADR-051: HR leaver evidence is reconciled on the customer's computer and uploaded as one number

**Status:** Accepted
**Date:** 2026-11-05
**Deciders:** Platform owner (accepted by the "ok go for it" instruction); a compliance reviewer should confirm the
control wording before a customer relies on it.

## Context
The HR evidence source needs one number: how many people who have left the organisation still have an active account
(`terminated_users_with_active_accounts`, judged `== 0`). It feeds the DPDP leaver-access rule and PCI DSS. Unlike AWS
and Microsoft 365, there is **no common HR system API**: every customer uses a different HR product and a different
directory. ADR-049 and ADR-050 settled that the platform holds no customer credential and customers upload their own
answers. The question here is only *what the customer's script reads*.

## Decision
The customer exports two CSV files and runs `app/collectors/hr_leavers.py` (standard library only) on their own
computer: **leavers.csv** (people who left, from HR) and **accounts.csv** (every account still active, from the directory,
for example Entra, Google Workspace or Okta). It matches them by email, ignoring case, spaces and repeats, and uploads
**one whole number**. No name or address leaves the computer, and addresses print locally only with `--show`.
It uses the same upload token and strict ingest as ADR-049, now accepting a count from 0 to 1,000,000 for this source
and still refusing counts from the yes/no sources.

## Options Considered

### Option A: Adapter per HR product (BambooHR, Workday, Zoho People, ...)
| Dimension | Assessment |
|-----------|------------|
| Complexity | High: one adapter and one credential flow per product |
| Cost | High and open-ended |
| Scalability | Poor: every new customer system is new work |
| Team familiarity | Low |

**Pros:** fully automatic once connected. **Cons:** we would hold or broker an HR credential, the most sensitive kind;
adapters rot as vendors change; most customers would still wait for the one they use.

### Option B: Reconcile two exports locally, upload the count (chosen)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low: one small script, no new endpoint |
| Cost | Low |
| Scalability | Works for every HR system and directory that can export a list |
| Team familiarity | High: reuses ADR-049 |

**Pros:** nothing personal ever leaves the customer; no HR credential anywhere near us; works for any system.
**Cons:** two manual exports each time unless the customer scripts them; the answer is only as good as the two files.

### Option C: Customer ticks "no leavers have access" in the app
| Dimension | Assessment |
|-----------|------------|
| Complexity | Lowest |
| Cost | Lowest |
| Scalability | Unlimited |
| Team familiarity | High |

**Pros:** trivial. **Cons:** it is an assertion, not evidence: nothing is reconciled, and it undermines the rule that the
platform's verdicts come from facts.

## Trade-off Analysis
The choice is between convenience and exposure. HR data is the most sensitive data a customer holds. Option B gives up
automation to keep every address and name on the customer's computer, which also removes any need to review the
platform's handling of HR personal data. Option C is weaker evidence; Option A is the most convenient and the highest
risk. Option B can be upgraded to A for a single product later without changing the upload.

## Consequences
- Easier: nothing personal is stored, logged or sent; one rule for all HR and directory products.
- Harder: freshness depends on the customer exporting again; an export of the wrong people gives a wrong count.
- Guard rails: an empty leavers list is reported as incomplete unless `--allow-empty` says nobody left; an empty accounts
  list is always incomplete (it is almost certainly the wrong file, not zero accounts). A run marked incomplete is never
  read as a pass.
- Limit stated plainly: this evidences that the two exports agree **at the time they were exported**. It does not prove
  the exports are complete.
- To revisit: whether to add a named adapter for the one HR product most customers use.

## Action Items
1. [x] Count-valued attributes in the ingest, with a 0 to 1,000,000 range and no booleans.
2. [x] `hr_leavers.py` with a dry run, `--show`, and a clear error for a missing column.
3. [x] HR card on the Connections page and the guide `docs/operations/hr-upload.md`.
4. [ ] Try it with a real leavers and accounts export from a pilot customer.
5. [ ] Decide on a named adapter for the most common HR product.
