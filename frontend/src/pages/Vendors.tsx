import { useState } from "react";
import {
  ApiError, addVendor, attachVendorReport, downloadVendorReport, listVendors, reviewVendor, updateVendor,
  type Vendor,
} from "../api/client";
import { useApi } from "../lib/useApi";

const STATE_LABEL: Record<Vendor["review"]["state"], string> = {
  NEVER_REVIEWED: "Never reviewed", OVERDUE: "Overdue", DUE_SOON: "Due soon", CURRENT: "Current", OFFBOARDED: "Offboarded",
};
const DATA = ["NONE", "INTERNAL", "PERSONAL", "SENSITIVE"];
const CRIT = ["LOW", "MEDIUM", "HIGH"];
const REPORT_TYPES: [string, string][] = [
  ["SOC2_TYPE2", "SOC 2 Type II"], ["SOC2_TYPE1", "SOC 2 Type I"], ["ISO27001", "ISO 27001 certificate"], ["OTHER", "Other document"],
];
const blank = { name: "", service: "", data_access: "NONE", criticality: "LOW", has_attestation: false };

/** Third parties you depend on (ADR-042). The tier is points from fixed rules, shown with its working so it
 *  is never a surprise; the tier sets how often the vendor is reviewed. */
export function VendorsPage() {
  const vendors = useApi(() => listVendors(), []);
  const [form, setForm] = useState(blank);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [openReports, setOpenReports] = useState<string | null>(null);
  const [reportForm, setReportForm] = useState({ type: "SOC2_TYPE2", until: "" });
  const [reportFile, setReportFile] = useState<{ vendorId: string; file: File } | null>(null);
  const [fileKey, setFileKey] = useState(0); // remount the file input to clear a chosen file
  const resetReportForm = () => { setReportFile(null); setReportForm({ type: "SOC2_TYPE2", until: "" }); setFileKey((k) => k + 1); };
  // Reports are permanent, so a half-filled form must never carry over from one vendor to another.
  const toggleReports = (id: string) => { resetReportForm(); setOpenReports(openReports === id ? null : id); };
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

      <table className="data-table static">
        <thead><tr><th>Vendor</th><th>Data</th><th>Criticality</th><th>Attestation</th><th>Tier</th><th>Review</th><th /></tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={7} className="muted">No vendors yet. Add the first one below.</td></tr>}
          {rows.map((v) => [
            <tr key={v.id} style={v.status === "OFFBOARDED" ? { opacity: 0.6 } : undefined}>
              <td><strong>{v.name}</strong><div className="muted" style={{ fontSize: 12 }}>{v.service}</div></td>
              <td>{v.data_access.toLowerCase()}</td>
              <td>{v.criticality.toLowerCase()}</td>
              <td>
                {v.attestation.source === "report" ? `report, valid to ${v.attestation.valid_until}`
                  : v.attestation.source === "manual" ? "ticked by hand" : "none"}
              </td>
              <td title={`${v.points} points`}>{v.tier} <span className="muted">({v.points})</span></td>
              <td>
                {STATE_LABEL[v.review.state]}
                {v.review.due && <div className="muted" style={{ fontSize: 12 }}>due {v.review.due}</div>}
              </td>
              <td>
                <button className="btn btn-sm" onClick={() => toggleReports(v.id)}>Reports ({v.reports.length})</button>{" "}
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
                    <button className="btn btn-sm btn-danger" onClick={() => run(() => updateVendor(v.id, { status: "OFFBOARDED" }))}>Offboard</button>
                  </>
                ))}
              </td>
            </tr>,
            openReports === v.id && (
              <tr key={v.id + "-reports"}>
                <td colSpan={7} style={{ background: "var(--neutral-bg)" }}>
                  <strong>Reports for {v.name}</strong>
                  <p className="muted" style={{ fontSize: 12, margin: "2px 0 8px" }}>
                    A SOC 2 or ISO 27001 report counts as an attestation until the date you give. Any other document is kept
                    on the record and never counts. Files cannot be deleted.
                  </p>
                  {v.reports.length === 0 && <p className="muted">No reports attached.</p>}
                  {v.reports.map((r) => (
                    <div key={r.id}>
                      <button type="button" className="link-btn" onClick={() => downloadVendorReport(v.id, r)}>{r.filename}</button>
                      <span className="muted"> {r.report_type.replace(/_/g, " ")}, valid to {r.valid_until},
                        {r.counts ? " counts as an attestation" : " does not count"}</span>
                    </div>
                  ))}
                  {v.status === "ACTIVE" && <div style={{ marginTop: 8 }}>
                    <select aria-label="Report type" value={reportForm.type} onChange={(e) => setReportForm({ ...reportForm, type: e.target.value })}>
                      {REPORT_TYPES.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                    </select>{" "}
                    <label>valid until <input type="date" value={reportForm.until}
                      onChange={(e) => setReportForm({ ...reportForm, until: e.target.value })} /></label>{" "}
                    <input key={`${v.id}-${fileKey}`} type="file" aria-label="Report file"
                      onChange={(e) => setReportFile(e.target.files?.[0] ? { vendorId: v.id, file: e.target.files[0] } : null)} />{" "}
                    <button className="btn btn-sm btn-primary"
                      disabled={reportFile?.vendorId !== v.id || !reportForm.until}
                      onClick={() => run(async () => {
                        if (reportFile?.vendorId !== v.id) return;
                        await attachVendorReport(v.id, reportFile.file, reportForm.type, reportForm.until);
                        resetReportForm();
                      })}>
                      Attach
                    </button>
                  </div>}
                  {v.status !== "ACTIVE" && <p className="muted" style={{ fontSize: 12 }}>Offboarded: reports can be read but not added.</p>}
                </td>
              </tr>
            ),
          ])}
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
