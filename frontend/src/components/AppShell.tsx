import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useSession } from "../lib/session";
import { Hint } from "./Hint";

const ORG_NAV = [
  {
    to: "/overview", label: "Overview",
    hint: "Your compliance snapshot — readiness by framework, open gaps, and how much duplicate evidence work has been avoided.",
  },
  {
    to: "/evidence", label: "Evidence",
    hint: "Upload a document once — it's automatically evaluated against every framework you're subscribed to, with page-level proof for every extracted fact.",
  },
  {
    to: "/controls", label: "Controls",
    hint: "Every requirement your organisation is measured against, with its current verdict, linked evidence, and lock status.",
  },
  {
    to: "/gaps", label: "Gaps",
    hint: "Exactly what's missing or wrong in your evidence, and the specific fix required — not a generic 'insufficient evidence'.",
  },
  {
    to: "/tasks", label: "Tasks",
    hint: "One remediation task per gap. Closes itself automatically once a corrected upload actually fixes the problem.",
  },
  {
    to: "/admin", label: "Admin",
    hint: "Bootstrap tools — invite a team member, register a control, assign it to someone, or close an engagement.",
  },
];

const OWNER_NAV = [
  { ...ORG_NAV[4], label: "My tasks" },
  { ...ORG_NAV[2], label: "My controls" },
  ORG_NAV[1],
];

const AUDITOR_NAV = [
  { ...ORG_NAV[2], label: "Review queue" },
  ORG_NAV[1],
  ORG_NAV[3],
  { ...ORG_NAV[0], label: "Engagement overview" },
];

export function AppShell() {
  const { identity, setIdentity } = useSession();
  const navigate = useNavigate();
  const isAuditor = identity?.kind === "auditor" || (identity?.kind === "oidc" && Boolean(identity.engagementId));
  const nav = identity?.kind === "user" ? OWNER_NAV : isAuditor ? AUDITOR_NAV : ORG_NAV;

  const switchIdentity = () => {
    setIdentity(null);
    navigate("/login");
  };

  return (
    <div className="app-shell">
      <nav className="sidebar">
        <h1>GRC Workspace</h1>
        {nav.map((item) => (
          <NavLink key={item.to} to={item.to} className={({ isActive }) => (isActive ? "active" : "")}>
            {item.label}
            <Hint>{item.hint}</Hint>
          </NavLink>
        ))}
        {import.meta.env.VITE_CISO_ASSISTANT_URL && (
          <a href={import.meta.env.VITE_CISO_ASSISTANT_URL} target="_blank" rel="noreferrer">
            Risk &amp; policy ↗
            <Hint>Opens CISO Assistant — risk register, vendor/TPRM and policy management for this org (see docs/adr/010-ciso-assistant-integration.md). This app only pushes verdicts and gaps into it; edit risk/policy/vendor data there.</Hint>
          </a>
        )}
        {identity && (
          <div className="identity-box">
            <strong>{identity.label}</strong>
            <div className="mono">
              {identity.kind === "oidc" ? "sso" : `${identity.kind}:${identity.id.slice(0, 8)}…`}
            </div>
            <p style={{ margin: "6px 0 0", opacity: 0.85 }}>
              What you see below is restricted to what this identity can access — enforced by the
              backend, not just hidden in this menu.
            </p>
            <button onClick={switchIdentity}>Switch identity</button>
          </div>
        )}
      </nav>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
