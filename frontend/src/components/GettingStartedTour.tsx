import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

const TOUR_STORAGE_KEY = "grc:getting-started-tour-complete";

type TourStep = {
  eyebrow: string;
  title: string;
  body: string;
  target?: string;
  route?: "/evidence" | "/gaps";
};

const STEPS: readonly TourStep[] = [
  {
    eyebrow: "Start with people",
    title: "Invite the person who owns the control",
    body: "In GRC, the auditee is usually the person who operates a process and supplies its proof. Create them as a Control owner; they will only see work assigned to them.",
    target: "invite-user",
  },
  {
    eyebrow: "Define the requirement",
    title: "Register the control to be tested",
    body: "A control is a safeguard, such as approving access requests. The framework and clause identify the requirement it satisfies.",
    target: "register-control",
  },
  {
    eyebrow: "Give ownership",
    title: "Assign the control to the auditee",
    body: "Copy the new user ID and control ID into this form. Assignment is the access boundary: the control owner can see this control without gaining organisation-wide access.",
    target: "assign-control",
  },
  {
    eyebrow: "Collect proof",
    title: "Ask the owner to upload evidence",
    body: "Switch identity to the Control owner and upload a policy, procedure, screenshot, or report. The system analyses the evidence and links it to relevant controls.",
    route: "/evidence",
  },
  {
    eyebrow: "Review and improve",
    title: "Resolve gaps before the audit",
    body: "Check Gaps for missing or weak proof, then use Tasks to track the requested fix. When corrected evidence resolves a gap, its task closes automatically.",
    route: "/gaps",
  },
];

export function GettingStartedTour() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);
  const dialogRef = useRef<HTMLDivElement>(null);
  const current = STEPS[step];

  useEffect(() => {
    if (open) dialogRef.current?.focus();
  }, [open, step]);

  const close = (complete = false) => {
    setOpen(false);
    document.querySelector(".tour-target")?.classList.remove("tour-target");
    if (complete) localStorage.setItem(TOUR_STORAGE_KEY, "true");
  };

  const showStep = (nextStep: number) => {
    document.querySelector(".tour-target")?.classList.remove("tour-target");
    setStep(nextStep);
    const target = STEPS[nextStep].target;
    if (target) {
      requestAnimationFrame(() => {
        const element = document.getElementById(target);
        element?.classList.add("tour-target");
        element?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    }
  };

  const start = () => {
    setOpen(true);
    showStep(0);
  };

  const next = () => {
    if (step === STEPS.length - 1) {
      close(true);
      return;
    }
    showStep(step + 1);
  };

  const goToTask = () => {
    if (!current.route) return;
    close(step === STEPS.length - 1);
    navigate(current.route);
  };

  return (
    <>
      <section className="getting-started" aria-labelledby="getting-started-title">
        <div className="getting-started-icon" aria-hidden="true">✓</div>
        <div>
          <span className="eyebrow">New to GRC?</span>
          <h3 id="getting-started-title">Set up your first auditee workflow</h3>
          <p>Learn the five steps from assigning a control owner to fixing audit gaps. No compliance background required.</p>
        </div>
        <button className="btn btn-primary" onClick={start}>
          {localStorage.getItem(TOUR_STORAGE_KEY) ? "Replay guided tour" : "Start guided tour"}
        </button>
      </section>

      {open && (
        <div className="tour-backdrop" role="presentation">
          <div
            className="tour-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="tour-title"
            ref={dialogRef}
            tabIndex={-1}
            onKeyDown={(event) => event.key === "Escape" && close()}
          >
            <div className="tour-progress" aria-label={`Step ${step + 1} of ${STEPS.length}`}>
              {STEPS.map((item, index) => (
                <span key={item.title} className={index <= step ? "complete" : ""} />
              ))}
            </div>
            <button className="tour-close" onClick={() => close()} aria-label="Close guided tour">×</button>
            <span className="eyebrow">Step {step + 1} of {STEPS.length} · {current.eyebrow}</span>
            <h3 id="tour-title">{current.title}</h3>
            <p>{current.body}</p>
            {current.route && (
              <button className="tour-link" onClick={goToTask}>Open {current.route === "/evidence" ? "Evidence" : "Gaps"} →</button>
            )}
            <div className="tour-actions">
              <button className="btn" disabled={step === 0} onClick={() => showStep(step - 1)}>Back</button>
              <button className="btn btn-primary" onClick={next}>{step === STEPS.length - 1 ? "Finish tour" : "Next"}</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
