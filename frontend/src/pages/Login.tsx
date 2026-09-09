import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { createAuditFirm, createEngagement, createFirmUser, createOrganization, submitOnboardingRequest } from "../api/client";
import { useSession } from "../lib/session";
import { Hint } from "../components/Hint";
import { LoginTour } from "../components/LoginTour";
import { oidcConfigured, startLogin } from "../lib/pkce";

const FRAMEWORKS = ["ISO-27001", "PCI-DSS", "SOC-2", "NIST-CSF", "HIPAA", "CIS-CONTROLS", "GDPR"];

export type Tab = "org" | "user" | "auditor" | "firm" | "request" | "quickstart" | "sso";

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

        <p className="muted">
          New here? <Link to="/pitch">See what this is, with a live demo</Link>.
        </p>

        <LoginTour onSelectTab={setTab} />

        <div className="pill-select" data-tour="login-tabs">
          <button data-tour="tab-quickstart" className={tab === "quickstart" ? "active" : ""} onClick={() => setTab("quickstart")}>
            Quick start
            <Hint>Spins up a demo organisation, audit firm and engagement in one click — the fastest way to see it working.</Hint>
          </button>
          <button data-tour="tab-org" className={tab === "org" ? "active" : ""} onClick={() => setTab("org")}>
            Organisation
            <Hint>Sign in as the auditee — upload evidence, track gaps, and submit controls for review.</Hint>
          </button>
          <button data-tour="tab-user" className={tab === "user" ? "active" : ""} onClick={() => setTab("user")}>
            Control owner
            <Hint>Sign in as a team member who can see only the specific controls assigned to them, nothing else.</Hint>
          </button>
          <button data-tour="tab-auditor" className={tab === "auditor" ? "active" : ""} onClick={() => setTab("auditor")}>
            Auditor
            <Hint>Sign in as the reviewer — record verdicts, lock controls, and see only the frameworks this engagement covers.</Hint>
          </button>
          <button data-tour="tab-firm" className={tab === "firm" ? "active" : ""} onClick={() => setTab("firm")}>
            Audit firm
            <Hint>Sign in on the firm's side of the table — approve who gets onboarded, and staff your auditors onto the clients they are allowed to work.</Hint>
          </button>
          <button data-tour="tab-request" className={tab === "request" ? "active" : ""} onClick={() => setTab("request")}>
            Request an audit
            <Hint>The prospect's entry point: ask a firm to audit you. It creates no account — approval by the firm is what does that.</Hint>
          </button>
          {oidcConfigured() && (
            <button className={tab === "sso" ? "active" : ""} onClick={() => setTab("sso")}>
              Single sign-on
              <Hint>Sign in via the organisation's identity provider instead of a raw id (see docs/adr/011-oidc-auth.md).</Hint>
            </button>
          )}
        </div>

        {tab === "quickstart" && <QuickStart onDone={() => navigate("/overview")} />}
        {tab === "firm" && <FirmStart onDone={() => navigate("/firm")} />}
        {tab === "request" && <RequestAudit />}
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
      <button data-tour="quickstart-submit" className="btn btn-primary" disabled={busy || frameworks.length === 0} onClick={run}>
        {busy ? "Creating…" : "Create organisation & engagement"}
      </button>
    </div>
  );
}


/**
 * The firm's way in. Creating a firm here also creates its first FIRM_ADMIN and
 * signs in as that user rather than as the bare `firm:<id>` stub, so staffing
 * and onboarding decisions are attributable to a person in the audit trail.
 */
