# ADR-063: Training: read, confirm, repeat every year

**Status:** Accepted
**Date:** 2026-11-12
**Deciders:** Platform owner

## Context
Staff awareness training is on every SOC 2 and ISO 27001 checklist (ISO A.6.3, SOC 2 CC1.4) and an auditor asks to see
who was trained and when. Competitor research (November 2026) found it is one of the modules that makes the leaders
sticky, because everyone in the company ends up using the product. We had no record of it: the policy library (ADR-056)
tracks who accepted a policy, but an acceptance never expires, and training has to repeat.

## Decision
- **Two tables, both under row level security:** `training_courses` (title, text, version, cycle in days, default 365)
  and `training_completions` (insert-only: person, version, day).
- **A person is DONE while their latest completion of the current version is newer than the cycle,** DUE_SOON in the last
  30 days, OVERDUE after it, NOT_DONE with none. The state is computed from the stored rows alone.
- **Editing the text makes a new version** that everyone completes again. Changing only the title or cycle does not.
  Completing a stale version is refused, so nobody confirms text that changed after they read it.
- **A statement, not a test.** The record shows a person was given the material and said they read and understood it.
  It does not claim they learned it.
- An organisation admin writes courses (two templates in our own words, to be read and adjusted); every member completes
  for themselves; an admin sees who is waiting, a member does not. Auditors do not see it (it is internal, like the
  policy library). Each addition, edit and completion is an audit event.
- The page points to it for the A.6.3 and CC1.4 attestations (ADR-060). It does not attest for anyone.

## Consequences
- The completion history is kept, so "who was trained, on which version, when" can always be answered.
- Not done: archiving a course, reminders before a completion lapses, adding people-by-role, and a weekly digest line for
  who is overdue. The overdue list is on the page for an admin.
