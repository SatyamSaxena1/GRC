import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, downloadComplianceExport, getDashboard } from "../api/client";
import { useApi } from "../lib/useApi";
import { useSession } from "../lib/session";
import { Badge } from "../components/Badge";
import { PageTour } from "../components/PageTour";

const TOUR_STEPS = [
  {
    title: "Five numbers, one request",
    body: "Controls, gaps, tasks, evidence and open requests — all computed server-side and delivered in one call, so this page loads as one round trip instead of fanning out per control.",
    target: "[data-tour='stat-cards']",
  },
  {
    title: "Evidence reuse is the whole thesis",
    body: "One artefact can satisfy requirements across multiple frameworks. This is literally counting how many uploads that avoided.",
    target: "[data-tour='reuse-cards']",
  },
  {
    title: "Day-1 readiness",
    body: "Shows what a framework you haven't even subscribed to yet would already look like, using only evidence already on file — the preview badge marks frameworks you're not subscribed to.",
    target: "[data-tour='readiness']",
  },
] as const;

export function OverviewPage() {
  const { identity } = useSession();
  const [exportError, setExportError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const exportReport = async (format: "csv" | "xlsx") => {
    setExporting(true);
    setExportError(null);
    try {
      await downloadComplianceExport(format);
    } catch (err) {
      setExportError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    } finally {
      setExporting(false);
    }
  };

  // Everything below used to be 7 separate calls plus one GET /controls/{id}
  // per control (client-side fan-out) — now one round trip. See
  // app/routers/analytics.py::dashboard.
  const dashboard = useApi(() => getDashboard(), []);
  const data = dashboard.data;
  const needsAttention = data
    ? data.controls.by_verdict.PARTIAL + data.controls.by_verdict.FAIL + data.controls.by_verdict.NO_EVIDENCE
    : null;

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Workspace overview</h2>
          <p>Start with what needs attention, then drill into the exact evidence, gap, or control.</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn" disabled={exporting} onClick={() => exportReport("csv")}>
            {exporting ? "Preparing…" : "Download compliance report (CSV)"}
          </button>
          <button className="btn" disabled={exporting} onClick={() => exportReport("xlsx")}>
            {exporting ? "Preparing…" : "Download (XLSX)"}
          </button>
          <PageTour id="overview" steps={TOUR_STEPS} />
        </div>
      </div>

      {exportError && <div className="alert alert-error">{exportError}</div>}
      {dashboard.error && <div className="alert alert-error">{dashboard.error}</div>}

      {data && data.attention.total > 0 && (
        <Link to="/evidence" className="alert alert-error" style={{ display: "block", marginBottom: 20 }}>
          <strong>Needs attention:</strong>{" "}
          {[
            data.attention.expired.length > 0 && `${data.attention.expired.length} expired`,
            data.attention.expiring_soon.length > 0 &&
              `${data.attention.expiring_soon.length} expiring within ${data.attention.horizon_days} days`,
            data.attention.failed.length > 0 && `${data.attention.failed.length} failed to process`,
            data.attention.stuck.length > 0 && `${data.attention.stuck.length} stuck mid-upload`,
          ].filter(Boolean).join(" · ")}
          {" — see Evidence"}
        </Link>
      )}

      <div className="card-grid" data-tour="stat-cards">
        <Link to="/controls" className="card stat-card action-card">
          <div className="stat-label">Controls tracked</div>
          <div className="stat-value">{data?.controls.total ?? "—"}</div>
          <div className="stat-sub">{data?.controls.locked ?? 0} locked by an auditor</div>
        </Link>
        <Link to="/gaps" className="card stat-card action-card">
          <div className="stat-label">Open gaps</div>
          <div className="stat-value">{data?.gaps_open ?? "—"}</div>
          <div className="stat-sub">Specific evidence shortfalls to resolve</div>
        </Link>
        <Link to="/tasks" className="card stat-card action-card">
          <div className="stat-label">Open remediation tasks</div>
          <div className="stat-value">{data?.tasks_open ?? "—"}</div>
          <div className="stat-sub">One task is created for each active gap</div>
        </Link>
        <Link to="/evidence" className="card stat-card action-card">
          <div className="stat-label">Evidence ready</div>
          <div className="stat-value">{data?.evidence.ready ?? "—"}</div>
          <div className="stat-sub">of {data?.evidence.total ?? "—"} current artefacts analysed</div>
        </Link>
        <div className="card stat-card">
          <div className="stat-label">{identity?.kind === "auditor" ? "Open requests you've sent" : "Requests from your auditor"}</div>
          <div className="stat-value">{data?.requests_open ?? "—"}</div>
          <div className="stat-sub">Evidence and unlock requests awaiting a response — see each control's Discussion</div>
        </div>
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
      <div className="card-grid" data-tour="reuse-cards">
        <div className="card stat-card">
          <div className="stat-label">Evidence reuse rate</div>
          <div className="stat-value">{data ? `${Math.round(data.reuse.reuse_rate * 100)}%` : "—"}</div>
          <div className="stat-sub">
            {data ? `${data.reuse.avoided_uploads} uploads avoided across ${data.reuse.distinct_evidence} artefact(s)` : "loading…"}
          </div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">Effort saved</div>
          <div className="stat-value">{data ? `${data.reuse.effort_hours_saved}h` : "—"}</div>
          <div className="stat-sub">at the configured hours-per-artefact rate</div>
        </div>
      </div>

      {data && (
        <>
          <div className="section-title">Controls by verdict</div>
          <div className="card">
            <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
              {(["PASS", "PARTIAL", "FAIL", "NO_EVIDENCE"] as const).map((v) => (
                <div key={v}>
                  <Badge value={v} />
                  <div style={{ fontSize: 22, fontWeight: 700, marginTop: 6 }}>{data.controls.by_verdict[v] ?? 0}</div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      <div className="section-title">Framework readiness</div>
      <div className="card-grid" data-tour="readiness">
        {data?.readiness.map((r) => (
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
