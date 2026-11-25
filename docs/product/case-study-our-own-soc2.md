# Case study: getting ourselves ready for a SOC 2 audit, using our own product

Written 12 Nov 2026 and updated 25 Nov 2026, from what actually happened. It is meant to be read by a person, and to be cut
into a video (section 6). Where something is not done yet, it says so. Update the "where we are" table when that changes.

## 1. The story in one paragraph

A small software company wants to sell to bigger buyers, and the buyers ask for a SOC 2 report. The company has no
compliance team. It uses its own product to see what is missing, write its policies, say what is true, and keep the
proof in one place, so that when an independent audit firm arrives, the answers are already written down. We are that
company, and the product is the one we sell. The most useful thing that happened is that the product's own checks
**contradicted** something we had written, and then the company corrected the statement instead of the evidence.

## 2. Who does what in a regular audit

| Step | Who does it | What it means |
|---|---|---|
| 1. Scope | The owner | Which criteria (we suggest Security only), and Type 1 (one day) or Type 2 (a stretch of months) |
| 2. Readiness check | The company, a consultant, or a tool | A list of what is missing, before anyone is paid to test |
| 3. Policies and controls | The company | Write the rules, approve them, and put the controls in place |
| 4. Evidence | The company | Keep proof that the rules are followed: logs, scans, records, training |
| 5. Choose the auditor | The owner | An independent, licensed accounting firm. They cannot write your policies |
| 6. Audit work | **The auditor** | They test the controls, sample the evidence and interview people |
| 7. Report | The auditor | A draft, the company's replies, then the final report |
| 8. Repeat | Both | Every year |

The company does the work. The auditor checks it. Our product helps with steps 3 and 4.

## 3. Where we are (25 Nov 2026)

| Step | Status |
|---|---|
| 1. Scope | **Not decided.** Suggested: Security criteria only, Type 1 first |
| 2. Readiness check | **Done** (docs/product/soc2-readiness.md) |
| 3. Policies and controls | **Mostly done.** All five policies are approved; four are also accepted by the owner and Access Control still needs that click. Two statements are attested (ISO A.8.25 and A.8.29), each corrected once after the evidence disagreed. Seven suppliers and eight risks are recorded |
| 4. Evidence | **Started.** The GitHub change-control collection runs through a one-click App on our repository only and has a real verdict (partial). Weekly package scans, code scanning, and secret scanning run. Multi-factor, backup and restore, and log evidence are still missing |
| 5. Choose the auditor | **Not started** |
| 6 to 8 | Not started |

## 4. What we did, scene by scene

**Scene 1: Look at ourselves honestly (readiness check).**
We ran the product against an empty organisation and read the live site. It showed what we have (reviewed changes, a
tamper-evident audit log) and what we lack (no tested restore, no stated backups, logs lost on every deploy, multi-factor
sign-in unchecked). Nothing was hidden to look better. *On screen: the readiness table.*

**Scene 2: Fix what is cheap, now.**
Four fixes the same week: safety headers on the website, a limit on guessing the operator key, a weekly scan of the
software parts we use (with a bot that proposes updates), and a browser safety rule set to "report only" so it cannot
break anything. Then the public list of API routes was switched off in production. *On screen: the weekly scan going
green; before and after of the route list.*

**Scene 3: Make our own organisation in the product.**
We created "GRC Platform (our own company)" with SOC 2, ISO 27001 and DPDP, and one administrator. *On screen: the new
organisation with every clause showing "no evidence", all red. This is the honest starting point.* (Shot 04.)

**Scene 4: Write the policies, and approve them.**
Five policy templates were added as drafts (access, passwords, encryption, incident response, data retention). Their
numbers come from the framework rules, not from guesswork. We filled in the company name, the approver's role, and what
"in scope" means for us, and added a real retention schedule that the template lacked. The owner then read each one and
approved it. The product refuses to let anyone approve text that changed after they read it. *On screen: five drafts, then
five approved.* (Shots 03 and 08.)

**Scene 5: Check what the policy promises, then say only what is true.**
The Password policy promised multi-factor sign-in for administrators, so the owner checked each service. GitHub was on;
Render was off and was switched on; Supabase is reached only through GitHub; and the product's own sign-in service had
**no multi-factor at all**. The policy was reworded to state that gap openly and a risk was recorded. *On screen: the
Password policy's "status at approval" section.*

**Scene 6: Attest, then let the evidence disagree.**
Two clauses were attested by a named person: secure development and security testing. The product records who said it
and until when (one year at most), and shows it as "attested", never "passed", because a statement is not a test.
*On screen: the clause turning from "no evidence" to "attested", with the wording.* (Shots 05, 07 and 11.)

**Scene 7: Real evidence arrives, and it is not flattering.**
GitHub was connected, first with a hand-made token and then with a one-click App limited to our one repository. The
product read every merge in the last 90 days and judged them against the change-management rules: **124 merges with no
independent approval**, 75 direct pushes, 17 merges with missing or failing checks. Change management, which we had
called our strongest area, came out **partial**. *On screen: the collection finishing, then the gap list.* (Shots 12 and 09.)

**Scene 8: Correct the statement, not the evidence.**
The first attestation said every change was a pull request. The evidence showed 74 direct pushes until 4 Nov 2026. The
owner withdrew it and attested a true version: "since 5 Nov, every change is a pull request; before that, some were
pushed directly; a second independent reviewer is not yet in place." A rule was added on the main branch so nobody can
push straight to it. *On screen: the old and the new wording side by side.* (Shot 11.)

