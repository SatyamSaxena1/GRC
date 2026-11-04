# Progress log (for video and write-ups)

One entry per step that changed what a person can do or see. Each has the plain-words line, what to show
on screen, and where the proof is. Add to the top. Say only what the live site does today.

## Where we stand against other compliance tools

| Gap named in the comparison | Status |
|---|---|
| Duplicate entries from double clicks | **Fixed** (PR 50) |
| Actions still shown on a locked control | **Fixed** (PR 50) |
| Switching role silently returned the old user | **Fixed** (PR 49) |
| Firm admin could not open a client | **Fixed** (PR 51) |
| Users page: see team, change roles, switch someone off | **Done** (PR 52, ADR-036) |
| Controls page fed by every source, not only GitHub | **Done** (PR 56, ADR-037): 3 controls became 11 |
| In-app connector setup | Open (needs a design for stored secrets first) |
| Fuller framework catalogue | Open |
| Policy templates | **Started** (PR 58, ADR-038): three templates whose figures come from the rules |
| Trust page | **Done** (PR 60/61, ADR-039): opt-in, counts only, revocable |
| Questionnaire answers | **Done** (PR 63, 64, ADR-040): status from verdicts, model only words it |
| Weekly report | **Done** (PR 66, 73; ADR-041): counts only, vendor reviews included, posts to Discord on Mondays |
| Vendor risk | **Done for v1** (PR 68, 71; ADR-042, 043): register, rule-decided tier, review dates, reports as proof |
| AI help on the live site | **Working for demos** (model on a personal machine, reached through a tunnel; not for real use) |

Where we lead: the verdict comes from fixed rules, never from a model; a named human signs and locks; every
step is in a tamper-evident log; the DPDP Act pack for India.

## Entries

### 4 Nov 2026: The weekly report and live alerts arrive in Discord (PR 66, 73, 74, 75)
- **Say:** "Every Monday, and the moment something happens, your team gets a short message in the channel
  they already read: where compliance stands, what changed, which vendor reviews are due, or that a task
  was just assigned."
- **Show:** the Discord channel with the weekly summary, then assign a task in the app and watch the alert
  appear a few seconds later in the channel.
- **Honest detail:** the weekly summary is numbers only. The instant "task assigned" alert does include the
  assignee's email address and the task's title, so keep that channel to your own team.
- **Fixed on the way:** the scheduled jobs had failed for days because their copy of the database address
  still pointed at the old database. They now reach the live one. The manual run button now runs one chosen
  job instead of everything.
- **Proof:** a real run posted "webhook: 1 report(s) sent" and the message appeared; a real assignment
  produced the alert; the task was then put back as it was.

### 4 Nov 2026: A vendor's security report is the proof (PR 71)
- **Say:** "Don't just tick a box that says the vendor is certified. Attach their security report. It counts
  only until the date it expires, and the vendor's risk level updates by itself when it runs out."
- **Show:** Vendors page, Reports on a vendor: attach a SOC 2 report with its valid-until date; the vendor
  now reads "report, valid to ...". Attach an expired one and see it kept but marked "does not count".
  Open a report to download it.
- **Honest detail:** the expiry date is the one you type in; the platform checks it has not passed, it does
  not read the report to confirm it. A report cannot be deleted, so a wrong file stays on the record.
- **Proof:** tests cover each report type and expiry boundary, upload checks, duplicate files, download-only
  delivery, and who may see what. An automated review caught a real flaw before release: a half-filled form
  could have attached one vendor's file to another, which is permanent, so the form now resets and refuses.

### 4 Nov 2026: Know your vendors, and when each is due (PR 68)
- **Say:** "List the companies you depend on. Each gets a risk level from simple rules you can read:
  what data they can reach, how much you rely on them, and whether they have a security report on file.
  The level decides how often you must review them, and the page tells you who is overdue."
- **Show:** Vendors page. Add a payments provider (sensitive data, high dependence): tier High, never
  reviewed. Tick "report on file" and watch the points drop. Press Mark reviewed, type what you checked,
  and the due date appears.
