import { useState } from "react";
import { TourPopover } from "./TourPopover";

type PageTourStep = {
  title: string;
  body: string;
  target: string; // CSS selector to point at — a real element already on this page
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
  const completeKey = `grc:page-tour:${id}:complete`;

  const close = (complete = false) => {
    if (complete) localStorage.setItem(completeKey, "true");
    setOpen(false);
  };

  if (steps.length === 0) return null;
  const current = open ? steps[step] : null;

  return (
    <>
      <button
        className={`btn page-tour-btn${open ? " is-active" : ""}`}
        onClick={() => { setStep(0); setOpen(true); }}
        aria-label={`${label} — guided tour`}
        title={label}
      >
        <span className="tour-icon" aria-hidden="true">?</span>
        {label}
        {!localStorage.getItem(completeKey) && <span className="tour-unseen-dot" aria-hidden="true" />}
      </button>

      {current && (
        <TourPopover
          targetSelector={current.target}
          step={step}
          total={steps.length}
          title={current.title}
          body={current.body}
          onClose={() => close()}
          onBack={() => setStep((v) => v - 1)}
          onNext={() => (step === steps.length - 1 ? close(true) : setStep((v) => v + 1))}
        />
      )}
    </>
  );
}
