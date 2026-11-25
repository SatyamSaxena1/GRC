# Plan: widening our DPDP checks from 9 requirements toward the law's full set of duties

Written 26 Nov 2026. This is a plan, not a change: nothing in the product or its content packs is altered by this document.

## 1. Why
Our DPDP pack (`app/content/dpdp-2023.yaml`) checks **nine** requirements. The Act and Rules, read as duties a business must meet,
come to about **79** (section 2). "DPDP ready" in our product therefore means a good deal less than the law asks, and a buyer who has
read the law can see that. Our own organisation shows **1 of 5** after four service baselines were marked not applicable.

## 2. Where the list of duties comes from, and what to check
The 79-duty register was read from `src/lib/obligations.ts` in the repository `shubham-bhagat78/DPDP-SAAS` (a private DPDP demo called
ConsentPal; read on 26 Nov 2026 at the owner's direction). Its header says every legal reference was checked against the official
Act (2023) and Rules (G.S.R. 846(E)). Treat it as a **map to the law, not the law**:
- **Verify each citation against the official text** before it ships. The Rules' notification date is reported as 13 or 14 Nov 2025 by
  different sources, so the start of the main duties is **13 or 14 May 2027**; our pack says 14 May and that repository says 13 May.
  Settle this from the Gazette (G.S.R. 846(E)), and then use one date everywhere.
- **Write our own wording.** Take the duties and section references as a starting point; do not copy that repository's descriptions
  or text. Get the repository owner's written agreement to the use, and say where the list came from in the pack file's header.
- **Counsel reviews the final pack.** This is readiness, not legal advice, as the DPDP page already says.

## 3. What our product is for, and what it is not
Our product checks **evidence**: documents, system settings, records and statements, each with a source, and a verdict an auditor can
re-check. It is not a consent-management or rights-desk tool. So for each duty the question is **what evidence would prove it**, not how to
run it. That sorts the 79 duties into seven treatments:

| Treatment | Duties |
|---|---|
| Fixed rule | 5 |
| AI-assessed document | 11 |
| Our own records | 10 |
| Connector or attestation | 4 |
| Attestation | 24 |
| Operational: attest now | 19 |
| Guidance only | 6 |
| **Total** | **79** |

- **Fixed rule** (5): a structured fact decides, as for Rule 7 today. Example: the board is told within 72 hours; logs are kept 365 days.
- **AI-assessed document** (11): the duty is about whether a document does its job (a privacy notice, a retention rule, a vendor
  contract, a grievance route). The model proposes with quotes and pages; a person confirms (ADR-069). Needs that lane to be built.
- **Our own records** (10): the product already holds the evidence: the policy library, the training module, the vendor register, the
  rights-request and breach logs, the audit log and tasks. A fixed rule can read those directly, so no upload is needed.
- **Connector or attestation** (4): encryption, access control, logging and technical measures, from the Rule 6 connector snapshots where
  a service is used, otherwise a named person's statement.
- **Attestation** (24): about behaviour no document shows (for example "no consent text waives a person's rights", the children's-data
  duties). A named person attests, with an expiry, as in ADR-060. Shown as attested, never as passed.
- **Operational: attest now** (19): in a consent tool these are computed from live data (consent ledger, suppression lists, sharing
  chain). We do not build that. Until a customer's own tool can export the figures, a person attests, and a later connector can replace
  the statement with evidence.
- **Guidance only** (6): changes to watch (Consent Manager registration, the CERT-In clock, extensions, the three-year inactivity rule).
  Shown, not scored.

## 4. Applicability
Many duties apply only to some organisations: children's data, Significant Data Fiduciary duties, cross-border transfers, research
exemptions. The product already lets an organisation mark a **source** not applicable (we did this for four services). It needs the same
for a **duty**: not applicable, with a reason, a named person and a date, kept in the audit log, and excluded from the score. A duty
marked not applicable without a reason should not be possible.

## 5. Order of work
**Phase 1: no new engine work.** Add the attestation, guidance and operational duties to the pack as attestation-only requirements
(ADR-060), and the duties our own records can prove as rules over those records. This alone takes the pack from 9 toward about 70
scoreable lines, most of them honestly "not yet attested" until a person acts. Add duty-level not-applicable.
**Phase 2: after the AI-assessed lane (ADR-069).** Move the 11 document duties onto it: privacy notice (Rule 3, language, contact, rights
route), grievance, retention rule, legal hold, vendor contracts and sharing agreements, DPIA.
**Phase 3: facts and infrastructure.** Durable logs and a logging policy for the 365-day rule (Rule 6(1)(e) and Rule 8(3)); the breach and
rights logs reported as on-time rates.
**Phase 4: later, only on demand.** Import a customer's consent or suppression exports to replace operational attestations.

## 6. Our own organisation, now
- Rule 7 (breach notification): met, from our approved incident policy.
- Four service baselines (AWS, Microsoft 365, Google Workspace, HR): not applicable, as we do not use them.
- Next for ourselves: a privacy notice (needs writing, then counsel), the retention policy as evidence (waits for the AI lane), and durable logs.
- Our own policy library, training and vendor and risk registers will move several of the "own records" duties as soon as they are in the pack.

## 7. What this plan does not do
- It does not build consent management, a rights desk, a customer portal or a cookie scanner, which that repository's demo shows.
- It does not make anyone compliant. It makes our checks as wide as the law, and keeps the labels honest: passed, AI-assessed, attested.
- Most substantive duties start in May 2027, so there is time to do this carefully.

## 8. Open questions for the owner
1. Is written permission from the repository's owner in place for using the register as a starting point?
2. Which date for the start of the main duties, 13 or 14 May 2027, once the Gazette is read?
3. Phase 1 first, or wait for the AI-assessed lane so the pack lands once?

## Appendix: the 79 duties and how we would check each

(Duty titles are short paraphrases for planning. They are not the pack's wording.)

### Notice and consent (16)

| Duty | Law | How we would check it |
|---|---|---|
| Every use rests on consent or a listed legitimate use | s.4(1), s.7 | Operational: attest now |
| Service messages stay apart from marketing | s.7(a), s.2(za) | Operational: attest now |
| A notice comes with or before every consent request | s.5(1) | Operational: attest now |
| The notice has everything Rule 3 asks for | Rule 3 | AI-assessed document |
| Offer the notice in English or any of the 22 languages | s.5(3), s.6(3) | AI-assessed document |
| People who agreed before the Act get the new notice | s.5(2) | Attestation |
| No consent text waives a person's rights | s.6(2) | Attestation |
| You can prove notice and consent for every person you use | s.6(10), s.6(1) | Operational: attest now |
| Withdrawing is as easy as agreeing | s.6(4) | Operational: attest now |
| On withdrawal you and your vendors stop within a reasonable time | s.6(5)-(6) | Attestation |
| Every consent request shows who to contact | s.6(3) | Operational: attest now |
| Bought and partner-passed contacts have consent that covers you | s.6, s.8(1) | Attestation |
| Ready to accept consent changes through a Consent Manager | s.6(7)-(9), Rule 4 | Guidance only |
| When a person says stop, everyone the data went to is told, and confirms | s.6(6), s.8(7)(b) | Operational: attest now |
| People who said no are blocked from every send | s.6(4), s.6(5) | Operational: attest now |
| Telecom permission is tracked apart from DPDP consent | s.6, TRAI TCCCPR | Operational: attest now |

### Rights and grievance (11)

| Duty | Law | How we would check it |
|---|---|---|
| A contact person is published and shown in every reply | s.8(9), Rule 9 | AI-assessed document |
| How to make a request is published | Rule 14(1) | AI-assessed document |
| A grievance system with a published reply time of 90 days or less | s.8(10), s.13, Rule 14(3) | AI-assessed document |
| Access, correction and deletion requests are answered on time | s.11, s.12 | Our own records |
| You can say what you hold and who it was shared with | s.11(1)(a)-(b), s.11(2) | Operational: attest now |
| Deletion requests are carried out, except what a law makes you keep | s.12(3) | Our own records |
| Wrong or incomplete details are corrected | s.12(2) | Our own records |
| People can nominate someone to act for them | s.14, Rule 14(4) | Operational: attest now |
| Identity is checked before acting, with minimum ID | Rule 14, good practice | Operational: attest now |
| People can see who holds their details and stop it themselves | s.11(1), s.13, Rule 14 | Operational: attest now |
| Data used for a decision, or handed to another business, is complete, accurate and consistent | s.8(3) | Attestation |

### Security and breach (13)

| Duty | Law | How we would check it |
|---|---|---|
| Personal data is encrypted, masked or tokenised | s.8(5), Rule 6(1)(a) | Connector or attestation |
| Access to systems is controlled | s.8(5), Rule 6(1)(b) | Connector or attestation |
| You can see who touched the data, and review it | s.8(5), Rule 6(1)(c) | Connector or attestation |
| Backups let you carry on after a loss or lock-out | s.8(5), Rule 6(1)(d) | Attestation |
| Logs and the data they cover are kept for one year | Rule 6(1)(e), Rule 8(3) | Fixed rule |
| Technical and organisational measures are in place | s.8(4), Rule 6(1)(g) | Connector or attestation |
| Each affected person is told without delay, with five facts | s.8(6), Rule 7(1) | Fixed rule |
| The Board is told without delay | Rule 7(2)(a) | Fixed rule |
| The full report reaches the Board within 72 hours | Rule 7(2)(b) | Fixed rule |
| A breach plan exists, with contacts and a practised drill | Rule 7 | Fixed rule |
| A longer period for the 72-hour report needs a written request | Rule 7(2)(b) | Guidance only |
| CERT-In has its own, shorter reporting clock for some incidents | CERT-In (separate regime) | Guidance only |
| Vendors that process your data keep the logs and data for a year too | Rule 8(3), Rule 6(1)(e) | Attestation |

### Retention and deletion (8)

| Duty | Law | How we would check it |
|---|---|---|
| A retention rule for each kind of data, with a reason | s.8(7)(a), s.8(8) | AI-assessed document |
| Scheduled deletions actually run | s.8(7) | Operational: attest now |
| Your vendors erase what you gave them | s.8(7)(b) | AI-assessed document |
| Records a law makes you keep are held apart and used for nothing else | Rule 8(3), s.8(7) | AI-assessed document |
| You collect only the data the purpose needs | s.6(1) | Attestation |
| Three-year inactivity erasure with a 48-hour warning | Rule 8(1)-(2), Third Schedule | Guidance only |
| Details you ask for through a link or QR are only what the purpose needs | s.6(1), s.8(7) | Operational: attest now |
| When a person takes their details back, you delete your copy and confirm | s.6(6), s.8(7)(a) | Operational: attest now |

### Children's data (6)

| Duty | Law | How we would check it |
|---|---|---|
| A verified parent agrees before you process a child's data | s.9(1), Rule 10 | Attestation |
| The parent is checked as an identifiable adult | Rule 10(1)-(2) | Attestation |
| You know which exemption applies to you and its conditions | Rule 12, Fourth Schedule | Attestation |
| No tracking, behavioural monitoring or ads aimed at children | s.9(3) | Attestation |
| Nothing you do is likely to harm a child's well-being | s.9(2) | Attestation |
| A guardian of a person with a disability is checked before you process the person's data | s.9(1), Rule 11 | Attestation |

### Vendors, sharing and transfers (9)

| Duty | Law | How we would check it |
|---|---|---|
| Every vendor is under a valid contract with security terms | s.8(2), Rule 6(1)(f) | AI-assessed document |
| You have checked each vendor's security | s.8(1), s.8(5) | Our own records |
| You record who each person's data was shared with | s.11(1)(b) | Operational: attest now |
| You know where data goes abroad and watch for restrictions | s.16, Rule 15 | Attestation |
| Sector rules on keeping data in India are met | s.16(2) | Attestation |
| Foreign customers' data is tagged, so the exemption is used correctly | s.17(1)(d) | Attestation |
| Everyone you pass data to has signed an agreement | s.8(1), s.8(2) | AI-assessed document |
| A recipient cannot quietly pass the data further | s.8(1), s.8(2) | Operational: attest now |
| Data you receive is not used for offers without the person's own yes | s.6(1), s.7(a) | Operational: attest now |

### Governance and people (9)

| Duty | Law | How we would check it |
|---|---|---|
| Staff are trained on the basics | s.8(4) | Our own records |
| Policies are published and acknowledged | s.8(4) | Our own records |
| Employee data is handled with a notice and the same safeguards | s.7(i) | Attestation |
| An India-based DPO answerable to the board | s.10(2)(a) | Attestation |
| An independent data auditor is appointed | s.10(2)(b) | Attestation |
| A yearly impact assessment and audit, reported to the Board | s.10(2)(c), Rule 13(1)-(2) | AI-assessed document |
| Algorithms that handle personal data do not put people's rights at risk | Rule 13(3) | Attestation |
| Specified data stays in India if the Government says so | Rule 13(4) | Guidance only |
| Research, archiving or statistics use stays inside the exemption's conditions | s.17(2)(b), Rule 16, Second Schedule | Attestation |

### Board-ready proof (7)

| Duty | Law | How we would check it |
|---|---|---|
| Every duty that applies has live evidence behind it | s.6(10), s.33(2) | Our own records |
| Every incident has a time-stamped record of how you fixed it | s.33(2)(e) | Our own records |
| You are ready to offer a voluntary undertaking | s.32 | Attestation |
| Someone can answer the Board and carry out its directions | s.27(2), s.28(7), Rule 19(9) | Our own records |
| You hear about changes that affect you the day they happen | s.10, s.16, s.17(3) | Guidance only |
| Every action and every decision by a person is on record | s.8(1), s.33(2) | Our own records |
| A Government request for information is answered, and kept confidential if you are told so | s.36, Rule 23 | Attestation |
