import { useState } from "react";
import {
  ApiError, downloadAuditEvents, downloadCheckpoint, getChainStatus, verifyCheckpoint, type CheckpointVerdict,
} from "../api/client";
import { useApi } from "../lib/useApi";
import { Badge } from "./Badge";

/** Is this organisation's audit trail intact, and can an auditor take a copy to hold outside
 *  the platform? A checkpoint is a signed statement of the chain's head; uploading it later
 *  proves nothing at or before it changed (ADR-023). */
export function AuditIntegrity({ isAuditor }: { isAuditor: boolean }) {
  const status = useApi(() => getChainStatus(), []);
  const [result, setResult] = useState<CheckpointVerdict | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      status.reload();
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const verifyFile = (file: File) => run(async () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(await file.text());
    } catch {
      throw new Error("that file is not a checkpoint (it is not JSON)");
    }
    setResult(await verifyCheckpoint(parsed));
  });

  const s = status.data;
  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <div>
          <strong>Audit trail integrity</strong>{" "}
          {s && <Badge value={s.ok ? "PASS" : "FAIL"} />}
          {s && (
            <div className="muted" style={{ fontSize: 12 }}>
              {s.ok ? `${s.events} events, each hash-linked to the one before; head ${s.head_hash.slice(0, 12)}…`
                : s.problems.join("; ")}
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {isAuditor && (<>
            <button type="button" className="btn btn-sm" disabled={busy} onClick={() => run(downloadCheckpoint)}>
              Download checkpoint
            </button>
            <button type="button" className="btn btn-sm" disabled={busy} onClick={() => run(downloadAuditEvents)}>
              Export chain
            </button>
          </>)}
          <label className="btn btn-sm" style={{ cursor: "pointer" }}>
            Verify a checkpoint
            <input type="file" accept="application/json,.json" hidden
                   onChange={(e) => { const f = e.target.files?.[0]; if (f) verifyFile(f); e.target.value = ""; }} />
          </label>
        </div>
      </div>
      {error && <div className="alert alert-error" style={{ marginTop: 8 }}>{error}</div>}
      {result && (
        <div className={`alert ${result.verified ? "alert-success" : "alert-error"}`} style={{ marginTop: 8 }}>
          {result.verified
            ? `Verified: everything up to event ${result.checkpoint_seq} is unchanged; ${result.events_since} event(s) since.`
            : `Does not verify: ${result.problems.join("; ")}`}
        </div>
      )}
    </div>
  );
}
