import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ApiError,
  approveOnboarding,
  listFirmAuditors,
  listFirmEngagements,
  listOnboardingRequests,
  rejectOnboarding,
  staffAuditor,
  unstaffAuditor,
  type FirmEngagement,
  type OnboardingRequestRow,
} from "../api/client";
import { useApi } from "../lib/useApi";
import { useSession } from "../lib/session";
import { Badge } from "../components/Badge";
import { Hint } from "../components/Hint";

const message = (err: unknown) =>
  err instanceof ApiError ? String(err.detail) : (err as Error).message;

/**
 * The firm's side of the table. A FIRM_ADMIN sees the whole book of clients and
 * decides who gets onboarded and who works on what; an AUDITOR sees only the
 * clients it has been staffed on. Both restrictions are server-side — this page
 * renders what came back, it does not decide what may be seen.
 */
export function FirmPage() {
  const { identity } = useSession();
  const isFirmAdmin = identity?.kind === "firm" || identity?.label.includes("firm admin");
  const engagements = useApi(() => listFirmEngagements(), []);
  const requests = useApi(() => listOnboardingRequests(), []);

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Firm console</h2>
          <p>
            Your clients, who is staffed on them, and who is waiting to be onboarded.
            Approving a request is what creates that client's workspace.
          </p>
        </div>
      </div>

      <OnboardingQueue state={requests} onDecided={() => { requests.reload(); engagements.reload(); }} />

      <h3 style={{ marginTop: 28 }}>
        Clients
        <Hint>
          One row per engagement. An auditor only ever sees the clients staffed to them — this list
          is filtered by the backend, not by this page.
        </Hint>
      </h3>
      {engagements.loading && <p className="muted">Loading clients…</p>}
      {engagements.error && <div className="alert alert-error">{engagements.error}</div>}
      {engagements.data?.engagements.length === 0 && (
        <div className="card">
          <p className="muted" style={{ margin: 0 }}>
            No clients yet. {isFirmAdmin
              ? "Approve an onboarding request above to create one."
              : "You have not been staffed on any engagement yet — ask your firm admin."}
          </p>
        </div>
      )}
      <div className="card-grid" data-tour="firm-clients">
        {engagements.data?.engagements.map((engagement) => (
          <ClientCard
            key={engagement.id}
            engagement={engagement}
            canStaff={Boolean(isFirmAdmin)}
            onChanged={() => engagements.reload()}
          />
        ))}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ onboarding

function OnboardingQueue({
  state,
  onDecided,
}: {
  state: ReturnType<typeof useApi<{ requests: OnboardingRequestRow[] }>>;
  onDecided: () => void;
}) {
  const pending = state.data?.requests.filter((r) => r.status === "PENDING") ?? [];
  const decided = state.data?.requests.filter((r) => r.status !== "PENDING") ?? [];

  return (
    <section data-tour="firm-onboarding">
      <h3>
        Onboarding requests
        <Hint>
          A prospect asks to be audited before any account for them exists. Nothing tenant-owned is
          created until you approve — a rejected request leaves no half-built organisation behind.
        </Hint>
      </h3>
      {state.error && <div className="alert alert-error">{state.error}</div>}
      {!state.loading && pending.length === 0 && (
        <p className="muted">No requests waiting on a decision.</p>
      )}
      <div className="card-grid">
        {pending.map((request) => (
          <RequestCard key={request.id} request={request} onDecided={onDecided} />
        ))}
      </div>
      {decided.length > 0 && (
        <details style={{ marginTop: 12 }}>
          <summary className="muted">{decided.length} already decided</summary>
          <ul className="muted" style={{ marginTop: 8 }}>
            {decided.map((r) => (
              <li key={r.id}>
                {r.org_name} — <Badge value={r.status} />{" "}
                {r.decision_note && <em>“{r.decision_note}”</em>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function RequestCard({ request, onDecided }: { request: OnboardingRequestRow; onDecided: () => void }) {
  // Pre-ticked with what the client asked for; the firm can narrow it here,
  // which is the whole point of approval being a decision rather than a rubber stamp.
  const [frameworks, setFrameworks] = useState<string[]>(request.frameworks);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = (fw: string) =>
    setFrameworks((current) =>
      current.includes(fw) ? current.filter((f) => f !== fw) : [...current, fw],
    );

  const decide = async (action: "approve" | "reject") => {
    if (action === "reject" && !note.trim()) {
      setError("A rejection needs a reason — the prospect is entitled to one.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (action === "approve") await approveOnboarding(request.id, frameworks, note);
      else await rejectOnboarding(request.id, note);
      onDecided();
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <strong>{request.org_name}</strong>
      <p className="stat-sub">{request.contact_email || "no contact given"}</p>
      {request.registration_detail && <p className="muted">{request.registration_detail}</p>}
      {error && <div className="alert alert-error">{error}</div>}

      <div className="form-grid">
        <div>
          <label>Frameworks to allocate</label>
          <div className="pill-select">
            {request.frameworks.map((fw) => (
              <button
                key={fw}
                type="button"
                className={frameworks.includes(fw) ? "active" : ""}
                onClick={() => toggle(fw)}
              >
                {fw}
              </button>
            ))}
          </div>
          <p className="muted" style={{ marginTop: 4 }}>
            Requested: {request.frameworks.join(", ") || "none"}
          </p>
        </div>
        <div>
          <label htmlFor={`note-${request.id}`}>Decision note</label>
          <input
            id={`note-${request.id}`}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="contract reference, or why not"
          />
        </div>
        <div className="form-row">
          <button
            className="btn btn-primary"
            disabled={busy || frameworks.length === 0}
            onClick={() => decide("approve")}
          >
            {busy ? "Working…" : "Approve & create workspace"}
          </button>
          <button className="btn btn-danger" disabled={busy} onClick={() => decide("reject")}>
            Reject
          </button>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ clients

function ClientCard({
  engagement,
  canStaff,
  onChanged,
}: {
  engagement: FirmEngagement;
  canStaff: boolean;
  onChanged: () => void;
}) {
  const { identity, setIdentity } = useSession();
  const navigate = useNavigate();
  const { progress } = engagement;

  // Working a client means carrying its engagement id on every request; the
  // ordinary auditee-shaped screens then scope themselves to it server-side.
  const openClient = () => {
    if (!identity || identity.kind === "oidc") return;
    setIdentity({ ...identity, engagementId: engagement.id, label: `${engagement.org_name} (auditor)` });
    navigate("/controls");
  };

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <strong>{engagement.org_name}</strong>
        <Badge value={engagement.status} />
      </div>
      <p className="stat-sub">{engagement.frameworks.join(", ") || "no frameworks allocated"}</p>

      <div className="meta-strip">
        <div className="meta-item">
          <span className="meta-label">Controls</span>
          <span className="meta-value">{progress.controls}</span>
        </div>
        <div className="meta-item">
          <span className="meta-label">Evaluated</span>
          <span className="meta-value">{progress.evaluated}</span>
        </div>
        <div className="meta-item">
          <span className="meta-label">Locked</span>
          <span className="meta-value">{progress.locked}</span>
        </div>
        <div className="meta-item">
          <span className="meta-label">Open gaps</span>
          <span className="meta-value">{progress.open_gaps}</span>
        </div>
      </div>

      <Staffing engagement={engagement} canStaff={canStaff} onChanged={onChanged} />

      <button
        className="btn btn-primary"
        disabled={engagement.status !== "ACTIVE"}
        onClick={openClient}
      >
        Open this client
      </button>
    </div>
  );
}

function Staffing({
  engagement,
  canStaff,
  onChanged,
}: {
  engagement: FirmEngagement;
  canStaff: boolean;
  onChanged: () => void;
}) {
  const roster = useApi(() => (canStaff ? listFirmAuditors() : Promise.resolve({ auditors: [] })), [canStaff]);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const staffed = new Set(engagement.auditors.map((a) => a.user_id));
  const assignable = (roster.data?.auditors ?? []).filter((a) => !staffed.has(a.id));

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setSelected("");
      onChanged();
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <label>Staffed auditors</label>
      {error && <div className="alert alert-error">{error}</div>}
      {engagement.auditors.length === 0 && <p className="muted">Nobody assigned yet.</p>}
      <ul style={{ listStyle: "none", padding: 0, margin: "4px 0 10px" }}>
        {engagement.auditors.map((auditor) => (
          <li key={auditor.user_id}
              style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "3px 0" }}>
            <span>
              {auditor.email} <span className="muted">{auditor.role}</span>
            </span>
            {canStaff && (
              <button
                className="btn"
                disabled={busy}
                onClick={() => run(() => unstaffAuditor(engagement.id, auditor.user_id))}
                aria-label={`Remove ${auditor.email} from ${engagement.org_name}`}
              >
                Remove
              </button>
            )}
          </li>
        ))}
      </ul>

      {canStaff && (
        <div className="form-row">
          <select value={selected} onChange={(e) => setSelected(e.target.value)}>
            <option value="">Add an auditor…</option>
            {assignable.map((auditor) => (
              <option key={auditor.id} value={auditor.id}>
                {auditor.email} ({auditor.role})
              </option>
            ))}
          </select>
          <button
            className="btn"
            disabled={!selected || busy}
            onClick={() => run(() => staffAuditor(engagement.id, selected))}
          >
            Assign
          </button>
        </div>
      )}
    </div>
  );
}
