import { useState } from "react";
import { ApiError, getVerdictRegister, supersedeVerdict, type VerdictRegisterView } from "../api/client";
import { Badge } from "./Badge";
import { localTime } from "../lib/format";

const REASON_CODES: Record<string, string> = {
  NEW_EVIDENCE: "New evidence changes the picture",
  RULES_CHANGED: "The rules the original verdict was judged against have changed",
  ERROR_IN_ORIGINAL: "The original verdict was wrong",
  SCOPE_CHANGE: "The scope of the audit or the control changed",
  OTHER: "Another reason, stated in full below",
};
const VERDICTS = ["COMPLIANT", "PARTIALLY_COMPLIANT", "NON_COMPLIANT"];

/** Every verdict step on one control, oldest first: the original, each reopening and replacement,
 *  with who, when, why and the rules each was judged by. Loaded when opened (ADR-029). */
export function VerdictRegister({ linkId }: { linkId: string }) {
  const [view, setView] = useState<VerdictRegisterView | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      setView(await getVerdictRegister(linkId));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    }
  };

  return (
    <details style={{ marginTop: 10 }} onToggle={(e) => { if ((e.target as HTMLDetailsElement).open && !view) void load(); }}>
      <summary>Verdict history</summary>
      {error && <div className="alert alert-error">{error}</div>}
      {view && view.entries.length === 0 && <p className="muted">No verdict has been recorded on this control yet.</p>}
      {view && view.entries.length > 0 && (
        <ol className="timeline" aria-label="Verdict history, oldest first">
          {view.entries.map((r) => (
            <li key={r.id}>
              <div className="ts">{localTime(r.decided_at)}</div>
              <strong>{r.kind === "REOPENED" ? "Reopened" : "Verdict"}</strong>{" "}
              {r.verdict && <Badge value={r.verdict} />}{" "}
              <span className="muted">by {r.decided_by_display ?? r.decided_by}</span>
              {r.reasoning && <div>{r.reasoning}</div>}
              <div className="muted" style={{ fontSize: 12 }}>
                {r.reason_code !== "RECORDED" && <>reason: {REASON_CODES[r.reason_code] ?? r.reason_code} · </>}
                {r.engine_verdict && <>rules said {r.engine_verdict} · </>}
                {r.origin === "MIGRATED" && <>from before the register existed · </>}
                rule <code>{(r.rule_hash ?? "none").slice(0, 10)}</code>
              </div>
              {r.rules_changed_since_previous && (
                <div className="alert alert-warning" style={{ marginTop: 4 }}>
                  The rules changed between this step and the one before it.
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
      {view && <p className="muted" style={{ fontSize: 12 }}>{view.not_covered}</p>}
    </details>
  );
}

/** Replace a locked verdict: the original stays in the history, this adds the reopening and the
 *  new decision together, with a required reason. */
export function ReplaceVerdict({ linkId, onChanged }: { linkId: string; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [verdict, setVerdict] = useState(VERDICTS[0]);
  const [code, setCode] = useState("NEW_EVIDENCE");
  const [reasoning, setReasoning] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return <button className="btn btn-sm" style={{ marginTop: 8 }} onClick={() => setOpen(true)}>Replace verdict…</button>;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await supersedeVerdict(linkId, verdict, code, reasoning);
      setOpen(false);
      setReasoning("");
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <fieldset className="card" style={{ marginTop: 8 }}>
      <legend>Replace the locked verdict</legend>
      <p className="muted" style={{ fontSize: 12 }}>The original verdict is kept in the history. Say what changed, specifically.</p>
      <div className="form-row">
        <label>New verdict
          <select value={verdict} onChange={(e) => setVerdict(e.target.value)}>
            {VERDICTS.map((v) => <option key={v}>{v}</option>)}
          </select>
        </label>
        <label>Reason
          <select value={code} onChange={(e) => setCode(e.target.value)}>
            {Object.entries(REASON_CODES).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
        </label>
      </div>
      <label>What changed
        <textarea rows={3} value={reasoning} onChange={(e) => setReasoning(e.target.value)} style={{ width: "100%" }} />
      </label>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="form-row">
        <button className="btn btn-primary" disabled={busy || reasoning.trim().length < 15} onClick={submit}>Replace verdict</button>
        <button className="btn" disabled={busy} onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </fieldset>
  );
}
