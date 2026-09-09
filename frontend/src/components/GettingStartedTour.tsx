import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useSession } from "../lib/session";

type TourStep = {
  title: string;
  body: string;
  path: string;
  target: string;
  action: string;
};

type Tour = {
  id: string;
  title: string;
  description: string;
  steps: readonly TourStep[];
};

const TOURS: readonly Tour[] = [
  {
    id: "workspace",
    title: "Explore your workspace",
    description: "A quick tour of the core compliance workflow.",
    steps: [
      { title: "Start with the big picture", body: "Overview brings readiness, open gaps, tasks, and evidence health together. Click the highlighted navigation item to continue.", path: "/overview", target: '[data-tour="nav-overview"]', action: "Click Overview" },
      { title: "See the requirements", body: "Controls shows every requirement, its verdict, linked evidence, and audit lock status.", path: "/controls", target: '[data-tour="nav-controls"]', action: "Click Controls" },
      { title: "Find exact shortfalls", body: "Gaps explains what was observed, what was required, and which evidence needs correction.", path: "/gaps", target: '[data-tour="nav-gaps"]', action: "Click Gaps" },
      { title: "Track the fix", body: "Tasks turns each shortfall into owned, trackable remediation work.", path: "/tasks", target: '[data-tour="nav-tasks"]', action: "Click Tasks to finish" },
    ],
  },
  {
    id: "evidence",
    title: "Evidence to resolution",
    description: "Follow proof from upload through remediation.",
    steps: [
      { title: "Collect proof once", body: "Upload policies, scans, reports, or screenshots here. GRC evaluates each artefact against relevant controls.", path: "/evidence", target: '[data-tour="nav-evidence"]', action: "Click Evidence" },
      { title: "Review the result", body: "Controls combines linked proof into a current verdict for each requirement.", path: "/controls", target: '[data-tour="nav-controls"]', action: "Click Controls" },
      { title: "Complete remediation", body: "Use Tasks to assign the correction. Evidence-backed tasks close automatically when a new upload resolves the gap.", path: "/tasks", target: '[data-tour="nav-tasks"]', action: "Click Tasks to finish" },
    ],
  },
  {
    id: "firm",
    title: "Run the audit firm",
    description: "Onboard a client, then decide who on your staff may work it.",
    steps: [
      { title: "Start at your book of clients", body: "The firm console is the other side of the table from everything else in this app: many clients rather than one organisation. It opens with whoever is waiting on a decision from you.", path: "/firm", target: '[data-tour="nav-firm"]', action: "Click Firm console" },
      { title: "Approve, and the client comes into existence", body: "A prospect's request owns nothing yet \u2014 no organisation, no engagement, no login. Approving is what creates all three, and you can narrow the frameworks they asked for before you do.", path: "/firm", target: '[data-tour="firm-onboarding"]', action: "Review the onboarding queue" },
      { title: "Staff the people who may see it", body: "Belonging to your firm grants nobody access to a client. Assigning an auditor here is the grant \u2014 remove the row and their access to that client is gone on the next request, enforced server-side.", path: "/firm", target: '[data-tour="firm-clients"]', action: "Assign an auditor to a client" },
    ],
  },
  {
    id: "setup",
    title: "Set up a control owner",
    description: "Create a person, control, and least-privilege assignment.",
    steps: [
      { title: "Open administration", body: "Admin contains the setup tools for your organisation.", path: "/admin", target: '[data-tour="nav-admin"]', action: "Click Admin" },
      { title: "Invite the owner", body: "Create the person who operates the process and will supply its proof. Click the highlighted card to continue.", path: "/admin", target: "#invite-user", action: "Click Invite a team member" },
      { title: "Register the requirement", body: "Register the framework control that will be tested.", path: "/admin", target: "#register-control", action: "Click Register a control" },
      { title: "Grant least-privilege access", body: "Assigning the control lets its owner see this work without gaining organisation-wide access.", path: "/admin", target: "#assign-control", action: "Click Assign a control to finish" },
    ],
  },
];

const completeKey = (id: string) => `grc:guided-tour:${id}:complete`;

