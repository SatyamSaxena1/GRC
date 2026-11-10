# ADR-058: A first-week checklist read from real data, and drift counted from a verdict history

**Status:** Accepted
**Date:** 2026-11-10
**Deciders:** Platform owner

## Context
GRC is sold person to person to Indian SaaS and fintech startups, and two numbers decide whether a customer renews:
how fast they reach a first verdict (activation), and whether the product keeps telling them what changed (the reason
to open it in month six). Neither existed. A new admin landed on an empty Overview with only a guided tour, and nothing
recorded when an organisation was created or when its first verdict arrived. The weekly report (ADR-041) said how many
gaps were raised and resolved, but not which controls had got worse, because the platform never kept a control's
verdict over time: a link's `evaluated_at` is overwritten on every run and `VerdictRecord` (ADR-029) holds only an
auditor's decisions.

## Decision
**First-week checklist (organisation admin only).**
- `GET /onboarding` returns the steps and whether each is done: connect a source, upload a policy, invite two people,
  publish the trust page, give a control an owner, and, optional, settle any partial collection (ADR-046).
- **Every step is derived from data; nothing is stored or hand-ticked.** A source is any connection other than the chat
  webhook, or any collection run; a policy is any evidence whose type ends in POLICY; "two people" is two other active
  people in the organisation; the trust page is published while its token is set; an owner is any control assignment.
  Undoing the work (unpublishing the page) un-ticks the step.
- The optional step is done when sources have run and none has a PARTIAL latest run. It never blocks finishing, because
  most organisations never need it.
- The card sits on the Overview, links each step to the page where it is done, and hides itself once the five required
  steps are done. Anyone who is not an organisation admin gets `403` and sees nothing. It adds no navigation item.

**Time to first verdict.**
- `organizations.created_at` (set when the organisation is created) and `organizations.first_verdict_at` (set once, at
  the end of the first pipeline run that evaluated a requirement **and** rested on facts the platform read).
  A run where the model returned nothing usable is not a verdict anyone could act on (ADR-004), so it does not stop the clock.
- Both columns are nullable and nothing is backfilled: an organisation that existed before this has no `created_at`,
  so it shows no figure rather than an invented one.
- The figure, in minutes, is on the checklist card and on the operator's organisation list (`GET /admin/organizations`,
  the Operator page), which is where activation is read.

**Drift.**
- New tenant table `control_verdict_changes` (org, framework, clause, verdict, time), under row level security from the
  start. A row is written **only when a control's verdict differs from the last one recorded**; the verdict as of a date
  is the latest row at or before it. That keeps it small and answers every question drift asks.
- The verdict recorded is the control's, by the same rule the Controls and trust pages use (an auditor's lock counts
  as its mapped verdict; whole-estate evidence decides by its worst). A test holds the two equal.
- Two writers: the evaluation pipeline, for the requirements it has just judged, and `drift.snapshot`, run by
  `python -m app.monitor --weekly-report` for every control before it counts, which catches what no evaluation touches
  (an auditor locking or reopening a control).
- **"Turned worse" is a net comparison:** the verdict at the start of the seven days against the verdict now, by the rank
  PASS, PARTIAL, FAIL, NO_EVIDENCE. PASS to FAIL to PASS in one week is not reported; moving up from NO_EVIDENCE is never
  worse; a control first recorded inside the week is compared with its first row.
- **Connector not refreshed in N days:** a source the organisation has used whose last run that was not FAILED is 14 days
  old or more (`drift.CONNECTOR_STALE_DAYS`). A source that has only ever failed is dated from its latest attempt. A source
  the organisation scoped out of DPDP readiness is its own decision and is skipped; a source never used is not "quiet".
- **Evidence expiring within 30 days** was already computed by `app/monitor.py` (and is already on the Notifications page);
  the weekly report now carries its count and the count of evidence already past it.

**Where it shows.**
- Weekly report (`GET /reports/weekly`, the Markdown, and the Monday chat post): a `drift` block of counts and one
  sentence, for example "Drift: 3 controls turned worse this week, 5 evidence items expiring within 30 days
  (1 already expired), 1 connector not refreshed in 14 days." With nothing to say it says so. **Counts only, as in
  ADR-041:** no control, framework, source or file is named, and a test asserts none appears in that part.
- Notifications page (`GET /notifications`): one `CONTROL_WORSE` item per control, linking to it, and one
  `CONNECTOR_STALE` item per quiet source, linking to Connections. A control owner sees only the controls they own, as
  everywhere else; the page names controls and sources because it is the organisation's own view, not a chat message.

## Consequences
**Good:** the activation number exists from the day this ships and is read where the operator already looks; the checklist
cannot lie, because there is nothing to tick; "what changed this week" no longer needs a person to remember last week.
**Costs and limits:**
- History starts when this ships. The first weekly run writes a baseline, so the first report can only say what moved
  after it. Nothing is invented for earlier weeks.
- A lock by an auditor is recorded at the next evaluation or the weekly run, not the instant it happens, so its
  timestamp can be up to a week late; it still lands in the right week's figures.
- A control that is evaluated many times without its verdict moving writes nothing, so the table cannot be used to count
  evaluations.
- Quiet connectors use a fixed 14 days. Customer-run scripts are usually weekly, so that is one missed run plus slack; a
  per-connector schedule is a later change if customers run theirs less often.
- The checklist reads a few counts per page load of the Overview; they are indexed lookups on small tables.
