import { useState } from "react";
import {
  ApiError,
  assignControl,
  closeEngagement,
  createControl,
  createUser,
  listControls,
  listTaskOwners,
  listTeam,
  updateTeamUser,
} from "../api/client";
import { useSession } from "../lib/session";
import { useApi } from "../lib/useApi";

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

      <TeamCard />

      <div className="card-grid">
        <InviteUserCard orgId={orgId} />
        <RegisterControlCard orgId={orgId} />
        <AssignControlCard />
        <CloseEngagementCard />
      </div>
    </div>
  );
}

const ROLE_LABEL: Record<string, string> = {
  ORG_ADMIN: "Org admin", CONTROL_OWNER: "Control owner", COMPLIANCE_VIEWER: "Compliance viewer (read-only)",
  FIRM_ADMIN: "Firm admin", AUDITOR: "Auditor",
};

/** Who has access: change a role, or switch someone off without losing what they did (ADR-036).
 *  The server enforces who may do this and keeps the last admin in place; this only shows its answer. */
function TeamCard() {
  const team = useApi(() => listTeam(), []);
  const [error, setError] = useState<string | null>(null);
  const roles = (team.data ?? []).some((u) => u.role === "FIRM_ADMIN" || u.role === "AUDITOR")
    ? ["FIRM_ADMIN", "AUDITOR"] : ["ORG_ADMIN", "CONTROL_OWNER", "COMPLIANCE_VIEWER"];

  const change = async (id: string, patch: { role?: string; active?: boolean }) => {
    setError(null);
    try {
      await updateTeamUser(id, patch);
      team.reload();
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    }
  };

  if (team.error) return null; // not an admin of an organisation or firm: nothing to manage here
  return (
    <div className="card" id="team" style={{ marginBottom: 16 }}>
      <strong>Team</strong>
      <p className="stat-sub">
        Deactivating someone ends their access at once and keeps their history. Their past actions stay
        attributed to them in the audit log.
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      <table>
        <thead><tr><th>Email</th><th>Role</th><th>Status</th><th /></tr></thead>
        <tbody>
          {(team.data ?? []).map((u) => (
            <tr key={u.id} style={u.active ? undefined : { opacity: 0.6 }}>
              <td>{u.email}</td>
              <td>
                <select aria-label={`Role for ${u.email}`} value={u.role} onChange={(e) => change(u.id, { role: e.target.value })}>
                  {roles.map((r) => <option key={r} value={r}>{ROLE_LABEL[r] ?? r}</option>)}
                </select>
              </td>
              <td>{u.active ? "Active" : "Deactivated"}</td>
              <td>
                <button className="btn btn-sm" onClick={() => change(u.id, { active: !u.active })}>
                  {u.active ? "Deactivate" : "Reactivate"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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
            <option value="COMPLIANCE_VIEWER">Compliance viewer (read-only)</option>
            <option value="ORG_ADMIN">Org admin</option>
          </select>
        </div>
        <button className="btn btn-primary" disabled={!email || busy} onClick={run}>
          {busy ? "Creating…" : "Create user"}
        </button>
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
          <input aria-label="Framework" value={framework} onChange={(e) => setFramework(e.target.value)} />
        </div>
        <div>
          <label>Clause</label>
          <input aria-label="Clause" value={clause} onChange={(e) => setClause(e.target.value)} />
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
  const controls = useApi(() => listControls(), []);
  const users = useApi(() => listTaskOwners(), []);
  const { run, busy, error, result } = useFormAction(() => assignControl(controlId, userId));

  return (
    <div className="card" id="assign-control">
      <strong>Assign a control</strong>
      <p className="stat-sub">The sole access grant for a Control Owner — least privilege, enforced server-side.</p>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="form-grid">
        <div>
          <label htmlFor="assign-control-pick">Control</label>
          <select id="assign-control-pick" value={controlId} onChange={(e) => setControlId(e.target.value)}>
            <option value="">Choose a control…</option>
            {controls.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.framework} {c.clause}{c.owner_emails.length ? ` — ${c.owner_emails.join(", ")}` : " — unassigned"}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="assign-user-pick">Owner</label>
          <select id="assign-user-pick" value={userId} onChange={(e) => setUserId(e.target.value)}>
            <option value="">Choose a person…</option>
            {users.data?.map((u) => <option key={u.id} value={u.id}>{u.email}</option>)}
          </select>
        </div>
        <button className="btn btn-primary" disabled={!controlId || !userId || busy} onClick={run}>
          {busy ? "Assigning…" : "Assign"}
        </button>
        {result && <p role="status">Assigned.</p>}
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
          <input aria-label="Engagement id" value={engagementId} onChange={(e) => setEngagementId(e.target.value)} />
        </div>
        <button className="btn btn-danger" disabled={!engagementId || busy} onClick={run}>
          {busy ? "Closing…" : "Close engagement"}
        </button>
        {result && <p className="mono">status: {result.status}</p>}
      </div>
    </div>
  );
}
