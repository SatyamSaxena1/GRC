import { useParams } from "react-router-dom";
import { getPublicTrust, type TrustSummary } from "../api/client";
import { useApi } from "../lib/useApi";

/** What the public sees: counts and percentages the organisation chose to share, nothing else. */
export function TrustView({ s }: { s: TrustSummary }) {
  const c = s.controls;
  const stat = (n: number, label: string) => (
    <div className="card" style={{ textAlign: "center", flex: "1 1 140px" }}>
      <div style={{ fontSize: 28, fontWeight: 700 }}>{n}</div>
      <div className="muted" style={{ fontSize: 13 }}>{label}</div>
    </div>
  );
  return (
    <div>
      <h2 style={{ marginBottom: 4 }}>{s.organisation}: security and compliance</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        {s.evidence_last_collected ? `Evidence last collected ${s.evidence_last_collected}. ` : ""}
        Figures are shared by {s.organisation} and come from its own compliance workspace.
      </p>

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", margin: "16px 0" }}>
        {stat(c.total, "controls tracked")}
        {stat(c.meeting_requirements, "meeting requirements")}
        {stat(c.partly_meeting, "partly meeting")}
        {stat(c.reviewed_and_locked_by_an_auditor, "reviewed and locked by an auditor")}
      </div>

      <h3>Frameworks</h3>
      {s.frameworks.length === 0 ? <p className="muted">None published.</p> : (
        <table>
          <thead><tr><th>Framework</th><th>Requirements met</th><th>Readiness</th></tr></thead>
          <tbody>
            {s.frameworks.map((f) => (
              <tr key={f.framework}>
                <td>{f.framework}</td>
                <td>{f.requirements_met} of {f.requirements}</td>
                <td>{f.readiness_percent}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3>How we decide</h3>
      <ul>{s.practices.map((p) => <li key={p}>{p}</li>)}</ul>
    </div>
  );
}

export function PublicTrustPage() {
  const { token = "" } = useParams();
  const page = useApi(() => getPublicTrust(token), [token]);
  return (
    <main style={{ maxWidth: 760, margin: "0 auto", padding: "32px 16px" }}>
      {page.loading && <p className="muted">Loading…</p>}
      {page.error && <p>This page is not available. The link may have been withdrawn.</p>}
      {page.data && <TrustView s={page.data} />}
    </main>
  );
}
