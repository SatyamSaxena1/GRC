import { useState } from "react";
import { acceptConnectorScope, ApiError, listConnectorRuns, syncConnector, type ConnectorRun, type ConnectorStatus } from "../api/client";
import { Badge } from "./Badge";
import { localTime } from "../lib/format";

const MEANING: Record<string, string> = {
  COMPLETE: "Collected, and nothing indicated it was partial.",
  PARTIAL: "Collected, but the run looks incomplete. Its values were withheld from evaluation, not read as zero.",
  FAILED: "The collection failed. Earlier evidence is still on file but is not refreshed.",
};
const BASIS: Record<string, string> = {
  NONE: "nothing to compare it with yet",
  REPORTED: "checked against what the collector reported",
  HISTORY: "checked against the last complete run",
  "REPORTED+HISTORY": "checked against the collector's report and the last complete run",
};

/** Whether the last run of a connector could be trusted, and, on request, the last ten (ADR-030). */
export function CollectionStatus({ connector, onChanged }: { connector: ConnectorStatus; onChanged?: () => void }) {
  const last = connector.collection;
  const [runs, setRuns] = useState<ConnectorRun[] | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!last) return null;
  // Only a smaller repository scope can be accepted by a person; anything the collector itself flagged cannot.
  const scopeOnly = last.status === "PARTIAL" && last.signals.length > 0
    && last.signals.every((s) => s.startsWith("repositories in scope fell"));
  const accept = async () => {
    setBusy(true);
    setErr(null);
    try {
      await acceptConnectorScope(connector.source, reason);
      setReason("");
      await syncConnector(connector.source);
      onChanged?.();
    } catch (e) {
      setErr(e instanceof ApiError ? String(e.detail) : (e as Error).message);
    } finally { setBusy(false); }
  };
  return (
    <div style={{ marginTop: 8 }}>
      <div>
        <Badge value={last.status} /> <span className="muted" style={{ fontSize: 12 }}>last run, {BASIS[last.expectation] ?? last.expectation}</span>
      </div>
      <p className="muted" style={{ fontSize: 12, margin: "4px 0" }}>{MEANING[last.status] ?? ""}</p>
      {last.signals.length > 0 && (
        <ul style={{ margin: "4px 0 4px 18px", fontSize: 12 }}>{last.signals.map((s, i) => <li key={i}>{s}</li>)}</ul>
      )}
      {scopeOnly && (
        <div style={{ margin: "6px 0" }}>
          <label htmlFor={`scope-${connector.source}`} style={{ fontSize: 12 }}>
            If fewer repositories is right, say why (org admin). Collection runs again and the verdicts update.
          </label>
          <textarea id={`scope-${connector.source}`} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
          {err && <p className="error" style={{ fontSize: 12 }}>{err}</p>}
          <button className="btn" disabled={busy || reason.trim().split(/\s+/).length < 6} onClick={() => void accept()}>
            Accept smaller scope and collect again
          </button>
        </div>
      )}
      <details onToggle={(e) => { if ((e.target as HTMLDetailsElement).open && !runs) void listConnectorRuns(connector.source).then(setRuns); }}>
        <summary style={{ fontSize: 12 }}>Recent runs</summary>
        <ul className="timeline">
          {runs?.map((r) => (
            <li key={r.id}>
              <div className="ts">{localTime(r.at)}</div>
              <Badge value={r.status} /> <span className="muted" style={{ fontSize: 12 }}>{r.signals[0] ?? "no problems seen"}</span>
            </li>
          ))}
          {runs?.length === 0 && <li className="muted">No runs yet.</li>}
          {!runs && <li className="muted">Loading…</li>}
        </ul>
      </details>
    </div>
  );
}
