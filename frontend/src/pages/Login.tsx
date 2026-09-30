import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { createAuditFirm, createEngagement, createFirmUser, createOrganization, submitOnboardingRequest } from "../api/client";
import { useSession } from "../lib/session";
import { Hint } from "../components/Hint";
import { LoginTour } from "../components/LoginTour";
import { oidcConfigured, startLogin } from "../lib/pkce";
import { ROLES, type DemoWorld, type RoleDef } from "../lib/roles";
import { ensureWorld } from "../lib/demoWorld";
import { FEATURES, reachOf } from "../lib/nav";

// three.js is only needed for the map, so it arrives in its own chunk.
const FeatureConstellation = lazy(() => import("../components/FeatureConstellation"));
const RoleSurface = lazy(() => import("../components/RoleSurface"));

const FRAMEWORKS = ["ISO-27001", "PCI-DSS", "SOC-2", "NIST-CSF", "HIPAA", "CIS-CONTROLS", "GDPR"];

export type Tab = "org" | "user" | "viewer" | "auditor" | "firm" | "request" | "quickstart" | "sso";

export function LoginPage() {
  // With an identity provider configured this is a real deployment: SSO and
  // Request an audit only, exactly as before. Without one it is a demo, and
  // the front door is the role deck.
  return oidcConfigured() ? <ClassicLogin /> : <DemoGate />;
}

// Ids never reach the map — it only needs the shape of each role's identity to
// work out which menu that role gets.
const SHAPE: DemoWorld = {
  orgId: "-", firmId: "-", engagementId: "-", ownerId: "-", viewerId: "-", firmAdminId: "-",
  orgName: "Acme Corp", firmName: "Meridian Assurance",
};

