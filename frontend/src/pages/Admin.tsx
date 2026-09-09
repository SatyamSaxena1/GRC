import { useState } from "react";
import {
  ApiError,
  assignControl,
  closeEngagement,
  createControl,
  createUser,
} from "../api/client";
import { useSession } from "../lib/session";

function useFormAction<T>(action: () => Promise<T>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<T | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await action());
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return { run, busy, error, result };
}

export function AdminPage() {
  const { identity } = useSession();
  const orgId = identity?.kind === "org" ? identity.id : "";

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Admin</h2>
          <p>Bootstrap forms — there is no self-service signup yet, so onboarding happens here.</p>
        </div>
      </div>

      <div className="card-grid">
        <InviteUserCard orgId={orgId} />
        <RegisterControlCard orgId={orgId} />
        <AssignControlCard />
        <CloseEngagementCard />
      </div>
    </div>
  );
}

function InviteUserCard({ orgId }: { orgId: string }) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("CONTROL_OWNER");
  const { run, busy, error, result } = useFormAction(() => createUser(email, orgId, role));

  return (
    <div className="card" id="invite-user">
      <strong>Invite a team member</strong>
      <p className="stat-sub">Creates a User row scoped to the current organisation.</p>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="form-grid">
        <div>
          <label htmlFor="invite-email">Email</label>
          <input id="invite-email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="owner@example.com" />
        </div>
        <div>
          <label htmlFor="invite-role">Role</label>
          <select id="invite-role" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="CONTROL_OWNER">Control owner</option>
            <option value="ORG_ADMIN">Org admin</option>
          </select>
        </div>
        <button className="btn btn-primary" disabled={!orgId || !email || busy} onClick={run}>
          {busy ? "Creating…" : "Create user"}
        </button>
        {!orgId && <p className="muted">Sign in as an organisation to invite users.</p>}
        {result && <p className="mono">user id: {result.id}</p>}
      </div>
    </div>
  );
}

function RegisterControlCard({ orgId }: { orgId: string }) {
  const [framework, setFramework] = useState("ISO-27001");
  const [clause, setClause] = useState("A.5.15");
  const { run, busy, error, result } = useFormAction(() => createControl(orgId, framework, clause));

  return (
    <div className="card" id="register-control">
      <strong>Register a control</strong>
      <p className="stat-sub">Controls are normally created automatically on first evaluation — this is for manual setup.</p>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="form-grid">
        <div>
          <label>Framework</label>
          <input value={framework} onChange={(e) => setFramework(e.target.value)} />
        </div>
        <div>
          <label>Clause</label>
          <input value={clause} onChange={(e) => setClause(e.target.value)} />
        </div>
        <button className="btn btn-primary" disabled={!orgId || busy} onClick={run}>
          {busy ? "Creating…" : "Register control"}
        </button>
        {result && <p className="mono">control id: {result.id}</p>}
      </div>
    </div>
  );
}

function AssignControlCard() {
  const [controlId, setControlId] = useState("");
  const [userId, setUserId] = useState("");
  const { run, busy, error, result } = useFormAction(() => assignControl(controlId, userId));

  return (
    <div className="card" id="assign-control">
      <strong>Assign a control</strong>
      <p className="stat-sub">The sole access grant for a Control Owner — least privilege, enforced server-side.</p>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="form-grid">
        <div>
          <label>Control id</label>
          <input value={controlId} onChange={(e) => setControlId(e.target.value)} />
        </div>
        <div>
          <label>User id</label>
          <input value={userId} onChange={(e) => setUserId(e.target.value)} />
        </div>
        <button className="btn btn-primary" disabled={!controlId || !userId || busy} onClick={run}>
          {busy ? "Assigning…" : "Assign"}
        </button>
        {result && <p className="mono">assignment id: {result.id}</p>}
      </div>
    </div>
  );
}

function CloseEngagementCard() {
  const [engagementId, setEngagementId] = useState("");
  const { run, busy, error, result } = useFormAction(() => closeEngagement(engagementId));

  return (
    <div className="card">
      <strong>Close an engagement</strong>
      <p className="stat-sub">Revokes the auditor's access immediately; history is retained.</p>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="form-grid">
        <div>
          <label>Engagement id</label>
          <input value={engagementId} onChange={(e) => setEngagementId(e.target.value)} />
        </div>
        <button className="btn btn-danger" disabled={!engagementId || busy} onClick={run}>
          {busy ? "Closing…" : "Close engagement"}
        </button>
        {result && <p className="mono">status: {result.status}</p>}
      </div>
    </div>
  );
}
