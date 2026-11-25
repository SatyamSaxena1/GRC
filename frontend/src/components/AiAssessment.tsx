import { useState } from "react";
import { ApiError, confirmAssessment, runAssessment, type Assessment } from "../api/client";

const OUTCOMES = ["MET", "PARTIAL", "NOT_MET"];

/** One AI assessment (ADR-069): the proposal, each point's verbatim quote and page, and who confirmed it.
 *  The model proposes; only an organisation admin confirms. Never shown as passed by the rules. */
export function AssessmentCard({ a, isAdmin, onDone }: { a: Assessment; isAdmin: boolean; onDone: () => void }) {
  const [outcome, setOutcome] = useState(a.outcome === "NEEDS_REVIEW" ? "" : a.outcome);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await confirmAssessment(a.id, { outcome: outcome || undefined, note });
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : (e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="stat-sub">
      <strong>AI-assessed: {a.outcome.replace("_", " ")}</strong> by {a.model || "the model"} ({a.prompt_version}), read {a.created_at.slice(0, 10)}.
      {a.reason && <> {a.reason}.</>}
      <ul>
        {a.points.map((p) => (
          <li key={p.point}>
            <span className="mono">{p.point}</span>: {p.result}{p.reason ? `, ${p.reason}` : ""}
            {p.quote && <> — “{p.quote}”{p.page ? ` (page ${p.page})` : ""}</>}
          </li>
        ))}
      </ul>
      {a.confirmed_at ? (
        <div>Confirmed {a.confirmed_outcome?.replace("_", " ")} by {a.confirmed_by_display ?? a.confirmed_by} on {a.confirmed_at.slice(0, 10)}
          {a.confirm_note ? `: “${a.confirm_note}”` : ""}</div>
      ) : isAdmin ? (
        <div>
          <label>Your judgement{" "}
            <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
              <option value="">Choose…</option>
              {OUTCOMES.map((o) => <option key={o} value={o}>{o.replace("_", " ")}</option>)}
            </select>
          </label>{" "}
          <input aria-label="Note" placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />{" "}
          <button type="button" className="btn btn-sm btn-primary" disabled={busy || !outcome} onClick={confirm}>
            {outcome && outcome === a.outcome ? "Confirm" : "Confirm / override"}
          </button>
        </div>
      ) : (
        <div>Awaiting confirmation by an organisation admin.</div>
      )}
      {error && <div className="alert alert-error">{error}</div>}
    </div>
  );
}

/** For a clause the pack marks assessable: run the assessor, and show the assessment that counts. */
export function AssessCell({ framework, clause, current, canWrite, isAdmin, subscribed, onDone }: {
  framework: string; clause: string; current: Assessment | undefined; canWrite: boolean; isAdmin: boolean;
  subscribed: boolean; onDone: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      await runAssessment({ framework, clause });
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : (e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      {current && <AssessmentCard a={current} isAdmin={isAdmin} onDone={onDone} />}
      {!current && <span className="stat-sub">No fixed rule: the model can propose, a person confirms. </span>}
      {canWrite && subscribed && (
        <button type="button" className="btn btn-sm" disabled={busy} onClick={run}>
          {busy ? "Reading…" : current ? "Run again" : "Assess with AI"}
        </button>
      )}
      {error && <div className="alert alert-error">{error}</div>}
    </div>
  );
}

/** Role flags the pages share, from the session identity (same rule as CodeReview.tsx). */
export function roleFlags(identity: { kind?: string; role?: string | null; engagementId?: string | null } | null | undefined) {
  const scoped = !!identity?.engagementId;
  const isAdmin = identity?.kind === "org" || ((identity?.kind === "user" || identity?.kind === "oidc")
    && (identity.role ?? "ORG_ADMIN") === "ORG_ADMIN" && !scoped);
  const canWrite = identity?.kind !== "auditor" && !scoped && identity?.role !== "COMPLIANCE_VIEWER";
  return { isAdmin, canWrite };
}