function DemoGate() {
  const { setIdentity } = useSession();
  const navigate = useNavigate();
  const [active, setActive] = useState<RoleDef>(ROLES[0]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [manual, setManual] = useState(false);

  const reach = useMemo(
    () => Object.fromEntries(ROLES.map((r) => [r.id, reachOf(r.identity(SHAPE))])),
    [],
  );
  const labelOf = (to: string) => FEATURES.find((f) => f.to === to)?.label ?? to;

  const enter = async (role: RoleDef, to = role.home) => {
    if (busy) return;
    setActive(role);
    setError(null);
    try {
      const world = await ensureWorld(setBusy);
      setIdentity(role.identity(world));
      navigate(to);
    } catch (err) {
      setError(`Could not reach the backend: ${(err as Error).message}`);
    } finally {
      setBusy(null);
    }
  };

  // 1–5 signs straight in as that role, the same keys the in-app switcher uses.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (manual || e.metaKey || e.ctrlKey || e.altKey) return;
      if ((e.target as HTMLElement).closest("input, textarea, select")) return;
      const role = ROLES.find((r) => r.key === e.key);
      if (role) void enter(role);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const lit = reach[active.id];

  return (
    <div className="gate" style={{ "--role": active.color, "--role-dark": active.dark } as React.CSSProperties}>
      <Suspense fallback={null}>
        <RoleSurface color={active.color} />
      </Suspense>
      <header className="gate-bar">
        <strong>GRC Workspace</strong>
        <span className="gate-bar__demo">DEMO</span>
        <span className="gate-bar__what">
          Acme Corp is being audited by Meridian Assurance. Pick whose eyes to look through — one click, no password.
        </span>
        <Link to="/pitch">What is this?</Link>
        <button type="button" className="gate-link" onClick={() => setManual((m) => !m)}>
          {manual ? "Back to roles" : "Sign in by id / request an audit"}
        </button>
      </header>

      {manual ? (
        <div className="gate-manual"><ClassicLogin embedded /></div>
      ) : (
        <div className="gate-grid">
          <section className="role-deck" aria-label="Choose a role">
            {ROLES.map((role) => (
              <button
                key={role.id}
                type="button"
                className={`role-card${role.id === active.id ? " is-active" : ""}`}
                style={{ "--c": role.color, "--cd": role.dark } as React.CSSProperties}
                onMouseEnter={() => setActive(role)}
                onFocus={() => setActive(role)}
                onClick={() => void enter(role)}
                disabled={Boolean(busy)}
              >
                <span className="role-card__swatch">
                  <kbd>{role.key}</kbd>
                  <small>{role.swatch}</small>
                </span>
                <span className="role-card__body">
                  <span className="role-card__top">
                    <strong>{role.name}</strong>
                    <em>{role.side}</em>
                  </span>
                  <span className="role-card__who">{role.who}</span>
                  <span className="role-card__does">
                    {role.does.map((d) => <span key={d}>{d}</span>)}
                  </span>
                  <span className="role-card__foot">
                    Lands on {labelOf(role.home)} · {reach[role.id].size} of {FEATURES.length} screens
                  </span>
                </span>
                <span className="role-card__go" aria-hidden>→</span>
              </button>
            ))}
            <p className="role-deck__status" role="status">
              {error ? <span className="gate-error">{error}</span>
                : busy ?? "First click seeds the demo tenant; switching after that is instant."}
            </p>
          </section>

          <section className="gate-map">
            <div className="gate-map__caption">
              <span className="gate-map__dot" />
              <strong>{active.name}</strong> can open <strong>{lit.size}</strong> of {FEATURES.length} screens.
              <span className="muted"> Click a lit one to go straight there. Drag to turn.</span>
            </div>
            <Suspense fallback={<div className="constellation constellation--loading">Loading map…</div>}>
              <FeatureConstellation
                features={FEATURES}
                reachable={lit}
                color={active.color}
                onPick={(to) => void enter(active, to)}
              />
            </Suspense>
            <ul className="gate-map__list">
              {FEATURES.map((f) => (
                <li key={f.to} className={lit.has(f.to) ? "is-on" : ""}>
                  {lit.has(f.to)
                    ? <button type="button" onClick={() => void enter(active, f.to)}>{f.label}</button>
                    : <span>{f.label}</span>}
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </div>
  );
}

function ClassicLogin({ embedded = false }: { embedded?: boolean }) {
  const { setIdentity } = useSession();
  const navigate = useNavigate();
  // Whenever an identity provider is configured — every real deployment,
  // self-hosted or SaaS — the raw org:<id>/user:<id> stub tabs and the
  // /admin-calling demo flows (Quick start, Audit firm "create new") have
  // nothing to do: the backend rejects stub tokens once AUTH_STUB_ENABLED=false
  // (app/auth.py), and /admin/organizations|audit-firms now needs an operator
  // key the browser never has (app/routers/admin.py). A self-hosted org that
  // hasn't set up an IdP still gets the full stub UI below, unchanged — useful
  // for something that never leaves their own network. Real onboarding, once
  // OIDC is on, is Sign in (already-provisioned) or Request an audit
  // (self-service — see RequestAudit and firm.py::approve_onboarding_request).
  const production = oidcConfigured();
  const [tab, setTab] = useState<Tab>(production ? "sso" : "quickstart");

  const card = (
      <div className="card login-card">
        <h1>GRC Workspace</h1>
        {production ? (
          <p className="muted">Sign in with your organisation's identity provider, or ask an audit firm to onboard you.</p>
        ) : (
          <>
            <p className="muted">
              There is no account system yet — the backend identifies a caller by a plain
              <code> org:&lt;id&gt;</code> / <code>user:&lt;id&gt;</code> / <code>auditor:&lt;engagement_id&gt;</code>{" "}
              token. Start a demo organisation below, or sign in with an id you already have.
            </p>
            <p className="muted">
              New here? <Link to="/pitch">See what this is, with a live demo</Link>.
            </p>
          </>
        )}

        {!production && <LoginTour onSelectTab={setTab} />}

        <div className="pill-select" data-tour="login-tabs">
          {!production && (
            <>
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
              <button data-tour="tab-viewer" className={tab === "viewer" ? "active" : ""} onClick={() => setTab("viewer")}>
                Compliance viewer
                <Hint>Sign in with org-wide visibility — readiness, controls, gaps, tasks, evidence and the audit trail — and no ability to change anything.</Hint>
              </button>
              <button data-tour="tab-auditor" className={tab === "auditor" ? "active" : ""} onClick={() => setTab("auditor")}>
                Auditor
                <Hint>Sign in as the reviewer — record verdicts, lock controls, and see only the frameworks this engagement covers.</Hint>
              </button>
              <button data-tour="tab-firm" className={tab === "firm" ? "active" : ""} onClick={() => setTab("firm")}>
                Audit firm
                <Hint>Sign in on the firm's side of the table — approve who gets onboarded, and staff your auditors onto the clients they are allowed to work.</Hint>
              </button>
            </>
          )}
          <button data-tour="tab-request" className={tab === "request" ? "active" : ""} onClick={() => setTab("request")}>
            Request an audit
            <Hint>The prospect's entry point: ask a firm to audit you. It creates no account — approval by the firm is what does that.</Hint>
          </button>
          {oidcConfigured() && (
            <button className={tab === "sso" ? "active" : ""} onClick={() => setTab("sso")}>
              Sign in
              <Hint>Sign in via your organisation's identity provider (see docs/adr/011-oidc-auth.md).</Hint>
            </button>
          )}
        </div>

        {!production && tab === "quickstart" && <QuickStart onDone={() => navigate("/overview")} />}
        {!production && tab === "firm" && <FirmStart onDone={() => navigate("/firm")} />}
        {tab === "request" && <RequestAudit />}
        {tab === "sso" && (
          <div className="form-grid">
            <p className="muted">Redirects to the configured identity provider.</p>
            <button className="btn btn-primary" onClick={() => void startLogin()}>Continue with SSO</button>
          </div>
        )}
        {!production && tab === "org" && (
          <IdForm
            label="Organisation id"
            placeholder="paste an organisation id"
            onSubmit={(id) => {
              setIdentity({ kind: "org", id, label: "Organisation admin" });
              navigate("/overview");
            }}
          />
        )}
        {!production && tab === "user" && (
          <IdForm
            label="User id"
            placeholder="paste a control-owner user id"
            onSubmit={(id) => {
              setIdentity({ kind: "user", id, label: "Control owner" });
              navigate("/tasks");
            }}
          />
        )}
        {!production && tab === "viewer" && (
          <IdForm
            label="User id"
            placeholder="paste a compliance-viewer user id"
            onSubmit={(id) => {
              setIdentity({ kind: "user", id, label: "Compliance viewer", role: "COMPLIANCE_VIEWER" });
              navigate("/overview");
            }}
          />
        )}
        {!production && tab === "auditor" && (
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
  );
  return embedded ? card : <div className="login-shell">{card}</div>;
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
      setIdentity({ kind: "user", id: admin.id, label: `${firmName} (firm admin)`, role: "FIRM_ADMIN" });
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
        Request sent. Nothing exists for you yet — once the firm approves it, your organisation and
        engagement are created and you can sign in with the email you gave us.
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
