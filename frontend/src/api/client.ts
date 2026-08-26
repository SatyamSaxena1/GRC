// One fetch wrapper. Two identity shapes reach the backend (see app/auth.py):
// the stub scheme token ("org:<id>" / "user:<id>" / "auditor:<engagement_id>"),
// or a real OIDC JWT plus an optional engagement selection for an auditor
// (app/oidc.py, docs/adr/011-oidc-auth.md). Both are additive on the backend,
// so both stay selectable here rather than one replacing the other.

export type Identity =
  | { kind: "org" | "user" | "auditor"; id: string; label: string }
  | { kind: "oidc"; token: string; label: string; engagementId?: string };

const STORAGE_KEY = "grc.identity";

export function loadIdentity(): Identity | null {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Identity;
  } catch {
    return null;
  }
}

export function saveIdentity(identity: Identity | null): void {
  if (identity) localStorage.setItem(STORAGE_KEY, JSON.stringify(identity));
  else localStorage.removeItem(STORAGE_KEY);
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

function authHeaders(): Record<string, string> {
  const identity = loadIdentity();
  if (!identity) throw new ApiError(401, "no identity selected");
  if (identity.kind === "oidc") {
    const headers: Record<string, string> = { Authorization: `Bearer ${identity.token}` };
    if (identity.engagementId) headers["x-engagement-id"] = identity.engagementId;
    return headers;
  }
  return { Authorization: `${identity.kind}:${identity.id}` };
}

async function handle<T>(res: Response): Promise<T> {
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const body = text ? safeJson(text) : undefined;
  if (!res.ok) {
    const detail = (body as { detail?: unknown } | undefined)?.detail ?? body ?? res.statusText;
    throw new ApiError(res.status, detail);
  }
  return body as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function request<T>(method: string, path: string, opts: { json?: unknown; query?: Record<string, string | number | undefined>; form?: FormData } = {}): Promise<T> {
  const url = new URL(path, window.location.origin);
  for (const [key, value] of Object.entries(opts.query ?? {})) {
    if (value !== undefined && value !== "") url.searchParams.set(key, String(value));
  }

  const headers: Record<string, string> = authHeaders();
  let body: BodyInit | undefined;
  if (opts.form) {
    body = opts.form; // browser sets multipart boundary itself
  } else if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  }

  const res = await fetch(url.toString(), { method, headers, body });
  return handle<T>(res);
}

/** Same as `request`, but does not require an identity — used only for admin bootstrap. */
async function anon<T>(method: string, path: string, json?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: json !== undefined ? { "Content-Type": "application/json" } : {},
    body: json !== undefined ? JSON.stringify(json) : undefined,
  });
  return handle<T>(res);
}

// ---------------------------------------------------------------- admin (bootstrap)

export type OrgOut = { id: string };
export const createOrganization = (name: string, frameworks: string[]) =>
  anon<OrgOut>("POST", "/admin/organizations", { name, frameworks });

export const createAuditFirm = (name: string) => anon<OrgOut>("POST", "/admin/audit-firms", { name });

export type EngagementOut = { id: string; frameworks: string[] };
export const createEngagement = (audit_firm_id: string, org_id: string, frameworks: string[]) =>
  anon<EngagementOut>("POST", "/admin/engagements", { audit_firm_id, org_id, frameworks });

export const closeEngagement = (engagementId: string) =>
  anon<{ id: string; status: string }>("POST", `/admin/engagements/${engagementId}/close`);

export const createUser = (email: string, org_id: string, role: string) =>
  anon<{ id: string; role: string }>("POST", "/admin/users", { email, org_id, role });

export const createControl = (org_id: string, framework: string, clause: string) =>
  anon<{ id: string }>("POST", "/admin/controls", { org_id, framework, clause });

export const assignControl = (org_control_id: string, user_id: string) =>
  anon<{ id: string }>("POST", "/admin/control-assignments", { org_control_id, user_id });

// ---------------------------------------------------------------- evidence

