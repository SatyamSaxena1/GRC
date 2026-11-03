import { useState } from "react";
import { ApiError, addVendor, listVendors, reviewVendor, updateVendor, type Vendor } from "../api/client";
import { useApi } from "../lib/useApi";

const STATE_LABEL: Record<Vendor["review"]["state"], string> = {
  NEVER_REVIEWED: "Never reviewed", OVERDUE: "Overdue", DUE_SOON: "Due soon", CURRENT: "Current", OFFBOARDED: "Offboarded",
};
const DATA = ["NONE", "INTERNAL", "PERSONAL", "SENSITIVE"];
const CRIT = ["LOW", "MEDIUM", "HIGH"];
const blank = { name: "", service: "", data_access: "NONE", criticality: "LOW", has_attestation: false };

/** Third parties you depend on (ADR-042). The tier is points from fixed rules, shown with its working so it
 *  is never a surprise; the tier sets how often the vendor is reviewed. */
export function VendorsPage() {
  const vendors = useApi(() => listVendors(), []);
  const [form, setForm] = useState(blank);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try { await fn(); vendors.reload(); } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    }
  };
  if (vendors.error) return <div className="alert alert-error">{vendors.error}</div>;
  const rows = vendors.data ?? [];

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Vendors</h2>
          <p>Risk tier is points from fixed rules: what data they touch, how much you depend on them, and one more
            if they handle personal or sensitive data without a SOC 2 or ISO 27001 report on file. Higher tiers are
            reviewed more often (high 90 days, medium 180, low 365).</p>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}

      <table>
        <thead><tr><th>Vendor</th><th>Data</th><th>Criticality</th><th>Attestation</th><th>Tier</th><th>Review</th><th /></tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={7} className="muted">No vendors yet. Add the first one below.</td></tr>}
          {rows.map((v) => (
            <tr key={v.id} style={v.status === "OFFBOARDED" ? { opacity: 0.6 } : undefined}>
              <td><strong>{v.name}</strong><div className="muted" style={{ fontSize: 12 }}>{v.service}</div></td>
              <td>{v.data_access.toLowerCase()}</td>
              <td>{v.criticality.toLowerCase()}</td>
              <td>{v.has_attestation ? "on file" : "none"}</td>
              <td title={`${v.points} points`}>{v.tier} <span className="muted">({v.points})</span></td>
              <td>
                {STATE_LABEL[v.review.state]}
                {v.review.due && <div className="muted" style={{ fontSize: 12 }}>due {v.review.due}</div>}
              </td>
              <td>
                {v.status === "ACTIVE" && (reviewing === v.id ? (
                  <span>
                    <input aria-label={`Review note for ${v.name}`} value={note} onChange={(e) => setNote(e.target.value)}
                      placeholder="What did you check?" />{" "}
                    <button className="btn btn-sm btn-primary"
                      onClick={() => run(async () => { await reviewVendor(v.id, note); setReviewing(null); setNote(""); })}>Save</button>
                  </span>
                ) : (
                  <>
                    <button className="btn btn-sm" onClick={() => { setReviewing(v.id); setNote(""); }}>Mark reviewed</button>{" "}
                    <button className="btn btn-sm" onClick={() => run(() => updateVendor(v.id, { has_attestation: !v.has_attestation }))}>
                      {v.has_attestation ? "Remove attestation" : "Attestation on file"}
                    </button>{" "}
                    <button className="btn btn-sm btn-danger" onClick={() => run(() => updateVendor(v.id, { status: "OFFBOARDED" }))}>Offboard</button>
                  </>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="card" style={{ marginTop: 16 }}>
        <strong>Add a vendor</strong>
        <div className="form-grid">
          <div><label htmlFor="v-name">Name</label>
            <input id="v-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
          <div><label htmlFor="v-service">What they do for you</label>
            <input id="v-service" value={form.service} onChange={(e) => setForm({ ...form, service: e.target.value })} /></div>
          <div><label htmlFor="v-data">Data they can reach</label>
            <select id="v-data" value={form.data_access} onChange={(e) => setForm({ ...form, data_access: e.target.value })}>
              {DATA.map((d) => <option key={d} value={d}>{d.toLowerCase()}</option>)}</select></div>
          <div><label htmlFor="v-crit">How much you depend on them</label>
            <select id="v-crit" value={form.criticality} onChange={(e) => setForm({ ...form, criticality: e.target.value })}>
              {CRIT.map((c) => <option key={c} value={c}>{c.toLowerCase()}</option>)}</select></div>
          <label><input type="checkbox" checked={form.has_attestation}
            onChange={(e) => setForm({ ...form, has_attestation: e.target.checked })} /> A current SOC 2 or ISO 27001 report is on file</label>
          <button className="btn btn-primary" disabled={form.name.trim().length < 2}
            onClick={() => run(async () => { await addVendor(form); setForm(blank); })}>Add vendor</button>
        </div>
      </div>
    </div>
  );
}
