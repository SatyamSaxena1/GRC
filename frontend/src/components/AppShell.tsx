import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { listNotifications } from "../api/client";
import { useApi } from "../lib/useApi";
import { useSession } from "../lib/session";
import { Hint } from "./Hint";
import { GettingStartedTour } from "./GettingStartedTour";
import { RoleSwitcher } from "./RoleSwitcher";
import { navFor } from "../lib/nav";

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

// Group headings only: the role menus in lib/nav.ts stay the single source of truth for
// who sees what. Items in no group (firm console, engagement views) render first.
const NAV_GROUPS: [string, string[]][] = [
  ["Work", ["/evidence", "/controls", "/gaps", "/tasks"]],
  ["Compliance", ["/overview", "/map", "/ai-compliance", "/dpdp", "/dpdp/operations", "/ciso-sync"]],
  ["Workspace", ["/activity", "/admin", "/glossary"]],
];

export function AppShell() {
  const { identity, setIdentity } = useSession();
  const navigate = useNavigate();
  const nav = navFor(identity);
  // Remount the page when the identity changes, so a role switch refetches
  // everything as the new person instead of showing the last one's data.
  const viewKey = identity ? `${identity.kind}:${"id" in identity ? identity.id : "sso"}:${identity.engagementId ?? ""}` : "none";

  const switchIdentity = () => {
    setIdentity(null);
    navigate("/login");
  };

  // Phones: the sidebar becomes a drawer behind a top bar (Escape and navigation close it).
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const grouped = new Set(NAV_GROUPS.flatMap(([, paths]) => paths));
  const ungrouped = nav.filter((i) => !grouped.has(i.to));
  const link = (item: (typeof nav)[number]) => (
    <NavLink key={item.to} to={item.to} data-tour={`nav-${item.to.slice(1)}`} className={({ isActive }) => (isActive ? "active" : "")}>
      {item.label}
      <Hint>{item.hint}</Hint>
    </NavLink>
  );

  return (
    <div className="app-shell">
      <div className="topbar">
        <button aria-label="Open menu" aria-expanded={open} aria-controls="primary-nav" onClick={() => setOpen(true)}>☰</button>
        GRC Workspace
      </div>
      <div className={`sidebar-backdrop${open ? " open" : ""}`} onClick={() => setOpen(false)} />
      <nav id="primary-nav" aria-label="Primary" className={`sidebar${open ? " open" : ""}`}>
        <h1>GRC Workspace</h1>
        <RoleSwitcher />
        <NotificationsLink key={viewKey} />
        {ungrouped.map(link)}
        {NAV_GROUPS.map(([title, paths]) => {
          const items = nav.filter((i) => paths.includes(i.to));
          return items.length > 0 && (
            <div key={title} style={{ display: "contents" }}>
              <div className="nav-group">{title}</div>
              {items.map(link)}
            </div>
          );
        })}
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
            <button onClick={switchIdentity}>Sign out</button>
          </div>
        )}
      </nav>
      <main className="main" key={viewKey}>
        <Outlet />
      </main>
    </div>
  );
}
