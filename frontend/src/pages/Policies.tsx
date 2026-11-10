import { useState } from "react";
import {
  ApiError, acceptPolicy, addPolicy, approvePolicy, editPolicy, getPolicy, listPolicies, listPolicyTemplates,
  type Policy,
} from "../api/client";
import { useApi } from "../lib/useApi";

const REVIEW_LABEL: Record<Policy["review"], string> = {
  NOT_APPROVED: "Not approved yet", CURRENT: "Current", DUE_SOON: "Review due soon", OVERDUE: "Review overdue",
};

/** The organisation's own policies (ADR-056): an admin writes and approves, each person accepts for themselves, and a
 *  change to the text is a new version that everyone accepts again. The server decides who may do what; `can_manage`
 *  only chooses which buttons to draw. */
export function PoliciesPage() {
  const state = useApi(() => listPolicies(), []);
  const templates = useApi(() => listPolicyTemplates(), []);
  const [open, setOpen] = useState<Policy | null>(null);
  const [draft, setDraft] = useState<{ title: string; body: string } | null>(null);   // editing the open policy
  const [fresh, setFresh] = useState({ template: "", title: "", body: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<Policy | void>) => {
    setError(null);
    setBusy(true);
    try {
      const result = await fn();
      if (result) setOpen((cur) => (cur && cur.id === result.id ? { ...cur, ...result } : cur));
      state.reload();
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    } finally { setBusy(false); }
  };
  if (state.error) return <div className="alert alert-error">{state.error}</div>;
  if (!state.data) return <p className="muted">Loading…</p>;
  const { can_manage: admin, policies } = state.data;
  const mine = policies.filter((p) => p.status === "APPROVED" && !p.accepted_by_me).length;

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Policies</h2>
          <p>
            Your organisation's own policies. An admin approves each version, and every person accepts it for
            themselves. Change the text and it becomes a new version that everyone accepts again.
          </p>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {mine > 0 && <div className="alert alert-info">{mine === 1 ? "One policy is" : `${mine} policies are`} waiting for you to read and accept.</div>}

      <table className="data-table static">
        <thead><tr><th>Policy</th><th>Version</th><th>Status</th><th>Review</th><th>Accepted</th><th /></tr></thead>
        <tbody>
          {policies.length === 0 && (
            <tr><td colSpan={6} className="muted">{admin ? "No policies yet. Add the first one below." : "No approved policies yet."}</td></tr>
          )}
          {policies.map((p) => (
            <tr key={p.id}>
              <td><strong>{p.title}</strong></td>
              <td>v{p.version}</td>
              <td><span className={`badge ${p.status === "APPROVED" ? "badge-pass" : "badge-skipped"}`}>{p.status === "APPROVED" ? "approved" : "draft"}</span></td>
              <td>{REVIEW_LABEL[p.review]}{p.review_due && p.review !== "NOT_APPROVED" && <span className="muted"> by {p.review_due}</span>}</td>
              <td>{p.status === "APPROVED" ? `${p.accepted} of ${p.people}` : <span className="muted">after approval</span>}</td>
              <td>
                <button className="btn btn-sm" disabled={busy}
                  onClick={() => { setDraft(null); void run(async () => { setOpen(await getPolicy(p.id)); }); }}>
                  {p.status === "APPROVED" && !p.accepted_by_me ? "Read and accept" : "Open"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {open && (
        <div className="card" style={{ marginTop: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12 }}>
            <strong>{open.title} <span className="muted">v{open.version}</span></strong>
            <button className="btn btn-sm" onClick={() => { setOpen(null); setDraft(null); }}>Close</button>
          </div>
          {open.approved_at && <p className="stat-sub">Approved {new Date(open.approved_at).toLocaleDateString()}. Review due {open.review_due}.</p>}

          {draft ? (
            <>
              <label htmlFor="pol-title">Title</label>
              <input id="pol-title" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
              <label htmlFor="pol-body" style={{ marginTop: 8 }}>Text</label>
              <textarea id="pol-body" rows={16} value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
              <p className="stat-sub">Saving a change makes version {open.version + 1}. It needs approval again, and everyone accepts it again.</p>
              <button className="btn btn-primary" disabled={busy}
                onClick={() => run(async () => { const p = await editPolicy(open.id, draft); setDraft(null); return p; })}>
                Save as a new version
              </button>{" "}
              <button className="btn" onClick={() => setDraft(null)}>Cancel</button>
            </>
          ) : (
            <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: 14, maxHeight: 420, overflow: "auto" }}>{open.body}</pre>
          )}

          {!draft && (
            <div style={{ marginTop: 8 }}>
              {open.status === "APPROVED" && (open.accepted_by_me
                ? <span className="badge badge-pass">You accepted this version</span>
                : <button className="btn btn-primary" disabled={busy} onClick={() => run(() => acceptPolicy(open.id, open.version))}>I have read and accept this policy</button>)}
              {admin && open.status !== "APPROVED" && (
                <button className="btn btn-primary" disabled={busy} onClick={() => run(() => approvePolicy(open.id, open.version))}>Approve this version</button>
              )}{" "}
              {admin && <button className="btn" disabled={busy} onClick={() => setDraft({ title: open.title, body: open.body ?? "" })}>Edit</button>}
            </div>
          )}
          {admin && open.status === "APPROVED" && (open.waiting_on ?? []).length > 0 && (
            <details style={{ marginTop: 10 }}>
              <summary>Still to accept: {open.waiting_on!.length}</summary>
              <ul style={{ fontSize: 13, margin: "6px 0 0 18px" }}>{open.waiting_on!.map((e) => <li key={e}>{e}</li>)}</ul>
            </details>
          )}
        </div>
      )}

      {admin && (
        <div className="card" style={{ marginTop: 16 }}>
          <strong>Add a policy</strong>
          <p className="stat-sub">Start from a template whose figures already meet every framework's rules, or paste your own text.</p>
          <label htmlFor="pol-template">Start from</label>
          <select id="pol-template" value={fresh.template} onChange={(e) => setFresh({ ...fresh, template: e.target.value })}>
            <option value="">My own text</option>
            {(templates.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
          </select>
          {!fresh.template && (
            <>
              <label htmlFor="new-title" style={{ marginTop: 8 }}>Title</label>
              <input id="new-title" value={fresh.title} onChange={(e) => setFresh({ ...fresh, title: e.target.value })} />
              <label htmlFor="new-body" style={{ marginTop: 8 }}>Text</label>
              <textarea id="new-body" rows={8} value={fresh.body} onChange={(e) => setFresh({ ...fresh, body: e.target.value })} />
            </>
          )}
          <div style={{ marginTop: 8 }}>
            <button className="btn btn-primary"
              disabled={busy || (!fresh.template && (fresh.title.trim().length < 3 || fresh.body.trim().length < 20))}
              onClick={() => run(async () => {
                const p = await addPolicy(fresh.template ? { template_id: fresh.template } : { title: fresh.title.trim(), body: fresh.body });
                setFresh({ template: "", title: "", body: "" });
                setDraft(null);
                setOpen(p);
              })}>
              Add as a draft
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
