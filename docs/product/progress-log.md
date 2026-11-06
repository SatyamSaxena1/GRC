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
| In-app connector setup | **Started** (PR 77, ADR-044): team chat (Discord/Slack) done; evidence collectors still open |
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

### 5 Nov 2026: A personalised welcome email, and a person to answer it (interim support)
- **Say:** "When you invite someone, they get one welcome email with first steps for their own role and a way to reach a
  person. If their sign-in link is needed, it is in that email, so the admin never has to forward it."
- **Show:** Admin, invite a team member: the page says the welcome email was sent; open it: the organisation's name, five
  short first steps for their role, the one-time link, and "reply to this email". Reply and see it arrive in the support mailbox.
- **Honest detail:** it is fixed text per role, sent once, not a support desk. It works with any mail server, including
  BillionMail, but the live site must be able to reach that server and other mail systems must accept its mail (DNS records).
  Until the settings are added, nothing changes and the admin still sees the link.
- **Proof:** tests for each role's steps, the reply-to address, the link being emailed and never shown or stored, a failed
  send handing the link back, header-injection attempts, and exactly one email per sign-up.
### 5 Nov 2026: Show that leavers have lost access, without sending a single name (issue 79)
- **Say:** "Export two lists, the people who left and the accounts still active, and run one small script on your own
  computer. It counts the leavers who still have access and sends us only that number. No names or email addresses
  leave your computer."
- **Show:** Connections page, HR card: create the upload token, run the script with --dry-run --show to see which
  accounts to switch off, run it for real, and watch the leaver-access control update.
- **Honest detail:** it shows the two exports agree when they were exported, not that they are complete. An empty
  leavers list is marked incomplete unless you say nobody left. Evidence is as fresh as your last run.
- **Why this way:** there is no common HR system interface, and HR data is the most sensitive a customer holds, so
  nothing personal comes near us. That completes the evidence sources for the Connections page.
- **Proof:** tests for matching (case, spaces, repeats), only a number uploaded, the empty-list guard, the CSV
  errors, whole-number-only input, and a token for one source never working for another.

### 5 Nov 2026: Send Microsoft 365 evidence from your own tenant (issue 79)
- **Say:** "Run one small read-only script against your own Microsoft 365 tenant. It checks that every administrator
  has multi-factor authentication registered and that the audit log is recording, and sends us two yes/no answers. We
  hold no Microsoft credential of yours."
- **Show:** Connections page, Microsoft 365 card: create the upload token, run the script with --dry-run, then for real;
  the card shows when results arrived.
- **Honest detail:** it shows MFA is registered, not enforced, and that the Entra audit log is active, not the Purview
  setting. Evidence is as fresh as your last run. No Microsoft account or billing is needed on our side.
- **Also fixed:** the AWS card on the Connections page was looking for an old connection name and would not have
  appeared; it now does. The page now has a test that pins the list of connection kinds it expects.
- **Proof:** tests for both Graph checks, a missing permission, a token for one source never working for another, and the
  same token and size rules as AWS.

### 5 Nov 2026: Send AWS evidence from your own account (issue 79)
- **Say:** "You run one small read-only script in your own AWS account. It checks four things (encryption, MFA on
  admins, a logging trail, backups) and sends us only four yes/no answers. We hold no AWS key of yours."
- **Show:** Connections page, AWS card: create the upload token (shown once), run the script with --dry-run, then
  for real; the card shows when results arrived and the DPDP page shows the AWS evidence.
- **Honest detail:** evidence is as fresh as your last run; schedule the script if you want it regular. A check the
  permissions do not allow is left out and the run is marked incomplete, never a pass or a fail. Replacing the
  token ends the old one at once. The first design (we assume a role in your account) was dropped because it needed
  an AWS account with billing on our side.
- **Proof:** tests for the token (shown once, only its hash kept, one organisation cannot write to another), refusal of
  anything but four yes/no answers, rate and size limits, and each control failing on its own.

### 5 Nov 2026: Invite a person and they can actually sign in (issue 81, switched off until configured)
- **Say:** "Invite someone and they get a one-time link to choose their own password. Nobody, including the
  admin, ever sees or sets it. Deactivate them and their login is blocked too."
- **Show:** Admin, Invite a team member: create a user; a one-time link appears once with a Copy button. Deactivate
  the person on the team card and try to sign in.
- **Honest detail:** it is off until the operator adds the three Auth0 settings, so today nothing changes on the
  live site. The link is not stored anywhere and lasts seven days. If the sign-in service is down, the invite
  fails cleanly with no half-created person.