function FirmStart({ onDone }: { onDone: () => void }) {
  const { setIdentity } = useSession();
  const [firmName, setFirmName] = useState("Gemba Assurance");
  const [email, setEmail] = useState("admin@gemba.test");
  const [existingId, setExistingId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ firmId: string; adminId: string } | null>(null);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const firm = await createAuditFirm(firmName);
      const admin = await createFirmUser(email, firm.id, "FIRM_ADMIN");
      setResult({ firmId: firm.id, adminId: admin.id });
      setIdentity({ kind: "user", id: admin.id, label: `${firmName} (firm admin)` });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    return (
      <div>
        <div className="alert alert-info">Audit firm created. You are signed in as its firm admin.</div>
        <p className="mono">audit firm id: {result.firmId}</p>
        <p className="mono">firm admin user id: {result.adminId}</p>
        <p className="muted">
          Keep the audit firm id — a prospect needs it on the <strong>Request an audit</strong> tab to
          reach your onboarding queue.
        </p>
        <button className="btn btn-primary" onClick={onDone}>Open firm console</button>
      </div>
    );
  }

  return (
    <div className="form-grid">
      {error && <div className="alert alert-error">{error}</div>}
      <div>
        <label>Audit firm name</label>
        <input value={firmName} onChange={(e) => setFirmName(e.target.value)} />
      </div>
      <div>
        <label>Firm admin email</label>
        <input value={email} onChange={(e) => setEmail(e.target.value)} />
      </div>
      <button data-tour="firm-submit" className="btn btn-primary" disabled={busy || !firmName || !email} onClick={create}>
        {busy ? "Creating…" : "Create firm & sign in as its admin"}
      </button>

      <hr />
      <div>
        <label>…or sign in as an existing firm user</label>
        <input
          value={existingId}
          onChange={(e) => setExistingId(e.target.value)}
          placeholder="paste a firm admin or auditor user id"
        />
      </div>
      <button
        className="btn"
        disabled={!existingId.trim()}
        onClick={() => {
          setIdentity({ kind: "user", id: existingId.trim(), label: "Firm user" });
          onDone();
        }}
      >
        Continue
      </button>
    </div>
  );
}

/** A prospect asking to be audited. Deliberately creates no identity: the firm
 *  approving the request is what brings the organisation into existence. */
function RequestAudit() {
  const [firmId, setFirmId] = useState("");
  const [orgName, setOrgName] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [detail, setDetail] = useState("");
  const [frameworks, setFrameworks] = useState<string[]>(["ISO-27001"]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  const toggle = (fw: string) =>
    setFrameworks((current) => (current.includes(fw) ? current.filter((f) => f !== fw) : [...current, fw]));

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await submitOnboardingRequest({
        audit_firm_id: firmId.trim(),
        org_name: orgName,
        contact_email: contactEmail,
        registration_detail: detail,
        frameworks,
      });
      setSent(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (sent) {
    return (
      <div className="alert alert-info">
        Request sent. Nothing exists for you yet — when the firm approves it, your organisation and
        its engagement are created, and you will be given the id to sign in with.
      </div>
    );
  }

  return (
    <div className="form-grid">
      {error && <div className="alert alert-error">{error}</div>}
      <div>
        <label>Audit firm id</label>
        <input value={firmId} onChange={(e) => setFirmId(e.target.value)} placeholder="the firm you want to audit you" />
      </div>
      <div>
        <label>Organisation name</label>
        <input value={orgName} onChange={(e) => setOrgName(e.target.value)} placeholder="Acme Corp" />
      </div>
      <div>
        <label>Contact email</label>
        <input value={contactEmail} onChange={(e) => setContactEmail(e.target.value)} placeholder="ciso@acme.test" />
      </div>
      <div>
        <label>Registration details</label>
        <input value={detail} onChange={(e) => setDetail(e.target.value)} placeholder="registered entity, scope, sites" />
      </div>
      <div>
        <label>Frameworks you need audited</label>
        <div className="pill-select">
          {FRAMEWORKS.map((fw) => (
            <button key={fw} type="button" className={frameworks.includes(fw) ? "active" : ""} onClick={() => toggle(fw)}>
              {fw}
            </button>
          ))}
        </div>
      </div>
      <button className="btn btn-primary" disabled={busy || !firmId.trim() || !orgName || frameworks.length === 0} onClick={send}>
        {busy ? "Sending…" : "Send onboarding request"}
      </button>
    </div>
  );
}
