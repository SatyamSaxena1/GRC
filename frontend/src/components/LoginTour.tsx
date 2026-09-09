import { useEffect, useRef, useState } from "react";
import type { Tab } from "../pages/Login";

type Step = {
  title: string;
  body: string;
  tab: Tab | null;      // switch the login page to this tab when the step opens
  target: string;       // CSS selector to highlight — a real element on this page
};

// A GRC engagement is five separate parties who never see the same thing —
// enforced by the backend (app/authorization.py and app/auth.py), not hidden by
// this UI. This walks a tester through signing in as each one in the order that
// lets every role's restriction actually be observed, rather than just
// described. It starts on the firm's side, because that is where a real client
// comes from: nothing auditee-shaped exists until a firm approves it.
const STEPS: readonly Step[] = [
  {
    title: "One backend, five roles",
    body: "Everything below signs in as one of the real participants in an audit: the firm selling the audit and its individual auditors, the organisation being audited, and that organisation's employees. Each sees a different slice of the same data — enforced server-side, so switching identity here is the actual test, not a costume change.",
    tab: null,
    target: '[data-tour="login-tabs"]',
  },
  {
    title: "1 — Become the audit firm",
    body: "Start here rather than with the auditee: in a real deployment a client exists because a firm onboarded it. Creating a firm also creates its first firm admin and signs you in as that person, so every onboarding and staffing decision is attributable in the audit trail. Keep the audit firm id it prints.",
    tab: "firm",
    target: '[data-tour="tab-firm"]',
  },
  {
    title: "2 — Ask that firm for an audit",
    body: "Paste the firm id here and send a request as a prospect. Note what does not happen: no organisation, no engagement and no login are created. A pending request owns nothing — the firm approving it is what brings the tenant into existence, which is why rejecting one leaves nothing behind to clean up.",
    tab: "request",
    target: '[data-tour="tab-request"]',
  },
  {
    title: "3 — Approve it, then staff it",
    body: "Sign back in as the firm admin and approve the request in the firm console; you can cut the frameworks down from what was asked for. Then invite an auditor and assign them to that client. Worth testing directly: an auditor of the same firm who is not staffed on a client cannot see it at all — it answers 404, indistinguishable from a client that does not exist.",
    tab: "firm",
    target: '[data-tour="firm-submit"]',
  },
  {
    title: "4 — Become the auditee",
    body: "Quick start is the shortcut past the three steps above: it creates a demo organisation, an audit firm, and an active engagement in one click, and signs you in as that organisation's admin — the auditee. Use it when you want the auditee experience without running an onboarding first. The plain \"Organisation\" tab beside it is only for returning to an org you already created, by pasting its id.",
    tab: "quickstart",
    target: '[data-tour="tab-quickstart"]',
  },
  {
    title: "Note the two ids you're given",
    body: "After you click Create, the page prints an org id and an engagement id. Keep both — the engagement id is what lets you sign in as the auditor later, scoped only to the frameworks that engagement covers. As the auditee, go to Admin next and invite a team member: that creates a user id you'll use for the next role.",
    tab: null,
    target: '[data-tour="tab-quickstart"]',
  },
  {
    title: "5 — Become an employee (control owner)",
    body: "Sign back out and paste that employee's user id here. A control owner sees only the specific controls assigned to them — nothing else in the organisation is even visible, not just uneditable. That restriction is worth testing directly: try loading a control you know exists but wasn't assigned to this user.",
    tab: "user",
    target: '[data-tour="tab-user"]',
  },
  {
    title: "6 — Become the auditor",
    body: "Paste the engagement id from step 4 here instead. The auditor can record verdicts and lock controls, but only for frameworks that engagement was allocated — and can never upload evidence itself (segregation of duties, enforced the same way). Closing the engagement from Admin revokes this access immediately; that's worth testing too.",
    tab: "auditor",
    target: '[data-tour="tab-auditor"]',
  },
  {
    title: "Ready to start",
    body: "Back on Quick start: pick which frameworks the demo organisation subscribes to, then create it. Everything above is real — no seed data, no mocked roles — so whatever you find by switching identities is exactly what a real deployment would enforce.",
    tab: "quickstart",
    target: '[data-tour="quickstart-submit"]',
  },
];

const COMPLETE_KEY = "grc:guided-tour:login:complete";

export function LoginTour({ onSelectTab }: { onSelectTab: (tab: Tab) => void }) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);
  const dialogRef = useRef<HTMLDivElement>(null);
  const current = open ? STEPS[step] : null;

  const close = (complete = false) => {
    if (complete) localStorage.setItem(COMPLETE_KEY, "true");
    document.querySelector(".tour-target")?.classList.remove("tour-target");
    setOpen(false);
  };

  const advance = () => {
    if (step === STEPS.length - 1) close(true);
    else setStep((value) => value + 1);
  };

  useEffect(() => {
    if (!current) return;
    if (current.tab) onSelectTab(current.tab);
    let target: Element | null = null;
    const timer = window.setTimeout(() => {
      target = document.querySelector(current.target);
      target?.classList.add("tour-target");
      target?.scrollIntoView({ behavior: "smooth", block: "center" });
      dialogRef.current?.focus();
    }, 50);
    return () => {
      window.clearTimeout(timer);
      target?.classList.remove("tour-target");
    };
    // onSelectTab is the setState setter from the parent — stable identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current]);

  const start = () => {
    setStep(0);
    setOpen(true);
  };

  return (
    <>
      <button className="tour-launcher" onClick={start} aria-label="Open the testing walkthrough">
        <span aria-hidden="true">?</span> How to test this workspace
        {localStorage.getItem(COMPLETE_KEY) && <span className="muted" style={{ marginLeft: "auto", fontWeight: 400 }}>Completed</span>}
      </button>

      {current && (
        <div className="tour-clickthrough-layer" role="presentation">
          <div
            className="tour-dialog tour-coachmark"
            role="dialog"
            aria-modal="true"
            aria-labelledby="login-tour-title"
            ref={dialogRef}
            tabIndex={-1}
            onKeyDown={(event) => event.key === "Escape" && close()}
          >
            <div className="tour-progress" aria-label={`Step ${step + 1} of ${STEPS.length}`}>
              {STEPS.map((item, index) => (
                <span key={item.title} className={index <= step ? "complete" : ""} />
              ))}
            </div>
            <button className="tour-close" onClick={() => close()} aria-label="Close walkthrough">×</button>
            <span className="eyebrow">Testing walkthrough · {step + 1} of {STEPS.length}</span>
            <h3 id="login-tour-title">{current.title}</h3>
            <p>{current.body}</p>
            <div className="tour-actions">
              <button className="btn" disabled={step === 0} onClick={() => setStep((value) => value - 1)}>Back</button>
              <button className="btn btn-primary" onClick={advance}>
                {step === STEPS.length - 1 ? "Finish" : "Next"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
