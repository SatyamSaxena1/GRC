import type { Identity } from "../api/client";

// The sidebar's menus, shared with the login page so the feature map it draws
// for each role is exactly the menu that role gets after signing in.

export type NavItem = { to: string; label: string; hint: string };

export const ORG_NAV: NavItem[] = [
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
  {
    to: "/dpdp/operations", label: "Breach & DSR log",
    hint: "Log an actual breach or a data-principal rights/grievance request and track it to its DPDP deadline — the operational counterpart to the readiness checklist.",
  },
  {
    to: "/ciso-sync", label: "CISO sync",
    hint: "Every locked verdict and resolved gap pushed to CISO Assistant, and whether it actually landed — retry a failed one by hand.",
  },
  {
    to: "/map", label: "Evidence map",
    hint: "Every artefact and every control it satisfies, as one 3D graph: see which single upload is carrying the most frameworks and where the red verdicts cluster.",
  },
];

// Org-wide read, no setup surface — see docs/adr/017-compliance-officer-persona.md.
export const VIEWER_NAV: NavItem[] = ORG_NAV.filter((item) => item.to !== "/admin");

export const OWNER_NAV: NavItem[] = [
  { ...ORG_NAV[4], label: "My tasks" },
  { ...ORG_NAV[2], label: "My controls" },
  ORG_NAV[1],
  ORG_NAV[6],
  ORG_NAV[7],
  ORG_NAV[8],
  ORG_NAV[9],
  ORG_NAV[10],
  ORG_NAV[12],
];

export const FIRM_NAV: NavItem[] = [
  {
    to: "/firm", label: "Firm console",
    hint: "Your book of clients: who is waiting to be onboarded, who is staffed on what, and where each engagement stands. Approving a request here is what creates that client's workspace.",
  },
];

export const AUDITOR_NAV: NavItem[] = [
  { ...ORG_NAV[2], label: "Review queue" },
  ORG_NAV[1],
  ORG_NAV[3],
  { ...ORG_NAV[0], label: "Engagement overview" },
  ORG_NAV[6],
  ORG_NAV[7],
  ORG_NAV[8],
  ORG_NAV[9],
  ORG_NAV[10],
  ORG_NAV[12],
];

export function isAuditorIdentity(identity: Identity | null): boolean {
  return identity?.kind === "auditor" || (identity?.kind === "oidc" && Boolean(identity.engagementId));
}

export function navFor(identity: Identity | null): NavItem[] {
  // A firm identity keeps the console in reach at all times, and gains the
  // auditee-shaped review screens only once it has opened a client.
  // A firm admin signed in as a user carries role FIRM_ADMIN, so it gets the
  // console rather than the control-owner menu before it opens a client.
  const isFirm = identity?.kind === "firm"
    || (identity?.kind === "user" && (Boolean(identity.engagementId) || identity.role === "FIRM_ADMIN"));
  const isViewer = identity?.kind === "user" && identity.role === "COMPLIANCE_VIEWER";
  return isFirm
    ? [...FIRM_NAV, ...(identity && "engagementId" in identity && identity.engagementId ? AUDITOR_NAV : [])]
    : isViewer ? VIEWER_NAV
    : identity?.kind === "user" ? OWNER_NAV : isAuditorIdentity(identity) ? AUDITOR_NAV : ORG_NAV;
}

// Every screen in the product, grouped by the job it does — the login page's
// feature map draws one node per entry. Notifications is in every menu, just
// rendered separately (AppShell's NotificationsLink), so it is listed here too.
const STAGE: Record<string, string> = {
  "/evidence": "Collect", "/map": "Collect",
  "/overview": "Assess", "/controls": "Assess", "/gaps": "Assess",
  "/tasks": "Act", "/notifications": "Act", "/dpdp/operations": "Act", "/admin": "Act",
  "/firm": "Assure", "/activity": "Assure", "/ciso-sync": "Assure",
  "/ai-compliance": "Regulate", "/dpdp": "Regulate", "/glossary": "Regulate",
};

export const FEATURES: { to: string; label: string; stage: string }[] = [
  ...ORG_NAV, ...FIRM_NAV, { to: "/notifications", label: "Notifications", hint: "" },
].map((item) => ({ to: item.to, label: item.label, stage: STAGE[item.to] ?? "Regulate" }));

/** The routes an identity can open: its menu plus notifications. */
export function reachOf(identity: Identity | null): Set<string> {
  return new Set([...navFor(identity).map((item) => item.to), "/notifications"]);
}
