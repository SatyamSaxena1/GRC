import { useEffect, useRef, useState } from "react";

type PageTourStep = {
  title: string;
  body: string;
  target: string; // CSS selector to highlight — a real element already on this page
};

// A tour scoped to the elements of ONE page — how to read this table, what
// this button does, what this filter changes. Deliberately separate from
// GettingStartedTour (which walks a user across several pages/routes) and
// LoginTour (which walks the login page's role tabs): neither of those
// explains what's actually on, say, the Notifications or Tasks page once
// you're there. No cross-route navigation here — every step's target must
// already exist on the current page.
export function PageTour({
  id,
  label = "How this page works",
  steps,
}: {
  id: string;
  label?: string;
  steps: readonly PageTourStep[];
}) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);
  const dialogRef = useRef<HTMLDivElement>(null);
  const current = open ? steps[step] : null;
  const completeKey = `grc:page-tour:${id}:complete`;

  const close = (complete = false) => {
    if (complete) localStorage.setItem(completeKey, "true");
    document.querySelector(".tour-target")?.classList.remove("tour-target");
    setOpen(false);
  };

  const advance = () => {
    if (step === steps.length - 1) close(true);
    else setStep((value) => value + 1);
  };

  useEffect(() => {
    if (!current) return;
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
  }, [current]);

  if (steps.length === 0) return null;

  return (
    <>
      <button
        className="btn page-tour-btn"
        onClick={() => { setStep(0); setOpen(true); }}
        aria-label={`${label} — guided tour`}
        title={label}
      >
        <span className="tour-icon" aria-hidden="true">?</span>
        {label}
        {!localStorage.getItem(completeKey) && <span className="tour-unseen-dot" aria-hidden="true" />}
      </button>

      {current && (
        <div className="tour-clickthrough-layer" role="presentation">
          <div
            className="tour-dialog tour-coachmark"
            role="dialog"
            aria-modal="true"
            aria-labelledby="page-tour-title"
            ref={dialogRef}
            tabIndex={-1}
            onKeyDown={(event) => event.key === "Escape" && close()}
          >
            <div className="tour-progress" aria-label={`Step ${step + 1} of ${steps.length}`}>
              {steps.map((s, index) => (
                <span key={s.title} className={index <= step ? "complete" : ""} />
              ))}
            </div>
            <button className="tour-close" onClick={() => close()} aria-label="Close tour">×</button>
            <span className="eyebrow">{label} · {step + 1} of {steps.length}</span>
            <h3 id="page-tour-title">{current.title}</h3>
            <p>{current.body}</p>
            <div className="tour-actions">
              <button className="btn" disabled={step === 0} onClick={() => setStep((value) => value - 1)}>Back</button>
              <button className="btn btn-primary" onClick={advance}>
                {step === steps.length - 1 ? "Finish" : "Next"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
