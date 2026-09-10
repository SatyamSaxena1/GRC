import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError, getReadiness, listConnectors, syncConnector, type ConnectorStatus,
} from "../api/client";
import { Badge } from "../components/Badge";
import { useApi } from "../lib/useApi";

export function DpdpPage() {
  const readiness = useApi(() => getReadiness("DPDP"), []);
  const connectors = useApi(() => listConnectors(), []);
  const [syncing, setSyncing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const report = readiness.data;
  const score = Math.round((report?.readiness ?? 0) * 100);

  useEffect(() => {
    if (!connectors.data?.some((item) => !["READY", "FAILED", "NEEDS_REVIEW", "NEVER_SYNCED"].includes(item.status))) return;
    const id = window.setInterval(() => {
      connectors.reload();
      readiness.reload();
    }, 2_000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectors.data]);

  const sync = async (source: ConnectorStatus["source"]) => {
    setSyncing(source);
    setError(null);
    try {
      await syncConnector(source);
      connectors.reload();
      readiness.reload();
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    } finally {
      setSyncing(null);
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>DPDP readiness assessment</h2>
          <p>Evidence-backed preparation for the DPDP Act 2023 and Rules 2025.</p>
        </div>
        <button className="btn" onClick={() => window.print()}>Print score report</button>
      </div>

      <div className="alert">
        <strong>Readiness, not legal certification.</strong>{" "}
        Most substantive duties in this pack take effect on 14 May 2027. The score covers
        document-verifiable controls and four implementation checks; applicability,
        exemptions, consent validity and legal interpretation still require counsel.
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {readiness.error && <div className="alert alert-error">{readiness.error}</div>}

      <div className="card-grid">
        <div className="card stat-card">
          <div className="stat-label">DPDP readiness score</div>
          <div className="stat-value">{report ? `${score}%` : "—"}</div>
          <div className="readiness-bar"><div style={{ width: `${score}%` }} /></div>
          <div className="stat-sub">
            {report ? `${report.satisfied} of ${report.total_requirements} checks evidenced` : "Loading evidence…"}
          </div>
        </div>
        <div className="card">
          <strong>What moves the score</strong>
          <p className="stat-sub">
            Uploaded policies and privacy notices plus fresh snapshots from AWS, Microsoft
            365, Google Workspace and HRMS. A connector that has never synced contributes no evidence.
          </p>
          <Link className="btn" to="/evidence">Add document evidence</Link>
        </div>
      </div>

      <div className="section-title">Automatic evidence sources</div>
      <div className="card-grid">
        {connectors.data?.map((connector) => (
          <div className="card" key={connector.source}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <strong>{connector.label}</strong>
              <Badge value={connector.configured ? connector.status : "NOT_CONFIGURED"} />
            </div>
            <p className="stat-sub">
              {connector.last_synced_at
                ? `Last collected ${new Date(connector.last_synced_at).toLocaleString()}`
                : connector.configured
                  ? "Configured, but no evidence has been collected yet."
                  : "Requires a server-side collector URL and its least-privilege credential."}
            </p>
            <button
              className="btn btn-primary"
              disabled={!connector.configured || syncing === connector.source}
              onClick={() => sync(connector.source)}
            >
              {syncing === connector.source ? "Collecting…" : "Collect evidence"}
            </button>
          </div>
        ))}
      </div>
      <p className="muted">
        The collector contract is real automatic ingestion, but not a turnkey vendor integration:
        each configured endpoint must translate that system's API into the supported attributes.
        HRMS is necessarily adapter-based because there is no common HRMS API. There is not yet
        a “not applicable” scope control, so an unused source still counts as no evidence.
      </p>

      <div className="section-title">Score report</div>
      <div className="card">
        <table className="data-table">
          <thead><tr><th>Requirement</th><th>Assessment</th></tr></thead>
          <tbody>
            {report?.clauses.map((clause) => (
              <tr key={clause.clause}>
                <td><strong>{clause.clause}</strong><div className="stat-sub">{clause.title}</div></td>
                <td><Badge value={clause.verdict} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