**Scene 9: The tooling finds a real hole.**
Switching on GitHub's free code scanner (CodeQL) produced six alerts on its first run. One was real: an address with
encoded dots could make the web-app file server return a file from outside its folder. It was reproduced on a local copy,
fixed, tested (the new tests fail on the old code), and merged the same day, along with the other five. The security
attestation was then reworded to include all of this. *On screen: the alerts, the fix, then zero open alerts.*

**Scene 10: Leave the remaining gaps visible.**
Backups with a tested restore, durable logs, product sign-in multi-factor and background checks stay open, as eight
real risks with owners and review dates. An honest open gap is better than a statement that falls apart. (Shot 10.)

## 5. What went wrong, and what we learned

- **A statement was filed under the wrong control.** Two attest forms were open at once and the second landed on the
  wrong clause (A.8.30, not A.8.29). It was caught by reading the final list, withdrawn (kept in the history as
  withdrawn) and filed again, one form at a time. Lesson: check the result, not the click.
- **Our own attestation overstated.** "Every change is a pull request" was contradicted by the evidence. The statement
  was corrected. Lesson: a statement and a test are different, and the test wins.
- **The invite failed for our own administrator.** The sign-in service already had a login for that email that could not
  be sent a password link, so the invite stopped with a vague "502". We worked around it with a variant of the address
  and then fixed the product (PR 142). Lesson: found by using the product ourselves.
- **Connecting GitHub took several tries.** The private key pasted into the host's settings lost its line breaks; GitHub's
  install page defaults to "All repositories", which would have shared ten repositories instead of one; and its Uninstall
  button needs a browser pop-up. The product now accepts a mangled key, says in words why an install failed, and has a
  "Check the App settings" button. Lesson: the first real run is the real test.
- **Sign-in screens remembered the wrong account.** Auth0 kept offering an old test account's address, and the pane got
  signed in as the wrong organisation once. Nothing was harmed. Lesson: read the email field before typing a password.
- **A policy cannot be approved while it has blanks.** The templates had placeholders such as "[your organisation]". They
  were filled before approval.
- **A broken email check was found by a new test.** While fixing a slow-pattern alert, a test showed an address ending in
  a line break was accepted. It is now refused, because a line break can inject email headers.

## 6. Video outline (about 6 minutes, plain words)

1. **Hook (0:20).** "A buyer asks for a SOC 2 report. You have no compliance team. What now?"
2. **Who does what (0:40).** The step table in section 2, drawn as a simple lane diagram: you, the product, the auditor.
3. **Honest start (0:40).** Scenes 1 and 3: everything red.
4. **Write and approve (0:50).** Scenes 4 and 5: five policies approved, and the MFA check that found a real gap.
5. **The twist (1:30).** Scenes 6 to 8: a statement the evidence contradicted, and the owner correcting the statement.
6. **A real hole (0:50).** Scene 9: the free scanner finds a path-traversal flaw, fixed the same day.
7. **What the auditor does (0:30).** They test, they do not write. The evidence is ready.
8. **Close (0:40).** Where we are: five policies approved, real evidence flowing, eight honest risks. "Here is what happens next."

**Do not show on screen:** the operator key, any password, reset link, private key or client secret, the other test
accounts' email addresses, the Auth0, Render, Supabase or GitHub dashboards, or the database. Use our own organisation
only, never customer data. Crop the sign-in panel in shots 07 and 11.

## 7. What a viewer should take away

1. Compliance is mostly writing down true things and keeping proof, not buying a tool.
2. A statement and a test are different, and a good product labels them differently.
3. When they disagree, you fix the statement, not the evidence.
4. An honest gap list is better than a clean-looking one.
5. The independent auditor comes last, and the work is already done when they arrive.

## 8. What this case study does not claim

- We have **not** started an audit, chosen an audit firm, or been certified. No report exists.
- Multi-factor sign-in for the product itself is **not enabled**; the policy says so.
- Change management is **partial**: there is no independent reviewer, and the older numbers will only fall as old months
  leave the 90-day window.
- The product helps organise the work. It does not make a company compliant by itself.

## 9. Screenshots

Stored in `docs/product/case-study-shots/`, 800 by 500 pixels, taken on 12 and 25 Nov 2026 from our own organisation.
They are good for a storyboard; record the screen at full size for the final video.

| File | Shows |
|---|---|
| 01-risk-register.jpg | Heat map and the first six risks (12 Nov) |
| 02-vendor-register.jpg | The seven suppliers and their tiers |
| 03-policies-draft.jpg | Five policies at version 2, all drafts (12 Nov) |
| 04-frameworks-overview.jpg | The framework cards, all near zero |
| 05-iso-27001-attested-count.jpg | ISO 27001 "2 attested" |
| 06-connections-github-not-connected.jpg | The GitHub box, not connected (12 Nov) |
| 07-iso-27001-two-attested-clauses.jpg | The **first** wording of two attestations, before the evidence disagreed |
| 08-policies-all-approved.jpg | All five policies approved (25 Nov) |
| 09-gaps-real-findings.jpg | The real change-management gaps from the GitHub collection |
| 10-risk-register-eight.jpg | The heat map and eight risks |
| 11-iso-attestations-corrected.jpg | The **corrected** wording of both attestations |
| 12-github-collection-complete.jpg | The GitHub collection finished, through the App |

Shots 07 and 11 are meant to be shown together: the same two clauses, before and after the evidence.