export type EvidenceSummary = {
  id: string;
  original_filename: string;
  artefact_type: string;
  version: number;
  lifecycle_status: string;
  status: string;
  quality_score: number | null;
  uploaded_by: string;
  created_at: string;
};
export const listEvidence = (filter: { artefact_type?: string; lifecycle_status?: string } = {}) =>
  request<EvidenceSummary[]>("GET", "/evidence", { query: filter });

export type EvidenceUploadResult = { evidence_id: string; id: string; status: string; version?: number };

export function uploadEvidence(file: File, artefactType: string): Promise<EvidenceUploadResult> {
  const form = new FormData();
  form.append("file", file);
  return request("POST", `/evidence?artefact_type=${encodeURIComponent(artefactType)}`, { form });
}

export function uploadEvidenceVersion(evidenceId: string, file: File): Promise<EvidenceUploadResult> {
  const form = new FormData();
  form.append("file", file);
  return request("POST", `/evidence/${evidenceId}/versions`, { form });
}

export type EvidenceStatus = {
  evidence_id: string;
  status: string;
  detail: string;
  lifecycle_status: string;
  quality_score: number | null;
};
export const getEvidenceStatus = (id: string) => request<EvidenceStatus>("GET", `/evidence/${id}/status`);

export type EvidenceAttribute = {
  name: string;
  value: unknown;
  confidence: number | null;
  extraction_method: string;
  sources: { page?: number; quote?: string }[];
};
export const getEvidenceAttributes = (id: string) =>
  request<EvidenceAttribute[]>("GET", `/evidence/${id}/attributes`);

export type Gap = {
  id: string;
  kind: string;
  attribute: string;
  detail: string;
  actual_value: string | null;
  required_value: string | null;
  required_action: string;
  status: string;
  resolved_at: string | null;
};
export type EvidenceLink = {
  id: string;
  framework: string;
  clause: string;
  verdict: string;
  auditor_verdict: string | null;
  confidence: number | null;
  ucos: string[];
  locked: boolean;
  gaps: Gap[];
};
export const getEvidenceEvaluations = (id: string) =>
  request<EvidenceLink[]>("GET", `/evidence/${id}/evaluations`);

export type AuditEventOut = {
  action: string;
  actor: string;
  entity_type?: string;
  entity?: string;
  detail: Record<string, unknown>;
  reason: string;
  at: string;
};
export const getEvidenceHistory = (id: string) =>
  request<AuditEventOut[]>("GET", `/evidence/${id}/history`);

export type EvidenceVersion = {
  id: string;
  version: number;
  lifecycle_status: string;
  status: string;
  sha256: string;
  original_filename: string;
};
export const getEvidenceVersions = (id: string) =>
  request<EvidenceVersion[]>("GET", `/evidence/${id}/versions`);

export type EvidenceDetail = {
  id: string;
  version: number;
  lifecycle_status: string;
  status: string;
  sha256: string;
  mime_type: string;
  size_bytes: number;
  original_filename: string;
  quality_score: number | null;
  quality: { score: number; max_score: number; dimensions: { name: string; score: number; weight: number; reason: string }[] } | null;
  download_url: string;
  extracted_attributes: Record<string, unknown>;
  links: EvidenceLink[];
};
export const getEvidence = (id: string) => request<EvidenceDetail>("GET", `/evidence/${id}`);

// ---------------------------------------------------------------- controls

export type ControlSummary = { id: string; framework: string; clause: string };
export const listControls = () => request<ControlSummary[]>("GET", "/controls");

export type ControlLinkRow = {
  id: string;
  evidence_id: string;
  verdict: string;
  auditor_verdict: string | null;
  locked: boolean;
};
export type ControlDetail = { id: string; framework: string; clause: string; locked: boolean; links: ControlLinkRow[] };
export const getControl = (id: string) => request<ControlDetail>("GET", `/controls/${id}`);

export type ControlEvidenceRow = {
  evidence_id: string;
  version: number;
  lifecycle_status: string;
  original_filename: string;
  verdict: string;
  locked: boolean;
};
export const getControlEvidence = (id: string) =>
  request<ControlEvidenceRow[]>("GET", `/controls/${id}/evidence`);

