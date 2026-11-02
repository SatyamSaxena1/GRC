import { useState } from "react";
import {
  ApiError, closeFinding, raiseFinding, reopenFinding, respondToFinding, type Finding,
} from "../api/client";
import { localTime } from "../lib/format";
import { Badge } from "./Badge";

const SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];

/** Auditor findings on one control: an auditor raises and closes them, the auditee responds. Every
 *  step is in the audit trail (ADR-032); this is only the working view. */
export function FindingsPanel({ controlId, findings, isAuditor, canRespond, onChanged }: {
  controlId: string; findings: Finding[]; isAuditor: boolean; canRespond: boolean; onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try { await fn(); onChanged(); }
    catch (err) { setError(err instanceof ApiError ? String(err.detail) : (err as Error).message); }
    finally { setBusy(false); }
  };

  return (
    <div>
      {error && <div className="alert alert-error" role="alert">{error}</div>}
      {isAuditor && <RaiseForm busy={busy} onRaise={(f) => act(() => raiseFinding(controlId, f))} />}
      {findings.length === 0 && <p className="muted">No findings on this control.</p>}
      <ul className="timeline" aria-label="Findings">
        {findings.map((f) => (
          <li key={f.id}>
            <div className="ts">{localTime(f.raised_at)}</div>
            <strong>{f.title}</strong> <Badge value={f.severity} /> <Badge value={f.status} />
            <div className="muted" style={{ fontSize: 12 }}>raised by {f.raised_by_display}</div>
            <p>{f.description}</p>
            {f.response && (
              <p><strong>Response</strong> <span className="muted">({f.responded_by_display}, {f.responded_at ? localTime(f.responded_at) : ""})</span><br />{f.response}</p>
            )}
            {f.status === "CLOSED" && (
              <p><strong>Closed</strong> <span className="muted">({f.closed_by_display}, {f.closed_at ? localTime(f.closed_at) : ""})</span><br />{f.close_note}</p>
            )}
            {canRespond && f.status !== "CLOSED" && (
              <NoteForm label={f.response ? "Update response" : "Respond"} placeholder="What was done, and where the evidence is" busy={busy}
                        onSubmit={(t) => act(() => respondToFinding(f.id, t))} />
            )}
            {isAuditor && f.status !== "CLOSED" && (
              <NoteForm label="Close finding" placeholder="Why this is resolved" busy={busy} onSubmit={(t) => act(() => closeFinding(f.id, t))} />
            )}
            {isAuditor && f.status === "CLOSED" && (
              <NoteForm label="Reopen finding" placeholder="Why it is open again" busy={busy} onSubmit={(t) => act(() => reopenFinding(f.id, t))} />
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function NoteForm({ label, placeholder, busy, onSubmit }: {
  label: string; placeholder: string; busy: boolean; onSubmit: (text: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  if (!open) return <button className="btn btn-sm" onClick={() => setOpen(true)}>{label}…</button>;
  return (
    <div className="form-row" style={{ marginTop: 6 }}>
      <input aria-label={label} placeholder={placeholder} value={text} onChange={(e) => setText(e.target.value)} style={{ minWidth: 280 }} />
      <button className="btn btn-primary" disabled={busy || text.trim().length < 15}
              onClick={() => { onSubmit(text); setText(""); setOpen(false); }}>{label}</button>
      <button className="btn" onClick={() => setOpen(false)}>Cancel</button>
    </div>
  );
}

function RaiseForm({ busy, onRaise }: { busy: boolean; onRaise: (f: { title: string; severity: string; description: string }) => void }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [severity, setSeverity] = useState("MEDIUM");
  const [description, setDescription] = useState("");
  if (!open) return <button className="btn btn-primary" style={{ marginBottom: 12 }} onClick={() => setOpen(true)}>Raise a finding…</button>;
  return (
    <fieldset className="card" style={{ marginBottom: 12 }}>
      <legend>Raise a finding</legend>
      <div className="form-row">
        <label>Title <input value={title} onChange={(e) => setTitle(e.target.value)} /></label>
        <label>Severity
          <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
            {SEVERITIES.map((s) => <option key={s}>{s}</option>)}
          </select>
        </label>
      </div>
      <label>What you found
        <textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} style={{ width: "100%" }} />
      </label>
      <div className="form-row">
        <button className="btn btn-primary" disabled={busy || title.trim().length < 3 || description.trim().length < 15}
                onClick={() => { onRaise({ title, severity, description }); setOpen(false); setTitle(""); setDescription(""); }}>Raise finding</button>
        <button className="btn" onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </fieldset>
  );
}
