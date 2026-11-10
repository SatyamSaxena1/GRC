# ADR-056: A risk register where fixed rules score and a person signs

Status: accepted. Roadmap item 6. Applies ADR-004 (rules decide, a model only words things) and follows the shape of
ADR-042 (the vendor register).

## Context
ISO 27001 clause 6 and SOC 2 CC3 both expect a risk register: what could go wrong, how bad it is, what is being done,
who owns it and when it is next looked at. It was the largest module missing against Vanta, Drata and Secureframe. A
model-assigned score would break the rule the rest of the product follows, and a register that quietly rates its own
risks is the kind of thing an auditor asks about first.

## Decision
A `risks` table (additive migration `b3c4d5e6f7a8`, row level security enabled and forced in the same revision, same
policy as the other tenant tables) and `/risks` endpoints. Nothing is deleted: a risk is closed, never removed, so the
register and its audit trail stay whole.

**The score is a fixed rule** (`app/risks.py`): likelihood times impact, each 1 to 5, so 1 to 25. The band comes from the
score alone and is never stored:

| Score | Band | Reviewed every |
|---|---|---|
| 1 to 4 | Low | 365 days |
| 5 to 9 | Medium | 180 days |
| 10 to 16 | High | 90 days |
| 17 to 25 | Critical | 30 days |

These thresholds are our own baseline, sent by the server beside the data and drawn on the page, so the working is never
hidden. A client cannot send a score or a band: the endpoint has no such field.

**Two positions.** *Inherent* (before any treatment) is always kept. *Residual* (after treatment) is optional, and
must be stated as a pair, likelihood and impact together. A risk sits on the heat map at its residual position once one
is stated, otherwise at its inherent position. The page can show either view.

**Treatment** is one of mitigate, accept, transfer, avoid, or not yet decided (null, not a default, so the register
never claims a decision nobody made). **Status** is open, in treatment or closed.

**Review.** `next_review_date` is set from the band when the risk is added, unless the person gives one. A risk is
overdue when that date has passed and it is not closed; due soon within 14 days (shorter than the vendor register's 30,
because the critical cadence is itself 30 days). Recording a review needs a note of at least three words saying what was
checked, which becomes the reason on the audit event, and sets the next review from the current band. The date of an
open risk cannot be blanked, so an overdue flag cannot be dodged by clearing it.

**Who may do what** (`app/authorization.py::risk_scope`, `assert_may_change_risk`):

| Caller | Reads | Writes |
|---|---|---|
| Organisation admin | every risk | everything: add, edit, reassign owner, link controls |
| Compliance viewer | every risk | nothing |
| Control owner | only risks that name their email as owner | those risks, except owner and linked controls |
| Auditor, firm side, no organisation | refused (403) | refused |

A control owner asking for a risk that is not theirs is answered "not found" and the attempt is recorded, as for an
unassigned control. Linked controls must be the organisation's own; a control owner sees the name of a linked control
only if they could already see that control.

**A model may only draft wording.** `POST /risks/draft` takes a title and optional context and returns a description and a
treatment plan as text, through the existing tool gateway (`app/ingest.py::_tool_gateway`, with its fallback). The
function can return only those two strings, so it cannot set a score, a treatment or a status. It stores nothing. The page
shows the draft in a box marked as not yet part of the register, with the model's name, and a person chooses what to
copy into the form, edits it and saves. The saver is the signer: the audit event names them. Each draft request is
itself audited (title and model, not the text).

**Audit.** Adding, changing, closing, reviewing and drafting are each in the audit chain (`RISK_ADDED`, `RISK_UPDATED`,
`RISK_CLOSED`, `RISK_REVIEWED`, `RISK_DRAFTED`), with before and after state for changes. A change that alters nothing
writes nothing.

**Weekly report** (ADR-041). One line of counts, said only when the organisation has open risks: how many are open, how
many high or critical, how many reviews are overdue. No titles or owners: a risk's title can say what the organisation
is worried about, so it never goes in a chat post.

## Limits, stated plainly
- A single 5 by 5 matrix. There is no custom scale, no per-category appetite and no quantitative (money) estimate.
- Residual risk is the organisation's own statement. The product does not check that the linked controls actually reduce
  it; the link is a pointer to evidence the Controls page already holds.
- There is no separate sign-off step for accepting a risk. The person who saves "accept" is recorded in the audit chain;
  a second approver is a later change if a customer asks.
- Reviews are not yet in the daily attention list or notifications, only on the page and in the weekly report.

## Consequences
- ISO 27001 clause 6 and SOC 2 CC3 now have a register the organisation can show, with owners, dates and an audited
  history of every change.
- The heat map and the report read the same rules, so they cannot disagree.
- A tenant with no risks sees an empty page and no new line in its report.
