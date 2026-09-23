# How this website works (plain-language guide)

This is a compliance evidence tracker. You upload a document (like a password policy or a
vulnerability scan report), and the site automatically checks it against every compliance
framework you're signed up for (ISO 27001, PCI DSS, SOC 2, HIPAA, GDPR, etc.), tells you
exactly what's missing, tracks the fix, and lets a human auditor sign off and lock the result
so it can't be quietly changed afterward.

**Live demo link:** https://critter-kindness-wand.ngrok-free.dev
(This is a temporary tunnel to a copy running on this machine — it goes away when the
tunnel/server is stopped. Not for real data.)

---

## 1. Signing in

There's no username/password account system yet — you sign in with an "identity" instead.
Go to `/login` and pick a tab:

- **Quick start** — the easiest way to try it. Type an organisation name, an audit firm name,
  tick which frameworks you want, and press **Create organisation & engagement**. This makes
  a demo company for you in one click. Then press **Enter workspace**.
- **Organisation** — already have an organisation ID? Paste it in and sign in as that
  company's admin.
- **Control owner** — paste a user ID to sign in as someone responsible for specific controls
  (e.g. "make sure the password policy is uploaded").
- **Compliance viewer** — paste a user ID to sign in as someone who can look at everything but
  change nothing.
- **Auditor** — paste an "engagement ID" to sign in as the outside auditor reviewing one
  client.
- **Audit firm** — press **Create firm & sign in as its admin** to run the audit-firm side
  (the people who onboard and staff auditors onto clients).
- **Request an audit** — a form a prospective client fills out to ask an audit firm to take
  them on. Doesn't create an account by itself — the firm has to approve it first.

Which of these you sign in as decides which menu items you see everywhere else — the site
also double-checks on its own server, so the menu isn't the only thing stopping someone from
seeing data they shouldn't.

---

## 2. The main journey (what actually happens, step by step)

1. **Upload a document** — go to **Evidence**, choose what kind of document it is (policy,
   scan report, certificate, screenshot, etc.), pick the file, and press **Upload**.
2. **The site reads it automatically** — in the background it scans the file, pulls out the
   relevant facts (e.g. "minimum password length: 8 characters", found on page 6), and checks
   those facts against the rules of every framework you're subscribed to. You can watch this
   happen live on the evidence's page (scanning → reading → extracting → evaluating).
3. **Each framework gets a verdict** — pass, partial, or fail — for that document, shown right
   there with the exact page/quote it came from.
4. **Anything that fails opens a "gap"** — a plain-English note of exactly what's wrong (e.g.
   "password_min_length is 8, PCI DSS requires 12"), and a matching to-do task gets created
   automatically.
5. **Fix it** — go back to the evidence item and press **Upload revised version**. The site
   re-checks the new file automatically. If it now passes, the gap and its task close by
   themselves — nobody has to manually tick them off.
6. **Submit for review** — on the control's page, press **Submit for auditor review** once
   you think the evidence is solid.
7. **Auditor signs off** — someone signed in as the auditor opens the **Auditor review** tab,
   picks a verdict (compliant / partially compliant / non-compliant), and presses **Lock**.
   (Note: whoever uploaded the evidence can't also be the one who signs off on it — that's
   blocked on purpose.)
8. **Locked = frozen** — once locked, the company's side can no longer edit, delete, or
   replace that evidence. If they need a change, they have to press **Request unlock** and
   the auditor decides.

---

## 3. What each page does

**Overview** — the homepage after signing in. Shows counters (controls tracked, open gaps,
open tasks, evidence ready), what needs attention right now, and how much duplicate-upload
work you've avoided by reusing the same evidence across frameworks. Press **Download
compliance report** to get a CSV/Excel export. Everything else here is a link that jumps you
to the relevant page.

**Evidence** — where you upload documents (see step 1 above) and see the list of everything
uploaded, grouped by type, each with a status badge (processing / ready / failed / needs
review). Press a row to open it. If something failed, press **Retry** to re-run the check
without re-uploading.

**Evidence detail** (click any evidence row) — the deep-dive page for one document: what was
extracted from it, the verdict per framework, its version history. Press **Edit** to change
its description or expiry date, **Upload revised version** to replace it with a corrected
file, or **Remove** to delete it (locked evidence can't be removed).

**Controls** — one row per compliance requirement (a "clause"), showing its current verdict
and whether it's locked. Press a row to open it.

**Control detail** — everything about one requirement: which evidence backs it, a progress
tracker (collected → evaluated → submitted → reviewed → locked), a comment thread, and (for
auditors) the actual review controls — recording a verdict and locking/unlocking. Press
**Submit for auditor review** when ready, or type in the **Discussion** tab to leave a note
or ask a question.

**Gaps** — a table of everything currently failing, with the exact value found vs. the value
required. Filter by status, or press **Export** to download the filtered list. There's no
manual "fix" button here — you fix it by uploading corrected evidence.

**Tasks** — your to-do list. Org admins can press **Assign a task** to hand someone a manual
to-do (e.g. "get this policy signed"); control owners just see their own list. Click a task
to open its details, change its due date/priority, or mark it done. Tasks created from a gap
close themselves automatically when the gap is fixed.

**Firm** (audit-firm staff only) — approve or reject companies asking to be audited, assign
which auditors work which client, and press **Open this client** to step into their review
queue.

**Admin** (org admin only) — basic setup forms: invite a team member, manually register a
control, assign a control to someone, or close out an engagement.

**Activity** — a read-only timeline of every action anyone has taken, newest first.

**Notifications** — a combined list of everything currently open (tasks, requests from the
auditor, evidence quietly going stale). Click any row to jump straight to it.

**Glossary** — a searchable dictionary of the compliance terms used across the site.

**AI compliance** — a dedicated page for AI-governance readiness (NIST AI RMF), with its own
score, gaps, and reference material.

**DPDP readiness** — a page for India's data-protection law (DPDP Act) readiness, including
buttons to auto-pull evidence from connected systems (AWS, Microsoft 365, Google Workspace,
HR system) by pressing **Collect evidence** on each one.

---

## 4. Who can do what (the five roles)

| Role | Can see | Can do |
|---|---|---|
| **Org admin** | Everything in their own company | Upload evidence, invite users, assign controls, everything |
| **Control owner** | Only the controls assigned to them | Upload/manage evidence for their own controls |
| **Compliance viewer** | Everything in their own company | Look only — no uploads, no edits |
| **Auditor** | Only clients they're staffed on | Review evidence, record verdicts, lock/unlock — can't upload evidence themselves |
| **Firm admin** | Their whole client book | Approve new clients, assign auditors to them |

The rules are enforced on the server, not just hidden in the menu — so even if someone
guessed a URL, they'd still be blocked from data or actions outside their role.
