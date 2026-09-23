import { useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError, closeBreachEvent, closeRightsRequest, createBreachEvent, createRightsRequest,
  listBreachEvents, listRightsRequests, notifyAffectedBreach, notifyBoardBreach,
  type BreachEvent, type RightsRequest,
} from "../api/client";
import { Badge } from "../components/Badge";
import { useApi } from "../lib/useApi";
import { useSession } from "../lib/session";

const REQUEST_KINDS: RightsRequest["kind"][] = ["ACCESS", "CORRECTION", "ERASURE", "NOMINATION", "GRIEVANCE"];

function fmt(at: string | null) {
  return at ? new Date(at).toLocaleString() : "—";
}

function BreachSection({ canDeclare, canAct }: { canDeclare: boolean; canAct: boolean }) {
  const breaches = useApi(() => listBreachEvents(), []);
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [detectedAt, setDetectedAt] = useState("");
  const [categories, setCategories] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await createBreachEvent({
        title, description, personal_data_categories: categories,
        detected_at: new Date(detectedAt || Date.now()).toISOString(),
      });
      setOpen(false);
      setTitle(""); setDescription(""); setDetectedAt(""); setCategories("");
      breaches.reload();
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const act = async (fn: (id: string) => Promise<unknown>, id: string) => {
    await fn(id);
    breaches.reload();
  };

  return (
    <div>
      <div className="section-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>Breach log</span>
        {canDeclare && (
          <button className="btn" onClick={() => setOpen((o) => !o)}>{open ? "Cancel" : "Log breach"}</button>
        )}
      </div>
      <p className="stat-sub">
        Rule 7 requires Board notification within 72 hours (or your own stated commitment, if
        stricter) and affected-person notification without delay. Logging a breach here starts
        both clocks as real deadlines, not just a policy statement.
      </p>

      {open && (
        <div className="card" style={{ maxWidth: 460, marginBottom: 16 }}>
          {error && <div className="alert alert-error">{error}</div>}
          <div className="form-grid">
            <div>
              <label>What happened</label>
              <input type="text" placeholder="e.g. Leaked customer export" value={title} onChange={(e) => setTitle(e.target.value)} />
            </div>
            <div>
              <label>Description</label>
              <input type="text" value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>
            <div>
              <label>Personal data categories affected</label>
              <input type="text" placeholder="e.g. name, email, phone" value={categories} onChange={(e) => setCategories(e.target.value)} />
            </div>
            <div>
              <label>Detected at</label>
              <input type="datetime-local" value={detectedAt} onChange={(e) => setDetectedAt(e.target.value)} />
            </div>
            <button className="btn btn-primary" disabled={!title || busy} onClick={submit}>
              {busy ? "Logging…" : "Log breach"}
            </button>
          </div>
        </div>
      )}

      {breaches.error && <div className="alert alert-error">{breaches.error}</div>}
      <table className="data-table">
        <thead><tr><th>Breach</th><th>Board deadline</th><th>Affected-person deadline</th><th>Status</th>{canAct && <th />}</tr></thead>
        <tbody>
          {breaches.data?.map((b) => (
            <tr key={b.id}>
              <td><strong>{b.title}</strong><div className="stat-sub">detected {fmt(b.detected_at)}</div></td>
              <td>
                {fmt(b.board_notify_due_at)}
                {b.board_notified_at ? " — notified" : b.board_overdue ? <Badge value="OVERDUE" /> : null}
              </td>
              <td>
                {b.affected_notify_due_at ? fmt(b.affected_notify_due_at) : "no deadline stated"}
                {b.affected_notified_at ? " — notified" : b.affected_overdue ? <Badge value="OVERDUE" /> : null}
              </td>
              <td><Badge value={b.status} /></td>
              {canAct && (
                <td style={{ display: "flex", gap: 6 }}>
                  {!b.board_notified_at && (
                    <button className="btn" onClick={() => act((id) => notifyBoardBreach(id), b.id)}>Board notified</button>
                  )}
                  {b.affected_notify_due_at && !b.affected_notified_at && (
                    <button className="btn" onClick={() => act((id) => notifyAffectedBreach(id), b.id)}>Affected notified</button>
                  )}
                  {b.status !== "CLOSED" && (
                    <button className="btn" onClick={() => act((id) => closeBreachEvent(id), b.id)}>Close</button>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {breaches.data?.length === 0 && <p className="muted">No breaches logged.</p>}
    </div>
  );
}

function RightsRequestSection({ canLog }: { canLog: boolean }) {
  const requests = useApi(() => listRightsRequests(), []);
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<RightsRequest["kind"]>("ACCESS");
  const [name, setName] = useState("");
  const [contact, setContact] = useState("");
  const [details, setDetails] = useState("");
  const [receivedAt, setReceivedAt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await createRightsRequest({
        kind, requester_name: name, requester_contact: contact, details,
        received_at: new Date(receivedAt || Date.now()).toISOString(),
      });
      setOpen(false);
      setName(""); setContact(""); setDetails(""); setReceivedAt("");
      requests.reload();
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const close = async (id: string) => {
    await closeRightsRequest(id);
    requests.reload();
  };

  return (
    <div style={{ marginTop: 32 }}>
      <div className="section-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>Rights &amp; grievance requests</span>
        {canLog && (
          <button className="btn" onClick={() => setOpen((o) => !o)}>{open ? "Cancel" : "Log request"}</button>
        )}
      </div>
      <p className="stat-sub">
        Every access, correction, erasure, nomination or grievance request a data principal
        sends in, tracked to an SLA (your own stated commitment, or 30 days by default) — the
        operational side of the rights_request_link/grievance_process your privacy notice promises.
      </p>

      {open && (
        <div className="card" style={{ maxWidth: 460, marginBottom: 16 }}>
          {error && <div className="alert alert-error">{error}</div>}
          <div className="form-grid">
            <div>
              <label>Type</label>
              <select value={kind} onChange={(e) => setKind(e.target.value as RightsRequest["kind"])}>
                {REQUEST_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
              </select>
            </div>
            <div>
              <label>Requester name</label>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <label>Requester contact</label>
              <input type="text" value={contact} onChange={(e) => setContact(e.target.value)} />
            </div>
            <div>
              <label>Details</label>
              <input type="text" value={details} onChange={(e) => setDetails(e.target.value)} />
            </div>
            <div>
              <label>Received at</label>
              <input type="datetime-local" value={receivedAt} onChange={(e) => setReceivedAt(e.target.value)} />
            </div>
            <button className="btn btn-primary" disabled={busy} onClick={submit}>
              {busy ? "Logging…" : "Log request"}
            </button>
          </div>
        </div>
      )}

      {requests.error && <div className="alert alert-error">{requests.error}</div>}
      <table className="data-table">
        <thead><tr><th>Request</th><th>Received</th><th>Due</th><th>Status</th>{canLog && <th />}</tr></thead>
        <tbody>
          {requests.data?.map((r) => (
            <tr key={r.id}>
              <td><strong>{r.kind}</strong><div className="stat-sub">{r.requester_name || "unnamed"}</div></td>
              <td>{fmt(r.received_at)}</td>
              <td>{r.due_at ? fmt(r.due_at) : "—"}{r.overdue && <Badge value="OVERDUE" />}</td>
              <td><Badge value={r.status} /></td>
              {canLog && (
                <td>{r.status === "OPEN" && <button className="btn" onClick={() => close(r.id)}>Close</button>}</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {requests.data?.length === 0 && <p className="muted">No requests logged.</p>}
    </div>
  );
}

export function DpdpOperationsPage() {
  const { identity } = useSession();
  const isOrgAdmin = identity?.kind === "org";
  const isControlOwner = identity?.kind === "user" && identity.role === "CONTROL_OWNER";
  const canWrite = isOrgAdmin || isControlOwner;

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Breach &amp; DSR log</h2>
          <p>The operational side of DPDP Rule 7 and Rules 9 &amp; 14 — not just a document saying a process exists.</p>
        </div>
        <Link className="btn" to="/dpdp">Back to DPDP readiness</Link>
      </div>

      <BreachSection canDeclare={isOrgAdmin} canAct={canWrite} />
      <RightsRequestSection canLog={canWrite} />
    </div>
  );
}
