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
| Vendor risk, questionnaire answers | Open |
| AI help on the live site | **Working for demos** (model on a personal machine, reached through a tunnel; not for real use) |

Where we lead: the verdict comes from fixed rules, never from a model; a named human signs and locks; every
step is in a tamper-evident log; the DPDP Act pack for India.

## Entries

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
