import type { Identity } from "../api/client";

// The five people a demo walks through. Each has one colour, and that colour is
// the whole app's accent while you are that person — so a screenshot, a shared
// screen or a glance at the sidebar always says whose eyes you are looking
// through. The colour is a UI hint only; what each role can reach is still
// decided by the backend (app/auth.py, app/authorization.py).

export type RoleId = "admin" | "owner" | "viewer" | "auditor" | "firm";

export type DemoWorld = {
  orgId: string;
  firmId: string;
  engagementId: string;
  ownerId: string;
  viewerId: string;
  firmAdminId: string;
  orgName: string;
  firmName: string;
};

export type RoleDef = {
  id: RoleId;
  name: string;
  swatch: string;      // colour name shown next to the swatch
  color: string;
  dark: string;
  side: "Auditee" | "Audit firm";
  who: string;         // one line: who this person is
  does: string[];      // what they can actually do — shown densely on the login deck
  home: string;
  key: string;         // keyboard shortcut digit
  identity: (w: DemoWorld) => Identity;
};

export const ROLES: RoleDef[] = [
  {
    id: "admin", name: "Org admin", swatch: "Harbour teal", color: "#0f9d8a", dark: "#0b7466",
    side: "Auditee", key: "1", home: "/overview",
    who: "Runs the audited company's workspace.",
    does: ["Upload evidence", "Invite owners", "Register controls", "Submit for review"],
    identity: (w) => ({ kind: "org", id: w.orgId, label: `${w.orgName} · Org admin`, persona: "admin" }),
  },
  {
    id: "owner", name: "Control owner", swatch: "Ember amber", color: "#d97706", dark: "#a55a04",
    side: "Auditee", key: "2", home: "/tasks",
    who: "An employee who owns a few specific controls.",
    does: ["Work assigned tasks", "Fix gaps", "Upload new versions", "Sees only own controls"],
    identity: (w) => ({ kind: "user", id: w.ownerId, label: "Priya · Control owner", persona: "owner" }),
  },
  {
    id: "viewer", name: "Compliance viewer", swatch: "Iris violet", color: "#7c3aed", dark: "#5b21b6",
    side: "Auditee", key: "3", home: "/overview",
    who: "Compliance officer with org-wide, read-only sight.",
    does: ["Readiness by framework", "Every gap and task", "Audit trail", "Cannot change anything"],
    identity: (w) => ({
      kind: "user", id: w.viewerId, label: "Dev · Compliance viewer", role: "COMPLIANCE_VIEWER", persona: "viewer",
    }),
  },
  {
    id: "auditor", name: "Auditor", swatch: "Signal crimson", color: "#e11d48", dark: "#b0133a",
    side: "Audit firm", key: "4", home: "/controls",
    who: "Reviews this one engagement, and nothing else.",
    does: ["Record verdicts", "Lock controls", "Request evidence", "Scoped to engaged frameworks"],
    identity: (w) => ({ kind: "auditor", id: w.engagementId, label: `${w.firmName} · Auditor`, persona: "auditor" }),
  },
  {
    id: "firm", name: "Firm admin", swatch: "Cobalt", color: "#2563eb", dark: "#1d4ed8",
    side: "Audit firm", key: "5", home: "/firm",
    who: "Runs the audit firm's book of clients.",
    does: ["Approve onboarding", "Staff auditors", "Track every client", "Open any engagement"],
    identity: (w) => ({
      kind: "user", id: w.firmAdminId, label: `${w.firmName} · Firm admin`, role: "FIRM_ADMIN", persona: "firm",
    }),
  },
];

export const roleById = (id: RoleId) => ROLES.find((r) => r.id === id)!;

/** Which of the five an identity is, including ones signed in by hand or via
 *  SSO, so every session gets a colour — not only demo ones. */
export function roleOf(identity: Identity | null): RoleDef | null {
  if (!identity) return null;
  if ("persona" in identity && identity.persona) return roleById(identity.persona as RoleId);
  if (identity.kind === "org") return roleById("admin");
  if (identity.kind === "auditor") return roleById("auditor");
  if (identity.kind === "firm") return roleById("firm");
  if (identity.kind === "oidc") return roleById(identity.role === "FIRM_ADMIN" ? "firm" : identity.engagementId ? "auditor" : "admin");
  if (identity.role === "COMPLIANCE_VIEWER") return roleById("viewer");
  if (identity.role === "FIRM_ADMIN") return roleById("firm");
  if (identity.engagementId) return roleById("auditor");
  return roleById("owner");
}

/** Repaint the app in a role's colour. `--primary` is what every button, link,
 *  active tab and focus ring already uses, so one variable re-themes it all. */
export function applyRoleTheme(role: RoleDef | null): void {
  const root = document.documentElement;
  if (!role) {
    for (const v of ["--primary", "--primary-dark", "--role", "--role-dark"]) root.style.removeProperty(v);
    delete root.dataset.role;
    return;
  }
  root.style.setProperty("--primary", role.color);
  root.style.setProperty("--primary-dark", role.dark);
  root.style.setProperty("--role", role.color);
  root.style.setProperty("--role-dark", role.dark);
  root.dataset.role = role.id;
}