export function GettingStartedTour() {
  const { identity } = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const [chooserOpen, setChooserOpen] = useState(false);
  const [activeTour, setActiveTour] = useState<Tour | null>(null);
  const [step, setStep] = useState(0);
  const dialogRef = useRef<HTMLDivElement>(null);
  const current = activeTour?.steps[step];
  const isAuditor = identity?.kind === "auditor" || (identity?.kind === "oidc" && Boolean(identity.engagementId));
  // A firm user has not opened a client yet, so the auditee-shaped tours would
  // walk them into screens they cannot reach; the firm tour is the one that
  // matches what they can actually do from here.
  const isFirmSide = identity?.kind === "firm"
    || (identity?.kind === "user" && Boolean(identity.engagementId));
  const availableTours = isFirmSide
    ? TOURS.filter((tour) => tour.id === "firm" || tour.id === "workspace")
    : identity?.kind === "user"
      ? TOURS.filter((tour) => tour.id === "evidence")
      : isAuditor
        ? TOURS.filter((tour) => tour.id === "workspace")
        : TOURS.filter((tour) => tour.id !== "firm");

  const close = (complete = false) => {
    if (complete && activeTour) localStorage.setItem(completeKey(activeTour.id), "true");
    document.querySelector(".tour-target")?.classList.remove("tour-target");
    setActiveTour(null);
    setChooserOpen(false);
  };

  const advance = () => {
    if (!activeTour) return;
    if (step === activeTour.steps.length - 1) close(true);
    else setStep((value) => value + 1);
  };

  useEffect(() => {
    if (!current) return;
    if (location.pathname !== current.path) {
      navigate(current.path);
      return;
    }
    let target: Element | null = null;
    const timer = window.setTimeout(() => {
      target = document.querySelector(current.target);
      target?.classList.add("tour-target");
      target?.scrollIntoView({ behavior: "smooth", block: "center" });
      target?.addEventListener("click", advance);
      dialogRef.current?.focus();
    }, 50);
    return () => {
      window.clearTimeout(timer);
      target?.classList.remove("tour-target");
      target?.removeEventListener("click", advance);
    };
  // advance intentionally reflects the currently rendered step.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, location.pathname, navigate]);

  const start = (tour: Tour) => {
    setChooserOpen(false);
    setStep(0);
    setActiveTour(tour);
  };

  return (
    <>
      <button className="tour-launcher" onClick={() => setChooserOpen(true)} aria-label="Open guided tours">
        <span aria-hidden="true">?</span> Guided tours
      </button>

      {chooserOpen && !activeTour && (
        <div className="tour-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && close()}>
          <div className="tour-dialog tour-picker" role="dialog" aria-modal="true" aria-labelledby="tour-picker-title">
            <button className="tour-close" onClick={() => close()} aria-label="Close guided tours">×</button>
            <span className="eyebrow">Learn by doing</span>
            <h3 id="tour-picker-title">Choose a guided tour</h3>
            <p>Click through real parts of the workspace. You can leave or replay a tour at any time.</p>
            <div className="tour-list">
              {availableTours.map((tour) => (
                <button key={tour.id} onClick={() => start(tour)}>
                  <strong>{tour.title}</strong>
                  <span>{tour.description}</span>
                  <small>{tour.steps.length} steps{localStorage.getItem(completeKey(tour.id)) ? " · Completed" : ""}</small>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {activeTour && current && (
        <div className="tour-clickthrough-layer" role="presentation">
          <div className="tour-dialog tour-coachmark" role="dialog" aria-labelledby="tour-title" ref={dialogRef} tabIndex={-1} onKeyDown={(event) => event.key === "Escape" && close()}>
            <div className="tour-progress" aria-label={`Step ${step + 1} of ${activeTour.steps.length}`}>
              {activeTour.steps.map((item, index) => <span key={item.title} className={index <= step ? "complete" : ""} />)}
            </div>
            <button className="tour-close" onClick={() => close()} aria-label="Close guided tour">×</button>
            <span className="eyebrow">{activeTour.title} · {step + 1} of {activeTour.steps.length}</span>
            <h3 id="tour-title">{current.title}</h3>
            <p>{current.body}</p>
            <p className="tour-instruction">↖ {current.action}</p>
            <div className="tour-actions">
              <button className="btn" disabled={step === 0} onClick={() => setStep((value) => value - 1)}>Back</button>
              <button className="btn btn-primary" onClick={advance}>{step === activeTour.steps.length - 1 ? "Finish" : "Next instead"}</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
