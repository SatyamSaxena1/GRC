import { getActivity } from "../api/client";
import { useApi } from "../lib/useApi";
import { PageTour } from "../components/PageTour";
import { AuditIntegrity } from "../components/AuditIntegrity";
import { useSession } from "../lib/session";

const TOUR_STEPS = [
  {
    title: "The append-only trail",
    body: "Every state-changing action in your workspace lands here, newest first — uploads, verdicts, locks, task assignments. Nothing is ever edited or removed from this log, so it's the record an audit can rely on.",
    target: ".timeline",
  },
] as const;

// Same rendering as the per-control/per-evidence history views (ControlDetail.tsx,
// EvidenceDetail.tsx) — just not scoped to one entity. See app/routers/activity.py.
export function ActivityPage() {
  const activity = useApi(() => getActivity(), []);
  const { identity } = useSession();
  // Same test App.tsx uses: a stub auditor token, or a signed-in user acting under an engagement.
  const isAuditor = identity?.kind === "auditor" || (identity?.kind === "oidc" && Boolean(identity.engagementId));

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Activity</h2>
          <p>Everything that happened across your workspace, most recent first.</p>
        </div>
        <PageTour id="activity" steps={TOUR_STEPS} />
      </div>
      <AuditIntegrity isAuditor={isAuditor} />
      {activity.error && <div className="alert alert-error">{activity.error}</div>}
      <ul className="timeline">
        {activity.data?.map((e, i) => (
          <li key={i}>
            <div className="ts">{new Date(e.at).toLocaleString()}</div>
            <strong>{e.action}</strong> by {e.actor}
            {e.reason && <span className="muted"> — {e.reason}</span>}
          </li>
        ))}
        {activity.data?.length === 0 && <li className="muted">No activity yet.</li>}
      </ul>
    </div>
  );
}