export const getControlHistory = (id: string) =>
  request<AuditEventOut[]>("GET", `/controls/${id}/history`);

export const submitControl = (id: string) =>
  request<{ id: string; submitted: boolean }>("POST", `/controls/${id}/submit`);

// ---------------------------------------------------------------- gaps & tasks

export type GapRow = Gap & { framework: string; clause: string; evidence_id: string; resolved_by_evidence_id: string | null };
export const listGaps = (status?: string) => request<GapRow[]>("GET", "/gaps", { query: { status } });

export type TaskRow = {
  id: string;
  title: string;
  status: string;
  gap_id: string;
  framework: string;
  clause: string;
  required_action: string;
  detail: string;
  actual_value: string | null;
  required_value: string | null;
  evidence_id: string;
  owner_user_id: string | null;
  owner_email: string | null;
  due_at: string | null;
  priority: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  created_at: string;
};
export type TaskFilters = { status?: string; priority?: string; owner_user_id?: string; q?: string };
export const listTasks = (filters: TaskFilters = {}) => request<TaskRow[]>("GET", "/tasks", { query: filters });
export type TaskOwner = { id: string; email: string };
export const listTaskOwners = () => request<TaskOwner[]>("GET", "/tasks/owners");
export type TaskDetail = TaskRow & {
  history: { action: string; actor: string; before: Record<string, unknown> | null; after: Record<string, unknown> | null; at: string }[];
};
export const getTask = (id: string) => request<TaskDetail>("GET", `/tasks/${id}`);
export const updateTask = (id: string, update: { owner_user_id: string | null; due_at: string | null; priority: string }) =>
  request<TaskRow>("PATCH", `/tasks/${id}`, { json: update });

// ---------------------------------------------------------------- audit (auditor actions)

export const recordVerdict = (linkId: string, verdict: string, reason: string) =>
  request<{ id: string; auditor_verdict: string; locked: boolean }>(
    "POST",
    `/audit/links/${linkId}/verdict`,
    { json: { verdict, reason } }
  );

export const lockLink = (linkId: string, verdict: string) =>
  request<{ id: string; verdict: string; locked: boolean }>("POST", `/audit/links/${linkId}/lock`, {
    json: { verdict },
  });

export const unlockLink = (linkId: string, reason: string) =>
  request<{ id: string; locked: boolean; unlock_reason: string }>(
    "POST",
    `/audit/links/${linkId}/unlock`,
    { json: { reason } }
  );

// ---------------------------------------------------------------- analytics

export type ReuseStats = {
  total_links: number;
  distinct_evidence: number;
  reused_links: number;
  reuse_rate: number;
  avoided_uploads: number;
  effort_hours_saved: number;
};
export const getReuseStats = () => request<ReuseStats>("GET", "/analytics/reuse");

export type FrameworkReadiness = {
  framework: string;
  already_subscribed: boolean;
  total_requirements: number;
  evaluated: number;
  satisfied: number;
  partial: number;
  readiness: number;
  clauses: { clause: string; title: string; verdict: string }[];
};
export const getReadinessAll = () => request<FrameworkReadiness[]>("GET", "/analytics/readiness");
export const getReadiness = (framework: string) =>
  request<FrameworkReadiness>("GET", `/analytics/readiness/${encodeURIComponent(framework)}`);

// ---------------------------------------------------------------- CISO Assistant sync

// One-way push of locked verdicts and resolved gaps into CISO Assistant — see
// app/ciso_sync.py and docs/adr/010-ciso-assistant-integration.md. This app
// never reads risk/policy/vendor data back; the deep link is the read path.
export type CisoSyncStatus = {
  entity_type: "evidence_control_link" | "gap";
  entity_id: string;
  status: "PENDING" | "OK" | "FAILED" | "SKIPPED";
  last_synced_at: string | null;
  error: string;
};
export const getCisoSyncStatus = () => request<CisoSyncStatus[]>("GET", "/admin/ciso-sync/status");
