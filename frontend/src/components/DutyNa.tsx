import { useState } from "react";
import { ApiError, markDutyNa, reverseDutyNa } from "../api/client";

export const MIN_NA_WORDS = 6;

type NaClause = {
  clause: string; verdict: string; guidance_only?: boolean;
  na_id?: string; na_reason?: string; na_by?: string; na_at?: string;
};

/** DPDP duty-level not applicable: a written reason (six words or more), kept with who and when, reversible.
 *  Only an organisation admin sees the buttons; everyone sees the reason once a duty is marked. */
export function DutyNaControl({ framework, clause, isAdmin, onDone }: {
  framework: string; clause: NaClause; isAdmin: boolean; onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (framework !== "DPDP" || clause.guidance_only) return null;
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      setOpen(false);
      setReason("");
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : (e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const words = reason.trim().split(/\s+/).filter(Boolean).length;

  if (clause.verdict === "NOT_APPLICABLE") {
    if (!clause.na_id) return <span className="stat-sub">Marked out of scope at its evidence source.</span>;
    return (
      <div className="stat-sub">
        Not applicable. {clause.na_by} on {clause.na_at?.slice(0, 10)}: “{clause.na_reason}”{" "}
        {isAdmin && <button type="button" className="btn btn-link" disabled={busy}
          onClick={() => run(() => reverseDutyNa(clause.na_id!))}>Reverse</button>}
        {error && <div className="alert alert-error">{error}</div>}
      </div>
    );
  }
  if (!isAdmin) return null;
  if (!open) {
    return <button type="button" className="btn btn-sm" onClick={() => setOpen(true)}>Mark not applicable</button>;
  }
  return (
    <form onSubmit={(e) => { e.preventDefault(); run(() => markDutyNa({ clause: clause.clause, reason })); }}>
      <label className="stat-sub" htmlFor={`na-${clause.clause}`}>
        Why does this not apply to you? Write at least {MIN_NA_WORDS} words. It is recorded with your name and the date.
      </label>
      <textarea id={`na-${clause.clause}`} required rows={2} value={reason}
        onChange={(e) => setReason(e.target.value)} style={{ width: "100%" }} />
      <button type="submit" className="btn btn-primary" disabled={busy || words < MIN_NA_WORDS}>Mark not applicable</button>{" "}
      <button type="button" className="btn btn-link" onClick={() => setOpen(false)}>Cancel</button>
      {error && <div className="alert alert-error">{error}</div>}
    </form>
  );
}
