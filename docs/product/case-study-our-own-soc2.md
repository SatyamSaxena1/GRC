# Case study: getting ourselves ready for a SOC 2 audit, using our own product

Written 12 Nov 2026, from what actually happened on that day. It is meant to be read by a person, and to be cut into a
video (section 6). Where something is not done yet, it says so. Update the "where we are" table when that changes.

## 1. The story in one paragraph

A small software company wants to sell to bigger buyers, and the buyers ask for a SOC 2 report. The company has no
compliance team. It uses its own product to see what is missing, write its policies, say what is true, and keep the
proof in one place, so that when an independent audit firm arrives, the answers are already written down. We are that
company, and the product is the one we sell.

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

## 3. Where we are (12 Nov 2026)

| Step | Status |
|---|---|
| 1. Scope | **Not decided.** Suggested: Security criteria only, Type 1 first |
| 2. Readiness check | **Done** (docs/product/soc2-readiness.md) |
| 3. Policies and controls | **In progress.** Five policies are written and waiting for the owner to read and approve them. Two statements are signed |
| 4. Evidence | **Barely started.** Change history and weekly scans exist; our own organisation holds little yet |
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
organisation with every clause showing "no evidence", all red. This is the honest starting point.*

**Scene 4: Write the policies.**
Five policy templates were added as drafts (access, passwords, encryption, incident response, data retention). Their
numbers come from the framework rules, not from guesswork. We filled in our company name, the approver's role, and what
"in scope" means for us. *On screen: the policy list, five drafts, "not approved yet".*

**Scene 5: Say only what is true.**
Two clauses were attested by a named person: secure development (every change is a reviewed pull request that must pass
the checks) and security testing (tests on every change, a weekly package scan, and an honest note that we have no code
scanner yet). The product records who said it and until when (one year at most). It shows these as "attested", never as
"passed", because a statement is not a test. *On screen: the clause turns from "no evidence" to "attested", with the
wording.*

**Scene 6: Leave the gaps visible.**
Multi-factor sign-in, backups with a tested restore, durable logs and background checks stay open. We do not sign things
we cannot prove. An auditor will find them anyway, and an honest open gap is better than a statement that falls apart.
*On screen: the list of open items.*

**Scene 7 (next): Approve, then gather proof.**
The owner reads each policy and approves it. The product then asks every person to accept it. Approval is a human act:
the product refuses to let anyone approve text that changed after they read it. After that, real evidence flows in:
scan results, change history, training records.

## 5. What went wrong, and what we learned

- **The invite failed for our own administrator.** The sign-in service already had a login for that email which could not
  be sent a password link, so the invite stopped with a vague "502" error. We got around it with a variant of the address.
  Lesson: inviting someone who already signs in another way should work, or say clearly why not. This is a real bug in our
  product, found by using it ourselves. *(Fix not yet made.)*
- **The first reset email went to the wrong account.** The sign-in page remembered an old test account's address.
  Nothing was harmed. Lesson: check the address on every sign-in screen before sending anything.
- **The first live check of the hidden API pages failed.** It expected a 401; the live API answers 422 for a missing
  header. Fixed by running the check against the real site once.
- **A policy cannot be approved while it has blanks.** The templates had placeholders such as "[your organisation]".
  They were filled before approval.

## 6. Video outline (about 5 minutes, plain words)

1. **Hook (0:20).** "A buyer asks for a SOC 2 report. You have no compliance team. What now?"
2. **Who does what (0:40).** The step table in section 2, drawn as a simple lane diagram: you, the product, the auditor.
3. **Honest start (0:40).** Scene 1 and 3: everything red.
4. **Fix and write (1:00).** Scenes 2 and 4.
5. **Say only what is true (1:00).** Scenes 5 and 6: attested, not passed; open gaps left visible.
6. **What the auditor does (0:40).** They test, they do not write. The evidence is ready.
7. **Close (0:40).** Where we are now: two steps done, one in progress, the rest honest. "Here is what happens next."

**Do not show on screen:** the operator key, any password or reset link, the other test accounts' email addresses,
the Auth0 dashboard, or the database. Use the demo or our own organisation only, never customer data.

## 7. What a viewer should take away

1. Compliance is mostly writing down true things and keeping proof, not buying a tool.
2. A statement and a test are different, and a good product labels them differently.
3. An honest gap list is better than a clean-looking one.
4. The independent auditor comes last, and the work is already done when they arrive.

## 8. What this case study does not claim

- We have **not** started an audit, chosen an audit firm, or been certified. No report exists.
- Our policies are drafts until the owner approves them, and the multi-factor statement in the password policy has not
  been checked on our accounts yet.
- The product helps organise the work. It does not make a company compliant by itself.
