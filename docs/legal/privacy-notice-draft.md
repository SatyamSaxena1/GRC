# Privacy notice: GRC Platform (DRAFT for counsel)

> **Status: draft, not yet published, not legal advice.** Prepared 26 Nov 2026 from what the product actually does. Fill every
> `[bracketed blank]`, have counsel review it against the Digital Personal Data Protection Act 2023 and Rules 2025 (in particular
> Rule 3, the notice content, and Rules 9 and 14, contact and grievance), then publish it at a public address and use that address
> as the `PRIVACY_NOTICE` evidence. Facts marked **(confirm)** were not verifiable from the code and need the owner.
>
> To meet the Rule 3 and s.5 content checks, the notice stands on its own: it does not say "see our policy". Keep it that way.

---

# How GRC Platform uses your personal data

**Last updated:** [date]. **Who we are:** [registered name of the company or proprietor] ("we", "GRC Platform"), [address].
**Who to ask about your data:** [name and role of the contact person], [email address], [phone, optional]. Web page: [public address of this notice].

## 1. What this notice is about
GRC Platform is an online service that helps organisations keep, check and show the evidence they need for security and privacy
audits. This notice explains what personal data we collect when you use it or contact us, why, who else handles it, how long we
keep it, and how you can exercise your rights. If you use GRC Platform because your employer or another organisation
uses it, that organisation decides what is put into its workspace, and this notice covers our own handling of your account and of
what you or your organisation upload.

## 2. The personal data we collect
We collect only these kinds of data:
- **Your account details:** your name, if you give it, and your work email address, so that we can create your sign-in and know who you are inside your organisation's workspace.
- **What you do in the service:** which pages you open and which actions you take (for example approving a policy or attesting a control), with the time, because the service keeps a tamper-evident record of changes that auditors rely on.
- **Documents and records you or your organisation upload** (policies, reports, screenshots, registers). These may contain personal data, such as names and email addresses, that your organisation chose to include. We do not ask for more than the service needs.
- **Technical data:** your IP address, browser type and the time of each request, to keep the service secure and working.
- **Messages you send us:** when you write to us, we keep the message and your reply address.

We do **not** knowingly collect sensitive categories such as health, financial-account or biometric data, and we ask you not to upload them. The service is meant for working adults and organisations: **it is not directed at children**, and we do not knowingly collect data about anyone under 18.

## 3. Why we use it (our purposes)
- To **create and secure your account** and show you only your organisation's workspace.
- To **run the service**: store your documents, work out compliance results from them, and keep the audit record.
- To **help with drafting**: an automated language model may read an uploaded document or a question to suggest wording or point to a quote. It only **suggests**; a person approves, and it does not decide any result alone. **(confirm which model provider is in use today.)**
- To **send you messages about the service**: sign-in invitations, task and review alerts, and a weekly summary. These are service messages, not marketing. **(confirm: we send no marketing; remove this line if that changes.)**
- To **keep the service safe and fix faults**, and to meet our legal duties.

We use your data for these purposes only. If we want to use it for anything else, we will ask you first.

## 4. Who else handles your data
We use these service providers to run GRC Platform. They handle your data only to provide their service to us:
- **Hosting:** Render, which runs the application. **(confirm region.)**
- **Database:** Supabase, which stores the data. **(confirm region.)**
- **Network protection:** Cloudflare, which passes web traffic to the service.
- **Sign-in:** Auth0, which checks who you are.
- **Email:** [email service, for example Brevo], which sends service messages.
- **Language model:** [provider, if any], as described above.

We do not sell your data. We share it with authorities only when the law requires. **(confirm: where the data is stored and whether any is processed outside India; if so, say where and why.)**

## 5. How long we keep it
- **Your account and activity record:** while you have access to your organisation's workspace, and for up to 90 days after your access ends, so we can trace who did what.
- **Documents your organisation uploaded:** while the organisation's account is active, and then they are deleted within 90 days after it closes.
- **The audit record of changes:** at least one year, because auditors and the law ask for it.
- **Technical request logs:** [period]. **(confirm: our target is one year; today logs are not yet kept durably, so state only what is true.)**
- **Messages to us:** [period, for example two years].
After that we delete the data or remove what identifies you. Where a law requires us to keep a record longer, we keep only that record and use it for nothing else.

## 6. How we protect it
Data is encrypted while it travels (HTTPS) and while stored. Each organisation can see only its own workspace. Access to our systems needs a second sign-in step. **(confirm: today this is true for our hosting and code accounts but not yet for the service's own sign-in; remove or soften the last sentence until it is true for all.)** If a personal-data breach affects you, we will tell you without delay, and report it to the Data Protection Board of India as the law requires.

## 7. Your choices and rights
You can, at any time and free of charge:
- **Withdraw your consent**, as easily as you gave it: email [contact email] with the subject "Withdraw", or use [link, if the service offers it]. Withdrawing does not undo what we did before you withdrew, and some things (the audit record) we must keep, as explained above.
- **Ask what personal data we hold about you** and who it is shared with.
- **Ask us to correct** data that is wrong or incomplete.
- **Ask us to delete** your data. We will, except for what a law makes us keep.
- **Nominate someone** to exercise these rights for you if you die or cannot act.
**How to ask:** email [contact email] or write to [address]. We may check who you are before acting, asking only for what is needed. We answer within [30] days.

## 8. If you are unhappy
Tell our contact person first: [name, email]. We will acknowledge your complaint within [7] days and give you a reply within [30] days, and in any case within the 90 days the law allows. If you are not satisfied, you may complain to the **Data Protection Board of India** once you have used our grievance route.

## 9. Changes to this notice
If we change how we use your data, we will update this page and the date at the top, and tell you in the service before the change takes effect when it matters to you.

---

## Checklist for the owner before publishing
1. Fill the contact person, email, address and the date; decide the response times (30 days is suggested; the law's ceiling is 90).
2. Confirm every item marked **(confirm)**: model provider, hosting and database regions, whether any data leaves India, request-log retention, and the second-sign-in sentence.
3. Counsel reviews against Rule 3, s.5 to 6, Rules 9 and 14.
4. Publish at a public address; link it from the sign-in page and the footer; then upload that page as a `PRIVACY_NOTICE` and run the AI assessment (ADR-069) for the two DPDP notice clauses.
5. Keep this notice consistent with the approved Data Retention policy (v3) and the Incident Response policy; change one and you must check the other.
