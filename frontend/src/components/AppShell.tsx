import { useEffect } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { listNotifications } from "../api/client";
import { useApi } from "../lib/useApi";
import { useSession } from "../lib/session";
import { Hint } from "./Hint";
import { GettingStartedTour } from "./GettingStartedTour";

// No persisted read/unread state (see app/routers/notifications.py) — the
// count is "how many open items right now," refreshed every 60s so it isn't
// permanently stale for a session left open.
function NotificationsLink() {
  const notifications = useApi(() => listNotifications(), []);
  useEffect(() => {
    const id = window.setInterval(notifications.reload, 60_000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const count = notifications.data?.count ?? 0;
  return (
    <NavLink to="/notifications" data-tour="nav-notifications" className={({ isActive }) => (isActive ? "active" : "")}>
      Notifications{count > 0 && ` (${count})`}
      <Hint>Everything open right now that needs a look — tasks, requests from your auditor, and evidence going stale.</Hint>
    </NavLink>
  );
}

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
  // Appended, not inserted — OWNER_NAV/AUDITOR_NAV below pick specific ORG_NAV
  // entries by index, so a new item here must never shift the existing ones.
  {
    to: "/activity", label: "Activity",
    hint: "Everything that happened across your workspace, most recent first — one chronological view instead of digging through each control or evidence item's own history.",
  },
  {
    to: "/glossary", label: "Glossary",
    hint: "What the words on screen mean, and which document says so — a law or regulation outranks a standard, which outranks our own wording. Search by acronym too.",
  },
  {
    to: "/ai-compliance", label: "AI compliance",
    hint: "Turn NIST AI RMF outcomes into evidence, accountable ownership, and a practical AI governance work queue.",
  },
  {
    to: "/dpdp", label: "DPDP readiness",
    hint: "Run an evidence-backed DPDP readiness assessment and see whether AWS, Microsoft 365, Google Workspace and HRMS are actually connected.",
  },
];

// Org-wide read, no setup surface — see docs/adr/017-compliance-officer-persona.md.
const VIEWER_NAV = ORG_NAV.filter((item) => item.to !== "/admin");

const OWNER_NAV = [
  { ...ORG_NAV[4], label: "My tasks" },
  { ...ORG_NAV[2], label: "My controls" },
  ORG_NAV[1],
  ORG_NAV[6],
  ORG_NAV[7],
  ORG_NAV[8],
  ORG_NAV[9],
];

const FIRM_NAV = [
  {
    to: "/firm", label: "Firm console",
    hint: "Your book of clients: who is waiting to be onboarded, who is staffed on what, and where each engagement stands. Approving a request here is what creates that client's workspace.",
  },
];

const AUDITOR_NAV = [
  { ...ORG_NAV[2], label: "Review queue" },
  ORG_NAV[1],
  ORG_NAV[3],
  { ...ORG_NAV[0], label: "Engagement overview" },
  ORG_NAV[6],
  ORG_NAV[7],
  ORG_NAV[8],
  ORG_NAV[9],
];

export function AppShell() {
  const { identity, setIdentity } = useSession();
  const navigate = useNavigate();
  const isAuditor = identity?.kind === "auditor" || (identity?.kind === "oidc" && Boolean(identity.engagementId));
  // A firm identity keeps the console in reach at all times, and gains the
  // auditee-shaped review screens only once it has opened a client.
  const isFirm = identity?.kind === "firm" || (identity?.kind === "user" && Boolean(identity.engagementId));
  const isViewer = identity?.kind === "user" && identity.role === "COMPLIANCE_VIEWER";
  const nav = isFirm
    ? [...FIRM_NAV, ...(identity && "engagementId" in identity && identity.engagementId ? AUDITOR_NAV : [])]
    : isViewer ? VIEWER_NAV
    : identity?.kind === "user" ? OWNER_NAV : isAuditor ? AUDITOR_NAV : ORG_NAV;

  const switchIdentity = () => {
    setIdentity(null);
    navigate("/login");
  };

  return (
    <div className="app-shell">
      <nav className="sidebar">
        <h1>GRC Workspace</h1>
        <NotificationsLink />
        {nav.map((item) => (
          <NavLink key={item.to} to={item.to} data-tour={`nav-${item.to.slice(1)}`} className={({ isActive }) => (isActive ? "active" : "")}>
            {item.label}
            <Hint>{item.hint}</Hint>
          </NavLink>
        ))}
        <GettingStartedTour />
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