- **Honest detail:** a review needs a few words about what was checked, and every change is in the activity
  log. It does not store the vendor's report yet, and overdue reviews are not yet in the weekly summary.
- **Proof:** tests pin every tier boundary and every review state; the table is locked to each
  organisation in the database itself.

### 3 Nov 2026: A weekly report that writes itself (PR 66)
- **Say:** "Every Monday, one short message tells your team where compliance stands and what changed:
  how many controls are met, how many gaps were raised and closed, what was collected, what an auditor
  locked. It contains numbers only, so it is safe in a shared chat."
- **Show:** Admin page, Weekly report card: the sentence, then Download. Point at "this week: new gaps,
  resolved, evidence collected, controls locked".
- **Honest detail:** posting to Slack or Discord needs one setting, a webhook address. Until it is set the
  report is read and downloaded in the app. It does not say how many tasks were finished, because tasks
  do not yet record when they were closed.
- **Proof:** tests check the counts follow the seven-day window, that no file name or email appears, and
  that running it twice in a week sends one message.

### 3 Nov 2026: Answer a customer's security questionnaire (PR 63, 64)
- **Say:** "Paste the customer's questions. Each one is answered from your own controls, with the controls
  named beside it. The Yes or No is decided by your verdicts, never by the AI. If you have no evidence, it
  says so instead of guessing."
- **Show:** Questionnaires page. Paste: multi-factor authentication for remote access, audit logs,
  leavers, and one silly question (pets in the office). Watch answers appear one by one: Yes with the
  PCI control that backs it, Partly for logging, Not yet evidenced for the silly one. Download the CSV.
- **Honest detail:** these are drafts for a person to review. A question phrased oddly may miss and read as
  not evidenced, which is the safe way to be wrong.
- **Found by trying it live:** the first version never used the AI because the model server refused one
  request format, and a stray word like "access" pulled in unrelated controls and lowered a Yes to Partly.
  Both are fixed and tested against the real model.

### 3 Nov 2026: A trust page you control (PR 60, 61)
- **Say:** "Customers ask how you handle security. Publish one link that shows the facts, and take it down
  whenever you like. It shows numbers only: no files, no gaps, no names."
- **Show:** Admin page, Trust page card: the exact preview first, then Publish. Open the link in a private
  window with no sign-in: controls tracked, how many meet requirements, how many an auditor has locked,
  each framework's progress. Press Unpublish and reload the link: it no longer works.
- **Honest detail:** it is off until someone publishes it, and the link is a long random address, so only
  people you send it to can open it. The page is marked so search engines skip it.
- **Proof:** tests check that a planted file name, its text, the words "gap" and "task", and the link
  itself never appear in what the public receives.
- **A mistake worth knowing about:** the first release failed to start because a database change reused an
  old reference number. The old version kept running and no data was touched. A new check now stops that
  before release.

### 3 Nov 2026: Policy templates that meet the rules (PR 58)
- **Say:** "No policy yet? Start from a template. The numbers in it are not guesses: each one is the
  strictest figure any framework asks for, so a policy written from it passes."
- **Show:** Evidence page, under the file picker: three template buttons. Download the password policy and
  point at "at least 14 characters" and multi-factor for administrative and remote access. Fill in the
  blank dates, upload it, and watch the controls pick it up.
- **Honest detail:** the figure is 14, not the 12 most people expect, because one framework asks for 14.
  If a framework changes its rule, the template changes with it.
- **Proof:** every figure is checked by the same checker the platform uses on real documents.

### 3 Nov 2026: One piece of evidence, many controls (PR 56)
- **Say:** "The same AWS, Microsoft 365 and HR evidence now counts toward ISO 27001, SOC 2 and PCI DSS as well
  as the Indian DPDP Act. Collect once, see every framework move."
