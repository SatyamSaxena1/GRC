import { useState } from "react";
import { listConnectorRuns, type ConnectorRun, type ConnectorStatus } from "../api/client";
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
export function CollectionStatus({ connector }: { connector: ConnectorStatus }) {
  const last = connector.collection;
  const [runs, setRuns] = useState<ConnectorRun[] | null>(null);
  if (!last) return null;
  return (
    <div style={{ marginTop: 8 }}>
      <div>
        <Badge value={last.status} /> <span className="muted" style={{ fontSize: 12 }}>last run, {BASIS[last.expectation] ?? last.expectation}</span>
      </div>
      <p className="muted" style={{ fontSize: 12, margin: "4px 0" }}>{MEANING[last.status] ?? ""}</p>
      {last.signals.length > 0 && (
        <ul style={{ margin: "4px 0 4px 18px", fontSize: 12 }}>{last.signals.map((s, i) => <li key={i}>{s}</li>)}</ul>
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
