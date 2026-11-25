# Plan: a "Your path to audit-ready" view

**Status:** proposal for the owner to approve. Nothing in the product changes until then. Written 25 Nov 2026.

## 1. The problem in one paragraph
Someone who wants to become audit-ready has an order of work: decide the scope, see the honest starting point, write and
approve policies, connect evidence, attest what a machine cannot read, record risks and suppliers, close gaps, then meet
the auditor. Our own case study followed exactly that order. The product has a page for every one of those jobs, but the
menu is a flat list of about 25 pages arranged by feature, and no screen says "you are at step 3, here is the next one".
The only guided piece, the first-week checklist (`app/onboarding.py`, ADR-058), covers setting up the product (connect a
source, upload a policy, invite two people, publish the trust page, give a control an owner). It does not cover the
compliance journey, so it is done after a week and says nothing about the months after.

## 2. What we found (read from the routes and components, not from a usability test)
- `frontend/src/App.tsx` has about 25 top-level pages with no grouping by stage.
- Pages do not say what feeds them or what they feed.
- Journey explanations live apart from the working app: `/learn/soc-2`, `/pitch`, `/jeff`.
- The first-week checklist already proves the useful trick: every step is read from real data, with no stored "done" flag,
  so nothing can be ticked without having been done. We keep that rule.
- Unverified: how a first-time customer actually behaves. Step 1 of the build below includes watching two real people.

## 3. Proposal: one ordered path per framework
A new page `/path` (the landing page for an organisation admin, replacing the Overview's checklist card) that shows eight
stages. Each stage shows **done / in progress / not started**, **who does it**, **what it needs**, and **one button to the
page that does the work**. Every state is computed from data that already exists.

| # | Stage | Done when (read from data) | Page it links to | Who |
|---|-------|----------------------------|------------------|-----|
| 1 | Choose scope and frameworks | the organisation has at least one framework and a scope statement | Frameworks | Org admin |
| 2 | See your honest starting point | a readiness run exists | Overview / Gaps | Org admin |
| 3 | Write and approve policies | every policy the chosen frameworks require has an approved version | Policies | Policy owner, approver |
| 4 | Connect evidence sources | at least one source collected, none stuck on PARTIAL | Connections | Org admin |
| 5 | Attest what a machine cannot read | every attestation-only clause has a current attestation (not expired) | Frameworks / Gaps | Named control owners |
| 6 | Record risks and suppliers | risks have owners and review dates; suppliers have a status | Risks, Vendors | Risk owner |
| 7 | Close or accept the gaps | no open gap without a fix, an owner or an accepted exception | Gaps | Control owners |
| 8 | Get audit-ready | stages 1 to 7 done, and an auditor invitation or evidence pack exists | Firm / Evidence map | Org admin |

For DPDP the same view lists its own stages (notice, consent and rights handling, breach rule, retention, logs, processors).
Frameworks share the page; the stage list comes from the framework pack so a new pack needs no new screen code.

Three small rules keep it honest:
- A stage is never ticked by a click. It is ticked by the data, as in ADR-058.
- "AI-assessed" (ADR-069) counts as in progress until a named person confirms it; only the confirmed state counts as done.
- Each stage names the next single action, not a list.

## 4. Smaller changes that go with it
- Group the menu into the same stages instead of an alphabet of features, with the current stage highlighted.
- A one-line "Part of stage N" strip at the top of each existing page, with a link to the next stage.
- Keep the first-week checklist as stage 0 ("set up the product") so nothing already built is thrown away.
- Bring the `/learn` explanations inside the path as "Why this step" links, rather than as a separate area.

## 5. How to build it (smallest first)
1. **Look first.** Watch two people who have never seen the product try to reach "audit-ready" with the current screens
   and note where they stop. A week of work at most; it decides how big the menu change needs to be.
2. **Backend:** a `path` function beside `checklist()` that returns the stage list for the organisation's frameworks, each
   with state, owner role and link. Tests for each stage's done rule, including the AI-assessed rule.
3. **Frontend:** the `/path` page and the "Part of stage N" strip. Menu regrouping last, behind one flag, so the old menu
   stays available while we compare.
4. **Case study and demo:** update the video outline so it follows the same eight stages.

## 6. Decisions needed from the owner
1. Is stage 8 ("meet the auditor") in scope now, or do we stop at stage 7 until an audit firm is chosen?
2. Replace the Overview card with `/path`, or keep both for a while?
3. Regroup the menu now, or only after step 1 (watching two people) says it is needed?

## 7. What this plan does not claim
- It does not claim the current layout is bad for every user, only that it is not organised by the journey.
- The stage list is our reading of the order from one real run (the case study); an auditor may order some stages differently.
- Stage "done" rules for suppliers and the auditor handover still need checking against the data model before build.
