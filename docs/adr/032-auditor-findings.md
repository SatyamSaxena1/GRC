# ADR-032: Auditor findings on a control

> **Status:** Proposed. Implemented: `app/routers/findings.py`, model `Finding`, migration
> `e6f7a8b9c0d1` (under RLS from the start), a Findings tab on the control page,
> `tests/test_findings.py`.

## Context
An auditor could record a verdict and a one-line remark, but had nowhere to say "this is wrong, and
here is why" in a form the auditee could answer and the auditor could close. Disagreements lived in
the discussion thread, mixed with comments, with no status and no way to count what was still open.

## Decision
A finding belongs to one control in one organisation and has a lifecycle:

`OPEN` (an auditor raised it) -> `RESPONDED` (the auditee answered) -> `CLOSED` (an auditor closed
it, with a note) -> back to `OPEN` if an auditor reopens it, with a reason.

- **Who.** Only an auditor under an engagement raises, closes and reopens. Only a writer on the
  auditee side answers: an organisation admin, or a control owner assigned to that control. A
  compliance viewer cannot. An auditor cannot answer their own finding.
- **Specific or refused.** Description, response, closing note and reopening reason each need at
  least 3 words and 15 characters; "ok" is refused (the same bar as an override reason, ADR-029).
- **Visibility follows the control.** An auditor sees findings only on controls their engagement
  covers; the auditee sees findings on controls they may see; another organisation sees nothing.
- **Audited.** Every transition is an audit event (`FINDING_RAISED`, `_RESPONDED`, `_CLOSED`,
  `_REOPENED`) with before and after state and the reason. The row holds the current state; the
  trail holds the history, so an earlier response or closing note is never lost.
- **Notices.** Raising a finding sends a content-free webhook notice if one is configured (ADR-031):
  severity, framework and clause, never the title or text.

## Trade-offs
- The row keeps only the latest response and closing note. The earlier ones are in the audit trail,
  not on the finding itself.
- A finding is on a control, not a piece of evidence or a verdict, because that is the unit the
  auditee owns and the auditor reviews. Findings about a single document would need a second
  anchor.
- No second reviewer: one auditor can raise and close their own finding.

## Not covered
Findings in the OSCAL export, an organisation-wide findings screen (the API has `GET /findings`),
attachments, due dates and escalation, and a required second reviewer to close a high-severity
finding.
