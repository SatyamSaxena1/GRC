/** Public lessons: "SOC 2 in plain words" (ADR-065). Written in our own words. Drafted with AI help: the page shows a
 *  draft notice until the owner has reviewed the text, and then REVIEWED is set to true. */
export const REVIEWED = false;

export type PublicQuestion = { scenario: string; choices: string[]; answer: number; why: string };
export type PublicLesson = { slug: string; title: string; body: string; questions: PublicQuestion[] };

export const SOC2_LESSONS: PublicLesson[] = [
  {
    slug: "what-is-soc-2",
    title: "What SOC 2 is, and what it is not",
    body: `SOC 2 is a report, not a certificate. An independent audit firm (a licensed CPA firm) checks how you protect your customers' data and writes down what it found. Your customers read that report to decide whether to trust you.

The checks follow a set of criteria published by the AICPA, called the Trust Services Criteria. They are grouped into five areas:
- Security: always included. It covers access, change, monitoring, incidents and the rest of the basics.
- Availability: is the service up when customers need it?
- Processing integrity: does the system do what it should, completely and correctly?
- Confidentiality: is information marked confidential kept that way?
- Privacy: is personal information collected, used and deleted as promised?

Most startups start with Security alone and add more when customers ask.`,
    questions: [
      { scenario: "A prospect asks: 'Are you SOC 2 certified?' What is the most accurate reply?",
        choices: ["Yes, we hold a SOC 2 certificate", "We have a SOC 2 report from an independent auditor, which we can share under NDA",
          "SOC 2 does not apply to software companies"], answer: 1,
        why: "SOC 2 ends in an auditor's report, not a certificate. Customers usually read it under a non-disclosure agreement." },
      { scenario: "Which of the five areas has to be in every SOC 2 report?",
        choices: ["Privacy", "Availability", "Security"], answer: 2,
        why: "Security is always in scope. The other four are added when they matter to your customers." },
    ],
  },
  {
    slug: "type-1-and-type-2",
    title: "Type 1 and Type 2",
    body: `A Type 1 report looks at one day. The auditor checks that your controls are designed well and in place on that date.

A Type 2 report looks at a period, often three to twelve months. The auditor checks that the controls actually worked, again and again, across the whole period, by looking at samples of evidence from it.

Buyers usually want Type 2, because it shows habits, not a good day. A common path is a Type 1 first, to get something in hand quickly, then a Type 2 the following period. Either way, the report gets older every month, so you repeat the audit every year.`,
    questions: [
      { scenario: "Your biggest prospect wants proof that your access reviews happen every quarter, not just once. Which report shows that?",
        choices: ["Type 1", "Type 2", "Either, they are the same"], answer: 1,
        why: "Only a Type 2 tests that a control kept working across a period of time." },
      { scenario: "You got a Type 2 report 14 months ago. A customer asks if it is still current.",
        choices: ["Yes, a SOC 2 report never expires", "It is out of date: the next audit should already have started",
          "Only if nothing changed in the company"], answer: 1,
        why: "Reports cover a past period. Customers expect a new one every year, with a bridge letter for any gap in between." },
    ],
  },
  {
    slug: "scope-and-controls",
    title: "Scope and controls: you write them",
    body: `SOC 2 does not hand you a checklist. You decide what is in scope (the product, the systems and the people behind it), and you write your own controls: the things you do to meet each criterion.

A control is a specific, checkable habit. "We care about security" is not a control. "Every production access request is approved by an engineering lead in the ticket system" is.

Good controls are small and true. Write down what you really do, then do it every time. A control you cannot keep is worse than none, because the auditor will test it and write down that it failed.`,
    questions: [
      { scenario: "Which of these is a control an auditor can test?",
        choices: ["We take security seriously", "Laptops are encrypted, and a device tool reports it daily",
          "Engineers try to be careful with data"], answer: 1,
        why: "A control names a specific habit and leaves a record that can be checked." },
      { scenario: "Your draft says code is reviewed by two people, but your team of four usually has one reviewer.",
        choices: ["Keep 'two reviewers': it sounds stronger", "Change the control to what you really do, if it still meets the criterion",
          "Leave it vague so it cannot fail"], answer: 1,
        why: "The auditor tests what you wrote. Write what you actually do, as long as it still meets the criterion." },
    ],
  },
  {
    slug: "evidence",
    title: "Evidence: proof that the control worked",
    body: `For each control, the auditor asks for proof that it worked. For a Type 2 they pick samples from the period, for example 25 of the access requests made in it, and ask for the record of each one.

Good evidence is dated, comes straight from the system, and shows the whole thing: an exported list of users, a log, a ticket with its approval, a setting read from the cloud console. A screenshot with no date or a document written the week before the audit is weak.

When a sample shows the control did not work, the auditor records an exception in the report. A few explained exceptions are normal. Many, or hidden ones, are what worry customers.`,
    questions: [
      { scenario: "The auditor asks for proof of last March's access review. Which is the strongest evidence?",
        choices: ["A note written today saying the review happened", "The review ticket from March, with the user list exported then and the approver's sign-off",
          "A screenshot of today's user list"], answer: 1,
        why: "Evidence should come from the period, from the system, with who approved it and when." },
      { scenario: "One of 25 sampled changes skipped review. What happens?",
        choices: ["The whole audit fails", "It is recorded as an exception, ideally with your explanation and fix",
          "You can replace it with a different sample"], answer: 1,
        why: "Exceptions are written into the report. What matters is that they are few, explained and fixed." },
    ],
  },
  {
    slug: "getting-started",
    title: "Getting started: the first 90 days",
    body: `1. Readiness check. Compare what you do today with the criteria, and list the gaps.
2. Fix the basics. Single sign-on and multi-factor sign-in, encrypted laptops, code review, backups, logging, an incident plan, vendor reviews, staff training.
3. Write the policies. Short ones you actually follow: access, change, incident, vendor, data handling.
4. Collect evidence as you go. Have tools read it from your systems where they can, so it is dated and complete without anyone remembering to take a screenshot.
5. Choose an audit firm and agree the scope and the period.
6. Run the period, then the audit. Fix what comes up, and keep going: next year's audit starts the day this one ends.`,
    questions: [
      { scenario: "What should come first?",
        choices: ["Book the auditor for next week", "A readiness check against the criteria", "Buy every security tool you can"], answer: 1,
        why: "You cannot fix gaps you have not found. A readiness check shows where to spend time before an auditor looks." },
      { scenario: "Why have evidence collected from systems directly, instead of screenshots before the audit?",
        choices: ["It is dated and complete across the whole period, with no one having to remember",
          "Auditors do not accept screenshots at all", "It makes the audit unnecessary"], answer: 0,
        why: "A Type 2 looks across months. Evidence read from the system as it happens covers that without gaps." },
    ],
  },
];
