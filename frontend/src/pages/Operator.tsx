import { useState } from "react";
import { ApiError, operatorListOrgs, operatorSetPlan, type OperatorOrg } from "../api/client";

const PLANS = ["TRIAL", "DPDP_STARTER", "GROWTH", "SCALE"];
const message = (err: unknown) => (err instanceof ApiError ? String(err.detail) : (err as Error).message);

/** Operator-only: set an organisation's plan (ADR-054). Not linked from any menu. The gate is the server's admin key,
 *  which is typed in here and kept in memory only; this page decides nothing about who may change a plan. */
export function OperatorPage() {
  const [key, setKey] = useState("");
  const [orgs, setOrgs] = useState<OperatorOrg[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setError(null);
    try { setOrgs(await operatorListOrgs(key)); } catch (err) { setOrgs(null); setError(message(err)); }
  };
  const setPlan = async (id: string, plan: string) => {
    setError(null);
    try { await operatorSetPlan(key, id, plan); await load(); } catch (err) { setError(message(err)); }
  };

  return (
    <div style={{ maxWidth: 900, margin: "40px auto", padding: "0 16px" }}>
      <h2>Operator: plans</h2>
      <p className="stat-sub">
        Choose an organisation's plan. Moving to a smaller plan never removes anything; it only stops further additions.
        A trial that has ended makes the workspace read-only until you move it to a plan.
      </p>
      <form onSubmit={(e) => { e.preventDefault(); load(); }} style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <input type="password" aria-label="Operator key" placeholder="Operator key" value={key}
               onChange={(e) => setKey(e.target.value)} autoComplete="off" />
        <button className="btn" type="submit">Show organisations</button>
      </form>
      {error && <div className="alert alert-error">{error}</div>}
      {orgs && (
        <table className="data-table static">
          <thead><tr><th>Organisation</th><th>Plan</th><th>Frameworks</th><th>Seat limit</th><th>Trial ends</th><th>First verdict</th></tr></thead>
          <tbody>
            {orgs.map((o) => (
              <tr key={o.id}>
                <td>{o.name}</td>
                <td>
                  <select aria-label={`Plan for ${o.name}`} value={o.plan ?? ""} onChange={(e) => e.target.value && setPlan(o.id, e.target.value)}>
                    <option value="">No plan (no limits)</option>
                    {PLANS.map((p) => <option key={p} value={p}>{p.replace("_", " ")}</option>)}
                  </select>
                </td>
                <td>{o.frameworks.length}{o.frameworks_limit !== null ? ` of ${o.frameworks_limit}` : ""}</td>
                <td>{o.seats_limit ?? "no limit"}</td>
                <td>{o.trial_ends_at ? `${new Date(o.trial_ends_at).toLocaleDateString()}${o.trial_over ? " (ended)" : ""}` : "-"}</td>
                <td title="Minutes from the workspace being created to its first verdict (ADR-058)">
                  {o.minutes_to_first_verdict !== null ? `${o.minutes_to_first_verdict} min` : o.created_at && !o.first_verdict_at ? "not yet" : "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
