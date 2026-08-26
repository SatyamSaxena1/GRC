import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createAuditFirm, createEngagement, createOrganization, createUser } from "../api/client";
import { useSession } from "../lib/session";
import { Hint } from "../components/Hint";
import { oidcConfigured, startLogin } from "../lib/pkce";

const FRAMEWORKS = ["ISO-27001", "PCI-DSS"];

type Tab = "org" | "user" | "auditor" | "quickstart" | "sso";

export function LoginPage() {
  const { setIdentity } = useSession();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("quickstart");

  return (
    <div className="login-shell">
      <div className="card login-card">
        <h1>GRC Workspace</h1>
        <p className="muted">
          There is no account system yet — the backend identifies a caller by a plain
          <code> org:&lt;id&gt;</code> / <code>user:&lt;id&gt;</code> / <code>auditor:&lt;engagement_id&gt;</code>{" "}
          token. Start a demo organisation below, or sign in with an id you already have.
        </p>
        <div className="pill-select">
          <button className={tab === "quickstart" ? "active" : ""} onClick={() => setTab("quickstart")}>
            Quick start
            <Hint>Spins up a demo organisation, audit firm and engagement in one click — the fastest way to see it working.</Hint>
          </button>
          <button className={tab === "org" ? "active" : ""} onClick={() => setTab("org")}>
            Organisation
            <Hint>Sign in as the auditee — upload evidence, track gaps, and submit controls for review.</Hint>
          </button>
          <button className={tab === "user" ? "active" : ""} onClick={() => setTab("user")}>
            Control owner
            <Hint>Sign in as a team member who can see only the specific controls assigned to them, nothing else.</Hint>
          </button>
          <button className={tab === "auditor" ? "active" : ""} onClick={() => setTab("auditor")}>
            Auditor
            <Hint>Sign in as the reviewer — record verdicts, lock controls, and see only the frameworks this engagement covers.</Hint>
          </button>
          {oidcConfigured() && (
            <button className={tab === "sso" ? "active" : ""} onClick={() => setTab("sso")}>
              Single sign-on
              <Hint>Sign in via the organisation's identity provider instead of a raw id (see docs/adr/011-oidc-auth.md).</Hint>
            </button>
          )}
        </div>

        {tab === "quickstart" && <QuickStart onDone={() => navigate("/overview")} />}
        {tab === "sso" && (
          <div className="form-grid">
            <p className="muted">Redirects to the configured identity provider.</p>
            <button className="btn btn-primary" onClick={() => void startLogin()}>Continue with SSO</button>
          </div>
        )}
        {tab === "org" && (
          <IdForm
            label="Organisation id"
            placeholder="paste an organisation id"
            onSubmit={(id) => {
              setIdentity({ kind: "org", id, label: "Organisation admin" });
              navigate("/overview");
            }}
          />
        )}
        {tab === "user" && (
          <IdForm
            label="User id"
            placeholder="paste a control-owner user id"
            onSubmit={(id) => {
              setIdentity({ kind: "user", id, label: "Control owner" });
              navigate("/tasks");
            }}
          />
        )}
        {tab === "auditor" && (
          <IdForm
            label="Engagement id"
            placeholder="paste an active engagement id"
            onSubmit={(id) => {
              setIdentity({ kind: "auditor", id, label: "Auditor" });
              navigate("/controls");
            }}
          />
        )}
      </div>
    </div>
  );
}

function IdForm({ label, placeholder, onSubmit }: { label: string; placeholder: string; onSubmit: (id: string) => void }) {
  const [id, setId] = useState("");
  return (
    <form
      className="form-grid"
      onSubmit={(e) => {
        e.preventDefault();
        if (id.trim()) onSubmit(id.trim());
      }}
    >
      <div>
        <label>{label}</label>
        <input value={id} onChange={(e) => setId(e.target.value)} placeholder={placeholder} autoFocus />
      </div>
      <button className="btn btn-primary" type="submit">
        Continue
      </button>
    </form>
  );
}

function QuickStart({ onDone }: { onDone: () => void }) {
  const { setIdentity } = useSession();
  const [orgName, setOrgName] = useState("Acme Corp");
  const [firmName, setFirmName] = useState("Meridian Assurance");
  const [frameworks, setFrameworks] = useState<string[]>(FRAMEWORKS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ orgId: string; engagementId: string } | null>(null);

  const toggle = (fw: string) =>
    setFrameworks((current) => (current.includes(fw) ? current.filter((f) => f !== fw) : [...current, fw]));

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const org = await createOrganization(orgName, frameworks);
      const firm = await createAuditFirm(firmName);
      const engagement = await createEngagement(firm.id, org.id, frameworks);
      setResult({ orgId: org.id, engagementId: engagement.id });
      setIdentity({ kind: "org", id: org.id, label: `${orgName} (org admin)` });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    return (
      <div>
        <div className="alert alert-info">
          Organisation created. You are signed in as its org admin.
        </div>
        <p className="mono">org id: {result.orgId}</p>
        <p className="mono">engagement id: {result.engagementId}</p>
        <p className="muted">
          Keep the engagement id — sign in as <strong>Auditor</strong> with it later to review and lock
          controls.
        </p>
        <button className="btn btn-primary" onClick={onDone}>
          Enter workspace
        </button>
      </div>
    );
  }

  return (
    <div className="form-grid">
      {error && <div className="alert alert-error">{error}</div>}
      <div>
        <label>Organisation name</label>
        <input value={orgName} onChange={(e) => setOrgName(e.target.value)} />
      </div>
      <div>
        <label>Audit firm name</label>
        <input value={firmName} onChange={(e) => setFirmName(e.target.value)} />
      </div>
      <div>
        <label>Frameworks to subscribe</label>
        <div className="pill-select">
          {FRAMEWORKS.map((fw) => (
            <button key={fw} type="button" className={frameworks.includes(fw) ? "active" : ""} onClick={() => toggle(fw)}>
              {fw}
            </button>
          ))}
        </div>
      </div>
      <button className="btn btn-primary" disabled={busy || frameworks.length === 0} onClick={run}>
        {busy ? "Creating…" : "Create organisation & engagement"}
      </button>
    </div>
  );
}