- **Show:** Controls page before and after pressing Collect evidence on the three sources: 3 controls become
  11, with a mix of Pass and Partial. Open one: its evidence is the same file seen on the DPDP page.
- **Honest detail:** a check that shows only one side of a clause is marked Partial and can never read as a
  full pass. A clause no snapshot covers is simply left out.
- **Side effect to know:** a workspace that has not collected from any source now shows lower PCI readiness,
  because four connector-based clauses count as not yet evidenced.

### 3 Nov 2026: AI help works on the live site
- **Say:** "Ask a question about any gap and the assistant explains it in plain words, using only what is
  already in the workspace. The decision still comes from fixed rules, never from the assistant."
- **Show:** Gaps page. The sidebar light reads "Model connected". Press Explain on a gap. After a short
  wait the answer says what is missing, why it matters, and what the policy should state.
- **Be honest on screen:** the first answer takes around 20 seconds. The model runs on a separate machine
  for the demo. If it is switched off the buttons say so and nothing else breaks.
- **Proof:** the live health check reports the model as available.

### 3 Nov 2026: Switch someone off without losing their history (PR 52)
- **Say:** "An admin can now see everyone who has access, change a role, or switch a person off. They lose
  access straight away, and everything they did stays on record under their name."
- **Show:** Admin page, Team card. Change a role from the drop-down. Press Deactivate on a spare account;
  that person is signed out on their next click. Press Reactivate.
- **Also true:** the last admin can't be removed, nobody can switch themselves off, and every change is in
  the activity log with the before and after.
- **Proof:** 9 new tests; live database checked after release, all 5 users still active.
- **Tried on the live site as the org admin:** invited a spare account (no organisation id needed), changed
  its role, deactivated it (the button turned to Reactivate), and tried to deactivate the admin's own
  account, which was refused with "you cannot deactivate your own account". After an invite the list now
  updates by itself.

### 3 Nov 2026: A firm can open a client (PR 51)
- **Say:** "A firm admin opens any client they audit from one console, with the live numbers beside it."
- **Show:** Firm console: client card with controls, locked, open gaps, staffed auditor. Press Open this
  client. The Controls page loads with the client's locked control.
- **Found by:** testing the live site as the firm admin. The button did nothing for people who sign in
  through the company login.

### 3 Nov 2026: Cleaner sign-off and a clearer lock (PR 50)
- **Say:** "Submitting for review records once, however many times you click. A closed control shows no
  actions that can't apply."
- **Show:** the control page as the client (banner: closed by the auditor, read-only); the auditor's
  "Record verdict and lock" button.
- **Found by:** the audit history showed four "submitted" entries from one click.

### 3 Nov 2026: Signing out really signs you out (PR 49)
- **Say:** "Switch between client, auditor and firm on the same computer, with a password check each time."
- **Show:** Sign out, pick Auditor, type the password, land on the auditor's review queue.

### 3 Nov 2026: Evidence from four systems, stored safely
- **Say:** "One press collects evidence from AWS, Microsoft 365, the HR system and GitHub. Each source says
  whether it finished or only partly worked, and a partial run is never treated as a pass."
- **Show:** DPDP readiness: four cards turn READY and COMPLETE, the score moves from 0% to 22%, AWS shows
  PARTIAL. Gaps page: exact value found next to the value needed.
- **Fixed on the way:** stored evidence now goes to a private bucket on the new database project.

### 3 Nov 2026: The auditor's sign-off, end to end
- **Say:** "The client submits. The auditor reviews, records a decision with a reason, and the control
  locks. The rules said partial; the auditor's different decision needs a written reason, and both stay on
  record."
- **Show:** control page as client, then as auditor (reason box required before the button works), then the
  History tab with the auditor's reason, then the client's read-only view.
- **Proof:** history shows VERDICT_REGISTERED with the reason, the person and the time.

## Scenes still to film
- Team card with Deactivate/Reactivate (needs an org admin session).
- AI help (Explain, Ask AI) once the model has a stable address.
- The Controls page with more than three controls, once every source feeds it.
