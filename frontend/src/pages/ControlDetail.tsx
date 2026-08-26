import { useState } from "react";
import { useParams } from "react-router-dom";
import {
  ApiError,
  getCisoSyncStatus,
  getControl,
  getControlEvidence,
  getControlHistory,
  lockLink,
  recordVerdict,
  submitControl,
  unlockLink,
  type CisoSyncStatus,
} from "../api/client";
import { useApi } from "../lib/useApi";
import { useSession } from "../lib/session";
import { Badge } from "../components/Badge";
import { CisoSyncBadge } from "../components/CisoSyncBadge";

const AUDITOR_VERDICTS = ["COMPLIANT", "PARTIALLY_COMPLIANT", "NON_COMPLIANT"];

export function ControlDetailPage() {
  const { id = "" } = useParams();
  const { identity } = useSession();
  const control = useApi(() => getControl(id), [id]);
  const evidenceRows = useApi(() => getControlEvidence(id), [id]);
  const history = useApi(() => getControlHistory(id), [id]);
  const cisoSync = useApi(() => getCisoSyncStatus(), []);
  const [error, setError] = useState<string | null>(null);

  const isAuditor = identity?.kind === "auditor";

  const submit = async () => {
    setError(null);
    try {
      await submitControl(id);
      control.reload();
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    }
  };

  if (control.loading && !control.data) return <p className="muted">Loading…</p>;
  if (control.error) return <div className="alert alert-error">{control.error}</div>;
  if (!control.data) return null;

  const data = control.data;

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>{data.framework} {data.clause}</h2>
        </div>
        {data.locked && <span className="badge badge-locked">locked</span>}
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {!isAuditor && !data.locked && (
        <button className="btn btn-primary" onClick={submit} style={{ marginBottom: 20 }}>
          Submit for auditor review
        </button>
      )}
      {!isAuditor && data.locked && (
        <div className="alert alert-info">This control has been closed by the auditor. Contents are read-only.</div>
      )}

      <div className="section-title">Linked evidence</div>
      {evidenceRows.data && evidenceRows.data.length === 0 && (
        <div className="card empty-state">No evidence linked to this control yet.</div>
      )}
      <div className="card-grid">
        {evidenceRows.data?.map((row) => (
          <a key={row.evidence_id} href={`/evidence/${row.evidence_id}`} className="card">
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <strong>{row.original_filename || "evidence"}</strong>
              <Badge value={row.verdict} />
            </div>
            <div className="stat-sub">
              v{row.version} · {row.lifecycle_status}
              {row.locked && " · locked"}
            </div>
          </a>
        ))}
      </div>

      {isAuditor && (
        <>
          <div className="section-title">Auditor review</div>
          {data.links.map((link) => (
            <AuditorLinkPanel
              key={link.id} linkId={link.id} verdict={link.verdict}
              auditorVerdict={link.auditor_verdict} locked={link.locked}
              onChanged={() => { control.reload(); cisoSync.reload(); }}
              syncStatus={cisoSync.data?.find((s) => s.entity_type === "evidence_control_link" && s.entity_id === link.id)}
            />
          ))}
        </>
      )}

      <div className="section-title">History</div>
      <ul className="timeline">
        {history.data?.map((e, i) => (
          <li key={i}>
            <div className="ts">{new Date(e.at).toLocaleString()}</div>
            <strong>{e.action}</strong> by {e.actor}
            {e.reason && <span className="muted"> — {e.reason}</span>}
          </li>
        ))}
        {history.data?.length === 0 && <li className="muted">No events yet.</li>}
      </ul>
    </div>
  );
}

function AuditorLinkPanel({
  linkId,
  verdict,
  auditorVerdict,
  locked,
  onChanged,
  syncStatus,
}: {
  linkId: string;
  verdict: string;
  auditorVerdict: string | null;
  locked: boolean;
  onChanged: () => void;
  syncStatus?: CisoSyncStatus;
}) {
  const [choice, setChoice] = useState(auditorVerdict ?? AUDITOR_VERDICTS[0]);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card" style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <span className="muted">Deterministic verdict:</span>
        <Badge value={verdict} />
      </div>
      {locked && <CisoSyncBadge status={syncStatus} />}
      {error && <div className="alert alert-error">{error}</div>}
      {locked ? (
        <div style={{ marginTop: 10 }}>
          <div className="badge badge-locked">locked — {auditorVerdict}</div>
          <div className="form-row" style={{ marginTop: 10 }}>
            <input placeholder="reason for unlocking (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
            <button className="btn btn-danger" disabled={busy || reason.trim().length < 3} onClick={() => act(() => unlockLink(linkId, reason))}>
              Unlock
            </button>
          </div>
        </div>
      ) : (
        <div className="form-row" style={{ marginTop: 10 }}>
          <select value={choice} onChange={(e) => setChoice(e.target.value)}>
            {AUDITOR_VERDICTS.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
          <input placeholder="remarks (optional)" value={reason} onChange={(e) => setReason(e.target.value)} />
          <button className="btn btn-primary" disabled={busy} onClick={() => act(() => recordVerdict(linkId, choice, reason))}>
            Record verdict
          </button>
          <button className="btn" disabled={busy} onClick={() => act(() => lockLink(linkId, choice))}>
            Lock
          </button>
        </div>
      )}
      <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
        Recording COMPLIANT locks the control in the same step. The uploader of this evidence cannot
        be the one recording its verdict — the backend rejects that as a segregation-of-duties
        violation.
      </p>
    </div>
  );
}
