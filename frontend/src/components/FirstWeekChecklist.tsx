import { Link } from "react-router-dom";
import { getOnboarding } from "../api/client";
import { useApi } from "../lib/useApi";

/** The organisation admin's first-week checklist (ADR-058). Every step is read from real data on the server, so
 *  nothing here can be ticked by hand and undoing the work unticks it. It draws nothing while loading, for anyone the
 *  server does not show it to (it answers 403 to everyone but an organisation admin), and once the required steps
 *  are done. */
export function FirstWeekChecklist() {
  const checklist = useApi(() => getOnboarding(), []);
  const data = checklist.data;
  if (!data || data.complete) return null;
  const minutes = data.first_verdict.minutes_from_start;

  return (
    <div className="card" data-tour="first-week" style={{ marginBottom: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <strong>Your first week</strong>
        <span className="stat-sub">{data.done} of {data.total} done</span>
      </div>
      <div className="readiness-bar" role="progressbar" aria-valuemin={0} aria-valuemax={data.total} aria-valuenow={data.done} aria-label="First-week steps done">
        <div style={{ width: `${(data.done / data.total) * 100}%` }} />
      </div>
      <ul className="checklist">
        {data.steps.map((step) => (
          <li key={step.id} className={step.done ? "is-done" : undefined}>
            <span className="checklist__mark" role="img" aria-label={step.done ? "Done" : "Not done yet"}>{step.done ? "✓" : "○"}</span>
            <span>
              <Link to={step.link}>{step.title}</Link>
              {step.optional && <span className="stat-sub"> (only if needed)</span>}
              <span className="checklist__hint">{step.hint}</span>
            </span>
          </li>
        ))}
      </ul>
      {minutes !== null && (
        <p className="stat-sub" style={{ marginTop: 12 }}>
          Your first verdict arrived {minutes === 0 ? "within a minute" : `${minutes} minute${minutes === 1 ? "" : "s"}`} after the workspace was created.
        </p>
      )}
    </div>
  );
}
