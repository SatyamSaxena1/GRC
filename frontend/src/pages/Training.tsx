import { useState } from "react";
import {
  addTraining, answerTraining, ApiError, completeTraining, editTraining, getTraining, listTraining, listTrainingTemplates,
  type TrainingCourse, type TrainingMarked, type TrainingProgress,
} from "../api/client";
import { useApi } from "../lib/useApi";

const STATE_LABEL: Record<TrainingCourse["my_state"], string> = {
  NOT_DONE: "Not done yet", DONE: "Up to date", DUE_SOON: "Due soon", OVERDUE: "Overdue",
};
const STATE_BADGE: Record<TrainingCourse["my_state"], string> = {
  NOT_DONE: "badge-fail", DONE: "badge-pass", DUE_SOON: "badge-partial", OVERDUE: "badge-fail",
};
const RESULT_LABEL: Record<TrainingProgress["result"], [string, string]> = {
  NOT_STARTED: ["Not started", "badge-fail"], IN_PROGRESS: ["In progress", "badge-partial"],
  PASS: ["Pass", "badge-pass"], PARTIAL: ["Partial", "badge-partial"], FAIL: ["Fail", "badge-fail"],
};

function ResultBadge({ p }: { p: TrainingProgress }) {
  const [label, badge] = RESULT_LABEL[p.result];
  return (
    <span className={`badge ${badge}`}>
      {label}{p.score !== null ? ` ${p.score}%` : ` ${p.done} of ${p.lessons} lessons`}
    </span>
  );
}

/** One course's lessons (ADR-064): read a lesson, answer its situations, see the right answer and why. The server
 *  grades with the stored answers and keeps every try; the best try at each lesson counts. */
function Lessons({ course, onAnswered }: { course: TrainingCourse; onAnswered: (c: TrainingCourse) => void }) {
  const lessons = course.lessons ?? [];
  const [at, setAt] = useState(0);
  const [picked, setPicked] = useState<(number | undefined)[]>([]);
  const [marked, setMarked] = useState<TrainingMarked[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const lesson = lessons[at];
  const go = (i: number) => { setAt(i); setPicked([]); setMarked(null); setError(null); };
  const submit = async () => {
    setError(null);
    try {
      const r = await answerTraining(course.id, at, course.version, picked as number[]);
      setMarked(r.marked);
      onAnswered(r.course);
    } catch (err) { setError(err instanceof ApiError ? String(err.detail) : (err as Error).message); }
  };
  if (!lesson) return null;
  const ready = lesson.questions.every((_, i) => picked[i] !== undefined);
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {lessons.map((l, i) => {
          const best = course.my_progress?.by_lesson[i];
          return (
            <button key={i} className={`btn btn-sm${i === at ? " btn-primary" : ""}`} onClick={() => go(i)}>
              {i + 1}. {l.title}{best ? ` (${best[0]}/${best[1]})` : ""}
            </button>
          );
        })}
      </div>
      <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: 14, marginTop: 10 }}>{lesson.body}</pre>
      {lesson.questions.map((q, qi) => {
        const m = marked?.[qi];
        return (
          <fieldset key={`${at}-${qi}`} style={{ border: "1px solid var(--border, #ddd)", borderRadius: 6, padding: 10, marginTop: 8 }}>
            <legend style={{ fontSize: 13 }}>Situation {qi + 1}</legend>
            <p style={{ margin: "0 0 6px" }}>{q.scenario}</p>
            {q.choices.map((choice, ci) => (
              <label key={ci} style={{ display: "block", fontWeight: m && ci === m.answer ? 600 : undefined }}>
                <input type="radio" name={`q-${at}-${qi}`} disabled={!!marked} checked={picked[qi] === ci}
                  onChange={() => setPicked((p) => { const n = [...p]; n[qi] = ci; return n; })} /> {choice}
              </label>
            ))}
            {m && (
              <p className="stat-sub" style={{ marginTop: 6 }}>
                <span className={`badge ${m.right ? "badge-pass" : "badge-fail"}`}>{m.right ? "Right" : "Not quite"}</span>{" "}
                {!m.right && <>The answer is “{q.choices[m.answer]}”. </>}{m.why}
              </p>
            )}
          </fieldset>
        );
      })}
      {error && <div className="alert alert-error" style={{ marginTop: 8 }}>{error}</div>}
      <div style={{ marginTop: 8 }}>
        {marked ? (
          <>
            <strong>{marked.filter((m) => m.right).length} of {marked.length} right.</strong>{" "}
            <button className="btn btn-sm" onClick={() => go(at)}>Try again</button>{" "}
            {at + 1 < lessons.length && <button className="btn btn-sm btn-primary" onClick={() => go(at + 1)}>Next lesson</button>}
          </>
        ) : (
          <button className="btn btn-primary" disabled={!ready} onClick={() => void submit()}>
            {lesson.questions.length ? "Check my answers" : "Mark this lesson read"}
          </button>
        )}
      </div>
    </div>
  );
}

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
                {c.my_progress && <> <ResultBadge p={c.my_progress} /></>}
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
            <>
              <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: 14, maxHeight: 420, overflow: "auto" }}>{open.body}</pre>
              {(open.lessons ?? []).length > 0 && (
                <Lessons key={`${open.id}-${open.version}`} course={open}
                  onAnswered={(c) => { setOpen((cur) => (cur ? { ...cur, ...c } : cur)); state.reload(); }} />
              )}
            </>
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
          {admin && open.results && (
            <details style={{ marginTop: 10 }}>
              <summary>Everyone's results</summary>
              <p className="stat-sub">
                Best try at each lesson. 80% or more is a pass, 50% a partial. A pass shows the person picked the set
                answers, with retries allowed; it does not prove they are competent.
              </p>
              <table className="data-table static">
                <tbody>
                  {open.results.map((r) => <tr key={r.email}><td>{r.email}</td><td><ResultBadge p={r} /></td></tr>)}
                </tbody>
              </table>
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
