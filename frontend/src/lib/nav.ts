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
  {
    to: "/code-review", label: "Code review",
    hint: "Your organisation's review standard: versioned, hashed rules every pull request is checked against. Rules decide; a model only advises.",
  },
  {
    to: "/questionnaire", label: "Questionnaires",
    hint: "Paste a customer's security questions and get draft answers from your own controls. The Yes, Partly or No comes from your verdicts; a model only words it.",
  },
  {
    to: "/vendors", label: "Vendors",
    hint: "The third parties you depend on, each with a risk tier from fixed rules and a review date that tells you when it is due.",
  },
  {
    to: "/connections", label: "Connections",
    hint: "Connect your team chat so alerts and the Monday summary reach you. What you paste is stored encrypted and never shown again.",
  },
  {
    to: "/frameworks", label: "Frameworks",
    hint: "One page per framework: how much your evidence already meets, and exactly which clauses still need something.",
  },
  {
    to: "/policies", label: "Policies",
    hint: "Your organisation's own policies: an admin approves each version and every person accepts it for themselves.",
  },
  {
    to: "/risks", label: "Risks",
    hint: "What could go wrong, how bad it is by fixed rules, what you are doing about it, who owns it and when it is next reviewed. A model may suggest wording; it never sets a score.",
  },
  {
    to: "/training", label: "Training",
    hint: "Short courses every person reads and confirms they understood, repeated every year. An admin writes them; the page shows who is up to date.",
  },
];

// Everyone on the organisation's side reads and accepts policies, so the owner menu carries it too.
const POLICIES = ORG_NAV.find((item) => item.to === "/policies")!;

// Org-wide read, no setup surface — see docs/adr/017-compliance-officer-persona.md.
export const VIEWER_NAV: NavItem[] = ORG_NAV.filter((item) => item.to !== "/admin" && item.to !== "/connections");

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
  ORG_NAV[13],
  POLICIES,
  ORG_NAV.find((item) => item.to === "/training")!,
  // By path, not index: a control owner sees only the risks that name them as owner (ADR-057).
  ORG_NAV.find((item) => item.to === "/risks")!,
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
  ORG_NAV[13],
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
  "/overview": "Assess", "/frameworks": "Assess", "/questionnaire": "Assure", "/vendors": "Assess", "/connections": "Act", "/risks": "Assess", "/controls": "Assess", "/gaps": "Assess", "/code-review": "Assess",
  "/tasks": "Act", "/policies": "Act", "/training": "Act", "/notifications": "Act", "/dpdp/operations": "Act", "/admin": "Act",
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
