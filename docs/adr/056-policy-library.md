# ADR-056: A policy library with approval and each person's own acceptance

Status: accepted

## Context
SOC 2 and ISO 27001 both expect that people have read and accepted the organisation's policies, and every
competing tool tracks it. We had policy templates (ADR-038) but nowhere to keep the organisation's own text, no
record of who approved it, and no record of who accepted it.

## Decision
- **Three stored facts, nothing inferred:** the text of each policy, who approved the current version and when, and
  who accepted which version and when (`policy_docs`, `policy_acceptances`, both under forced row level security).
- **A change to the title or text is a new version.** It returns to draft, needs approval again, and everyone accepts
  it again. Earlier acceptances stay as history; the acceptance table is insert-only.
- **Who may do what:** an organisation admin writes, edits and approves. Every member of the organisation, including
  a read-only compliance viewer, reads approved policies and accepts for themselves. A draft is visible to admins only.
  An auditor does not see the library. The organisation's shared token is not a person and cannot accept.
- **Who is counted:** active members. A deactivated person stops counting, in both the total and the accepted figure.
  Only the admin sees the names still to accept.
- **Review date:** set to one year after approval; the page shows current, due soon (30 days) or overdue. Fixed rule,
  read from the stored date.
- **Templates:** a policy can start from any ADR-038 template, so its figures already meet every framework's rules.
- Every write is in the audit chain (`POLICY_ADDED`, `POLICY_EDITED`, `POLICY_APPROVED`, `POLICY_ACCEPTED`).

## Not done, on purpose
- Acceptance is **not yet evidence**: it does not feed any framework clause or verdict. Doing that means new clauses and
  a rules version, which a person must review (ADR-004).
- No reminders or emails to people who have not accepted, no file upload (text only), no per-group targeting,
  no e-signature beyond the signed-in identity.
