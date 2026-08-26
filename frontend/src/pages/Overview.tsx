import { useMemo } from "react";
import { Link } from "react-router-dom";
import {
  getControl,
  getReadinessAll,
  getReuseStats,
  listControls,
  listEvidence,
  listGaps,
  listTasks,
  type ControlDetail,
} from "../api/client";
import { useApi } from "../lib/useApi";
import { Badge } from "../components/Badge";

const VERDICT_RANK: Record<string, number> = { PASS: 3, PARTIAL: 2, FAIL: 1 };

function bestVerdict(control: ControlDetail): string {
  if (control.links.length === 0) return "NO_EVIDENCE";
  return control.links.reduce((best, link) => {
    const rank = VERDICT_RANK[link.verdict] ?? 0;
    return rank > (VERDICT_RANK[best] ?? -1) ? link.verdict : best;
  }, control.links[0].verdict);
}

export function OverviewPage() {
  const reuse = useApi(() => getReuseStats(), []);
  const readiness = useApi(() => getReadinessAll(), []);
  const evidence = useApi(() => listEvidence({ lifecycle_status: "CURRENT" }), []);
  const gaps = useApi(() => listGaps("OPEN"), []);
  const tasks = useApi(() => listTasks({ status: "OPEN" }), []);
  const controls = useApi(async () => {
    const summaries = await listControls();
    return Promise.all(summaries.map((c) => getControl(c.id)));
  }, []);

  const distribution = useMemo(() => {
    if (!controls.data) return null;
    const counts: Record<string, number> = { PASS: 0, PARTIAL: 0, FAIL: 0, NO_EVIDENCE: 0 };
    for (const c of controls.data) counts[bestVerdict(c)] = (counts[bestVerdict(c)] ?? 0) + 1;
    const lockedCount = controls.data.filter((c) => c.locked).length;
    return { counts, total: controls.data.length, lockedCount };
  }, [controls.data]);

  const readyEvidence = evidence.data?.filter((row) => row.status === "READY").length;
  const needsAttention = distribution
    ? distribution.counts.PARTIAL + distribution.counts.FAIL + distribution.counts.NO_EVIDENCE
    : null;

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Workspace overview</h2>
          <p>Start with what needs attention, then drill into the exact evidence, gap, or control.</p>
        </div>
      </div>

      <div className="card-grid">
        <Link to="/controls" className="card stat-card action-card">
          <div className="stat-label">Controls tracked</div>
          <div className="stat-value">{distribution?.total ?? "—"}</div>
          <div className="stat-sub">{distribution?.lockedCount ?? 0} locked by an auditor</div>
        </Link>
        <Link to="/gaps" className="card stat-card action-card">
          <div className="stat-label">Open gaps</div>
          <div className="stat-value">{gaps.data?.length ?? "—"}</div>
          <div className="stat-sub">Specific evidence shortfalls to resolve</div>
        </Link>
        <Link to="/tasks" className="card stat-card action-card">
          <div className="stat-label">Open remediation tasks</div>
          <div className="stat-value">{tasks.data?.length ?? "—"}</div>
          <div className="stat-sub">One task is created for each active gap</div>
        </Link>
        <Link to="/evidence" className="card stat-card action-card">
          <div className="stat-label">Evidence ready</div>
          <div className="stat-value">{readyEvidence ?? "—"}</div>
          <div className="stat-sub">of {evidence.data?.length ?? "—"} current artefacts analysed</div>
        </Link>
      </div>

      <div className="section-title">Priority work</div>
      <div className="card-grid">
        <Link to="/controls" className="card action-card">
          <strong>Controls needing attention</strong>
          <div className="stat-value" style={{ marginTop: 8 }}>{needsAttention ?? "—"}</div>
          <div className="stat-sub">Partial, failed, or not-yet-evidenced controls.</div>
        </Link>
        <Link to="/gaps" className="card action-card">
          <strong>Review exact fixes</strong>
          <div className="stat-sub" style={{ marginTop: 8 }}>Every open gap shows the observed value and the required value.</div>
        </Link>
        <Link to="/evidence" className="card action-card">
          <strong>Upload revised evidence</strong>
          <div className="stat-sub" style={{ marginTop: 8 }}>A corrected version automatically re-evaluates the affected requirements.</div>
        </Link>
      </div>

      <div className="section-title">Evidence intelligence</div>
      <div className="card-grid">
        <div className="card stat-card">
          <div className="stat-label">Evidence reuse rate</div>
          <div className="stat-value">{reuse.data ? `${Math.round(reuse.data.reuse_rate * 100)}%` : "—"}</div>
          <div className="stat-sub">
            {reuse.data ? `${reuse.data.avoided_uploads} uploads avoided across ${reuse.data.distinct_evidence} artefact(s)` : "loading…"}
          </div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">Effort saved</div>
          <div className="stat-value">{reuse.data ? `${reuse.data.effort_hours_saved}h` : "—"}</div>
          <div className="stat-sub">at the configured hours-per-artefact rate</div>
        </div>
      </div>

      {distribution && (
        <>
          <div className="section-title">Controls by verdict</div>
          <div className="card">
            <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
              {(["PASS", "PARTIAL", "FAIL", "NO_EVIDENCE"] as const).map((v) => (
                <div key={v}>
                  <Badge value={v} />
                  <div style={{ fontSize: 22, fontWeight: 700, marginTop: 6 }}>{distribution.counts[v] ?? 0}</div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      <div className="section-title">Framework readiness</div>
      {readiness.error && <div className="alert alert-error">{readiness.error}</div>}
      <div className="card-grid">
        {readiness.data?.map((r) => (
          <div key={r.framework} className="card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <strong>{r.framework}</strong>
              {r.already_subscribed ? (
                <span className="badge badge-pass">subscribed</span>
              ) : (
                <span className="badge badge-partial">day-1 preview</span>
              )}
            </div>
            <div className="readiness-bar">
              <div style={{ width: `${Math.round(r.readiness * 100)}%` }} />
            </div>
            <div className="stat-sub" style={{ marginTop: 6 }}>
              {Math.round(r.readiness * 100)}% ready — {r.satisfied} of {r.total_requirements} requirements
              satisfied{!r.already_subscribed && " by evidence already on file"}
            </div>
          </div>
        ))}
      </div>

      <div className="section-title">All workspace areas</div>
      <div className="card-grid">
        <Link to="/evidence" className="card">
          <strong>Upload evidence</strong>
          <div className="stat-sub">Add a document and see it evaluated against every subscribed framework.</div>
        </Link>
        <Link to="/gaps" className="card">
          <strong>Review open gaps</strong>
          <div className="stat-sub">Every unmet requirement, with the exact fix needed.</div>
        </Link>
        <Link to="/controls" className="card">
          <strong>Browse controls</strong>
          <div className="stat-sub">See what's assigned, evidenced, and locked.</div>
        </Link>
      </div>
    </div>
  );
}
