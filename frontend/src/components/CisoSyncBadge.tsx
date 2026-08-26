import type { CisoSyncStatus } from "../api/client";
import { Hint } from "./Hint";

// This app only pushes verdicts/gaps into CISO Assistant (app/ciso_sync.py) —
// it never reads risk/policy/vendor data back, so this is a status badge plus
// a link to CISO Assistant's dashboard, not a deep link to the pushed object
// (its UI route for a specific requirement-assessment isn't confirmed against
// a live instance yet; see docs/adr/010-ciso-assistant-integration.md).
const LABEL: Record<CisoSyncStatus["status"], string> = {
  OK: "Synced to CISO Assistant",
  FAILED: "CISO Assistant sync failed",
  PENDING: "Syncing to CISO Assistant…",
  SKIPPED: "CISO Assistant not configured",
};

export function CisoSyncBadge({ status }: { status?: CisoSyncStatus }) {
  if (!status) return null;
  const cisoUrl = import.meta.env.VITE_CISO_ASSISTANT_URL;

  return (
    <div className="muted" style={{ fontSize: 12, marginTop: 6, display: "flex", alignItems: "center", gap: 6 }}>
      <span className={`badge badge-${status.status.toLowerCase()}`}>{LABEL[status.status]}</span>
      {status.status === "FAILED" && <Hint>{status.error}</Hint>}
      {status.status === "OK" && cisoUrl && (
        <a href={cisoUrl} target="_blank" rel="noreferrer">open in CISO Assistant ↗</a>
      )}
    </div>
  );
}
