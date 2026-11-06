# ADR-052: An email client, used first for a personalised welcome that a person answers

**Status:** Accepted
**Date:** 2026-11-05
**Deciders:** Platform owner (asked for it, naming BillionMail as the interim channel); a person who will read the replies.

## Context
GRC sends no email at all. People are invited, but the only help they get is whatever the admin tells them. The owner runs
BillionMail (a self-hosted mail server) and wants it to give "limited support" to people as they sign up, until a proper support
pipeline exists. Two things are true of the setup: BillionMail runs on the owner's computer while the live site runs on a hosted
service that cannot reach it, and a home mail server needs reachable ports, DNS records and a sending reputation before other
people's mail systems will accept its messages.

## Decision
A small email client, `app/mailer.py`, driven by standard SMTP settings, and one use of it: **a single welcome email, once, at
sign-up**, built by `app/welcome.py`.
- The email names the organisation, gives first steps for the person's **own role** (admin, control owner, viewer, firm admin,
  auditor), includes the one-time sign-in link when a login was just created, and says that **replying reaches a person**.
  Replies go to `SMTP_SUPPORT_REPLY_TO`, a mailbox someone actually reads (in BillionMail, a Roundcube mailbox).
- It is **deterministic**: fixed text per role. No model writes it and nothing in it comes from evidence.
- It is **limited on purpose**: sent only when a person is created, never as a reminder; no resend; nothing marketing; no
  attachments; plain text.
- When the email is sent, the admin never sees the sign-in link (ADR-047). If it cannot be sent, the link is returned to the
  admin so the invite is not lost, with an error class as the reason.
- The client is off until `SMTP_HOST` and `SMTP_FROM` are set. It never logs or returns a body, a password or a full address;
  a failure returns only an error class; addresses with spaces, brackets, commas or line breaks are refused so a caller cannot
  inject headers.

## Options Considered

### Option A: Generic SMTP client (chosen)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low: standard library only |
| Cost | None; works with BillionMail or any provider |
| Scalability | Fine for invitations |
| Team familiarity | High |

**Pros:** no tie to one product; swapping BillionMail for a hosted provider later is a settings change.
**Cons:** deliverability is the operator's job.

### Option B: BillionMail's own sending API
| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium: a second integration to keep current |
| Cost | None |
| Scalability | Tied to one product |
| Team familiarity | Low |

**Pros:** campaign features. **Cons:** locks the platform to one mail server and is no easier to reach from the live site.

### Option C: A hosted transactional email provider
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low |
| Cost | A paid or free-tier account, often needing billing details |
| Scalability | High |
| Team familiarity | Medium |

**Pros:** good deliverability. **Cons:** needs an account; the owner prefers the self-hosted route for now.

## Trade-off Analysis
Option A keeps the door open to B and C at no cost, so it wins on flexibility. Its weakness is where the mail server lives:
BillionMail on a home computer needs a reachable address, and mail from an unknown home IP is often rejected or filed as spam.
That is an operating constraint, not a code constraint, so it is documented rather than worked around.

## Consequences
- Easier: new people get role-specific first steps without the admin writing anything; one place for replies.
- Harder: someone must read the support mailbox, and mail must reach the live site's server.
- To revisit: when a real support pipeline exists, point `SMTP_SUPPORT_REPLY_TO` at it, or add a link instead of an address.
- Limit stated plainly: welcome text is generic per role. It does not know the person's evidence or tasks.

## Action Items
1. [x] `app/mailer.py`, `app/welcome.py`, invite flow, and the Admin page message.
2. [x] Guide `docs/operations/email.md` including how to point it at BillionMail.
3. [ ] Operator: reach BillionMail from the live site (a tunnel for TCP, or a public host), set the five SMTP settings.
4. [ ] Operator: set DNS records (SPF, DKIM, DMARC) for the sending domain before inviting real people.
5. [ ] Someone reads and answers the support mailbox.
