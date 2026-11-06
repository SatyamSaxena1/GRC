# Email and the welcome message (ADR-052)

GRC sends one email: a personalised welcome when someone is invited. It needs any SMTP server, such as BillionMail.

## Settings (server-side, in the Render `grc-secrets` group)
| Name | Meaning |
|---|---|
| `SMTP_HOST` | the mail server's address |
| `SMTP_PORT` | default 587 |
| `SMTP_SECURITY` | `starttls` (default), `ssl` (port 465) or `none` |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | the sending mailbox's login (enter the password yourself, never in chat) |
| `SMTP_FROM` | e.g. `GRC <no-reply@yourdomain.com>` |
| `SMTP_SUPPORT_REPLY_TO` | the mailbox a person reads; replies go here (optional but recommended) |

Email stays off until `SMTP_HOST` and `SMTP_FROM` are both set. Until then, inviting someone shows the sign-in link to the admin.

## Using BillionMail
1. In BillionMail, add your sending domain, create a mailbox for sending (for example `no-reply@`) and one a person will read
   (for example `support@`). Set the support mailbox in `SMTP_SUPPORT_REPLY_TO`.
2. **The live site must be able to reach it.** BillionMail running on your own computer is not reachable from the hosted
   site. Either expose the SMTP submission port (587) through a TCP tunnel or run BillionMail on a host with a public address.
3. **Mail must be accepted by other people's systems.** Set the DNS records BillionMail shows you for the domain (SPF, DKIM,
   DMARC) and a reverse DNS name for the sending address. Many home internet providers block port 25 and many mail systems
   reject mail from home addresses, so test with a second mailbox first.
4. Invite a test person (a plus-address of your own) and check the message arrives, is not in spam, and that replying reaches
   the support mailbox.

## What the welcome email says
First steps for the person's role, the organisation's name, the one-time sign-in link when a login was just created (valid
seven days), and "reply to this email and a person will help you". It is fixed text, sent once at sign-up, never as a reminder.

## What it never does
Log or return a message body, a password or a full address; send marketing; attach files; or resend. A failed send returns
only an error class and gives the admin the link instead.