- **Proof:** tests with a stand-in sign-in service: off by default, random password, link shown once and absent
  from the audit trail, existing login reused, clean failure, block and unblock, failed block recorded.

### 4 Nov 2026: Your own GitHub evidence, tried live, and a way to accept a smaller scope (PRs 90, 91, this one)
- **Say:** "We connected a real GitHub token from the page. It collected 78 merges from the repository. It was
  held back as partial because a one-off earlier run had covered three repositories. A named admin can now accept
  the smaller scope with a reason, and the next collection is complete."
- **Show:** Connections card (token saved, access checked), then Collect evidence on the DPDP page: the card
  shows PARTIAL with the reason, the admin writes why, presses Accept, and it collects again and turns COMPLETE.
- **Found by trying it live:** reading review history takes minutes, so the button now runs it in the background;
  and the "fewer repositories" guard had no way out.
- **Honest detail:** only a smaller repository count can be accepted this way. Anything the collector itself
  reported as wrong cannot. Stored evidence is never edited; acceptance adds a run.
- **Proof:** tests for accepting, refusing a collector-flagged run, the reason, the role and the baseline.

### 4 Nov 2026: Connect your own GitHub from the Connections page (PR, part of issue 79)
- **Say:** "Paste a read-only GitHub token and name your repositories. We collect how code reaches production
  (reviews, checks, deployments) as evidence, with no server settings to edit."
- **Show:** Connections page, second card: token box (masked) and repositories box, Save, then Check access.
  Collect evidence on the DPDP page and see the change-control controls fill in.
- **Honest detail:** the server only ever calls api.github.com, so a customer cannot aim it elsewhere. If the
  saved token can no longer be read, the sync fails; it never borrows another organisation's collector. Self-hosted
  GitLab and Bitbucket still need the extra address-safety work and are not part of this step.
- **Proof:** tests cover bad input, write-only storage, no token in audit or errors, the access check's failure
  reasons, per-organisation isolation, and that a sync uses the organisation's own token and repositories.

### 4 Nov 2026: A tool to clean up old duplicate gaps (PR 88, closes issue 85)
- **Say:** "Gaps that an old bug duplicated can be cleaned up safely. We checked the live system and none exist,
  so nothing needed changing."
- **Show:** run `python -m app.gap_repair` (report only), then with `--apply` on a database that has duplicates.
- **Honest detail:** it never deletes. The earliest gap stays open, the copies are marked closed with a reason
  naming the one kept, and each closure is in the audit log. It is safe to run twice.
- **Proof:** tests for report-only, apply, no deletion, audit event, second run, and task handling; a read-only
  count on the live database found zero duplicate groups.

### 4 Nov 2026: Overdue vendor reviews show up in the daily list (PR 86, closes issue 83)
- **Say:** "A vendor whose review is overdue, or was never done, now appears in the same daily list as expiring
  evidence and breach deadlines, with a link straight to the Vendors page."
- **Show:** add a vendor and leave it unreviewed: it shows in the notifications list. Record a review and it
  disappears. Offboard a vendor and it never appears.
- **Honest detail:** in chat the list is one counted line ("1 vendor review(s) overdue or never done"), never a
  vendor's name, because the name says who you buy from. Reviews due within 30 days stay on the Vendors page and
  in the Monday summary, so the daily list is not noisy.
- **Proof:** tests cover listed, reviewed, offboarded, and the names-versus-count difference; the weekly report
  and daily list share one helper so their numbers cannot disagree.

### 4 Nov 2026: Connect your team chat yourself, no server settings (PR 77)
- **Say:** "Open Connections, paste your Discord or Slack webhook address, press Save, then Send a test
  message. From then on your alerts and the Monday summary go to your own channel. What you paste is stored
  scrambled and is never shown again."
- **Show:** Connections page (org admin only): the address box is masked while you paste; after Save it shows
  only "discord.com ...xxxx" and a status. Press the test button and the message appears in the channel.
  Then assign a task and watch the alert arrive.
- **Honest detail:** only Discord and Slack addresses are accepted. If the stored address ever cannot be
  read, nothing is sent, and it never falls back to the shared server channel. The "task assigned" alert still
  names the person, so use a channel only your own team reads.
- **Proof:** the old server-wide webhook setting was deleted from Render and GitHub, the site redeployed, and
  an assignment still produced the alert, so it came through the saved connection. The audit log records
  who set, tested or removed it, never the address. 35 tests cover validation, encryption and routing.

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
