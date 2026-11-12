import { useState } from "react";
import {
  addTraining, ApiError, completeTraining, editTraining, getTraining, listTraining, listTrainingTemplates,
  type TrainingCourse,
} from "../api/client";
import { useApi } from "../lib/useApi";

const STATE_LABEL: Record<TrainingCourse["my_state"], string> = {
  NOT_DONE: "Not done yet", DONE: "Up to date", DUE_SOON: "Due soon", OVERDUE: "Overdue",
};
const STATE_BADGE: Record<TrainingCourse["my_state"], string> = {
  NOT_DONE: "badge-fail", DONE: "badge-pass", DUE_SOON: "badge-partial", OVERDUE: "badge-fail",
};

/** Training (ADR-063): short courses each person reads and confirms they understood, repeated on a cycle. It is a
 *  statement, not a test. The server decides who may do what; `can_manage` only chooses which buttons to draw. */
export function TrainingPage() {
  const state = useApi(() => listTraining(), []);
  const templates = useApi(() => listTrainingTemplates().catch(() => []), []);
  const [open, setOpen] = useState<TrainingCourse | null>(null);
  const [draft, setDraft] = useState<{ title: string; body: string } | null>(null);
  const [fresh, setFresh] = useState({ template: "", title: "", body: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<TrainingCourse | void>) => {
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
  const { can_manage: admin, courses } = state.data;
  const todo = courses.filter((c) => c.my_state !== "DONE").length;

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Training</h2>
          <p>
            Short courses every person reads and confirms they understood, repeated every year. Change a course's text and
            it becomes a new version that everyone confirms again. When you attest ISO 27001 A.6.3 or SOC 2 CC1.4 on the
            Frameworks page, this is what you point your auditor to.
          </p>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {todo > 0 && <div className="alert alert-info">{todo === 1 ? "One course is" : `${todo} courses are`} waiting for you.</div>}

      <table className="data-table static">
        <thead><tr><th>Course</th><th>Version</th><th>Your status</th><th>Up to date</th><th /></tr></thead>
        <tbody>
          {courses.length === 0 && (
            <tr><td colSpan={5} className="muted">{admin ? "No courses yet. Add the first one below." : "No courses yet."}</td></tr>
          )}
          {courses.map((c) => (
            <tr key={c.id}>
              <td><strong>{c.title}</strong></td>
              <td>v{c.version}</td>
              <td>
                <span className={`badge ${STATE_BADGE[c.my_state]}`}>{STATE_LABEL[c.my_state]}</span>
                {c.my_due && c.my_state !== "NOT_DONE" && <span className="muted"> next by {c.my_due}</span>}
              </td>
              <td>{c.up_to_date} of {c.people}</td>
              <td>
                <button className="btn btn-sm" disabled={busy}
                  onClick={() => { setDraft(null); void run(async () => { setOpen(await getTraining(c.id)); }); }}>
                  {c.my_state === "DONE" ? "Open" : "Read and confirm"}
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
          {draft ? (
            <>
              <label htmlFor="tr-title">Title</label>
              <input id="tr-title" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
              <label htmlFor="tr-body" style={{ marginTop: 8 }}>Text</label>
              <textarea id="tr-body" rows={16} value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
              <p className="stat-sub">Changing the text makes version {open.version + 1}, and everyone confirms it again.</p>
              <button className="btn btn-primary" disabled={busy}
                onClick={() => run(async () => { const c = await editTraining(open.id, draft); setDraft(null); return c; })}>
                Save
              </button>{" "}
              <button className="btn" onClick={() => setDraft(null)}>Cancel</button>
            </>
          ) : (
            <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: 14, maxHeight: 420, overflow: "auto" }}>{open.body}</pre>
          )}
          {!draft && (
            <div style={{ marginTop: 8 }}>
              {open.my_state === "DONE"
                ? <span className="badge badge-pass">You confirmed this version{open.my_due ? `, next by ${open.my_due}` : ""}</span>
                : <button className="btn btn-primary" disabled={busy} onClick={() => run(() => completeTraining(open.id, open.version))}>
                    I have read this and understood it
                  </button>}{" "}
              {admin && <button className="btn" disabled={busy} onClick={() => setDraft({ title: open.title, body: open.body ?? "" })}>Edit</button>}
            </div>
          )}
          {admin && (open.waiting_on ?? []).length > 0 && (
            <details style={{ marginTop: 10 }}>
              <summary>Still to do or overdue: {open.waiting_on!.length}</summary>
              <ul style={{ fontSize: 13, margin: "6px 0 0 18px" }}>{open.waiting_on!.map((e) => <li key={e}>{e}</li>)}</ul>
            </details>
          )}
        </div>
      )}

      {admin && (
        <div className="card" style={{ marginTop: 16 }}>
          <strong>Add a course</strong>
          <p className="stat-sub">Start from a template, which you should read and adjust, or write your own. Repeats every year.</p>
          <label htmlFor="tr-template">Start from</label>
          <select id="tr-template" value={fresh.template} onChange={(e) => setFresh({ ...fresh, template: e.target.value })}>
            <option value="">My own text</option>
            {(templates.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
          </select>
          {!fresh.template && (
            <>
              <label htmlFor="tr-new-title" style={{ marginTop: 8 }}>Title</label>
              <input id="tr-new-title" value={fresh.title} onChange={(e) => setFresh({ ...fresh, title: e.target.value })} />
              <label htmlFor="tr-new-body" style={{ marginTop: 8 }}>Text</label>
              <textarea id="tr-new-body" rows={8} value={fresh.body} onChange={(e) => setFresh({ ...fresh, body: e.target.value })} />
            </>
          )}
          <div style={{ marginTop: 8 }}>
            <button className="btn btn-primary"
              disabled={busy || (!fresh.template && (fresh.title.trim().length < 3 || fresh.body.trim().length < 20))}
              onClick={() => run(async () => {
                const c = await addTraining(fresh.template ? { template_id: fresh.template } : { title: fresh.title.trim(), body: fresh.body });
                setFresh({ template: "", title: "", body: "" });
                setOpen(c);
              })}>
              Add course
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
