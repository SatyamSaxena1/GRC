// One fetch wrapper. Two identity shapes reach the backend (see app/auth.py):
// the stub scheme token ("org:<id>" / "user:<id>" / "auditor:<engagement_id>"),
// or a real OIDC JWT plus an optional engagement selection for an auditor
// (app/oidc.py, docs/adr/011-oidc-auth.md). Both are additive on the backend,
// so both stay selectable here rather than one replacing the other.

export type Identity =
  // `engagementId` is the client a firm-side user is currently working in. It
  // travels as x-engagement-id, exactly as it does for OIDC, so the ordinary
  // auditee-shaped screens work unchanged once an auditor picks a client.
  | { kind: "org" | "user" | "auditor" | "firm"; id: string; label: string; engagementId?: string }
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
  const headers: Record<string, string> = { Authorization: `${identity.kind}:${identity.id}` };
  if (identity.engagementId) headers["x-engagement-id"] = identity.engagementId;
  return headers;
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

// ---------------------------------------------------------------- audit firm

export const createFirmUser = (email: string, audit_firm_id: string, role: string) =>
  anon<{ id: string; role: string }>("POST", "/admin/users", { email, audit_firm_id, role });

export type OnboardingRequestRow = {
  id: string;
  org_name: string;
  contact_email: string;
  registration_detail: string;
  frameworks: string[];
  status: "PENDING" | "APPROVED" | "REJECTED";
  decision_note: string;
  org_id: string | null;
  engagement_id: string | null;
  created_at: string;
  decided_at: string | null;
};

/** Sent by a prospect who has no identity yet — approval is what creates one. */
export const submitOnboardingRequest = (body: {
  audit_firm_id: string;
  org_name: string;
  contact_email: string;
  registration_detail: string;
  frameworks: string[];
}) => anon<{ id: string; status: string }>("POST", "/firm/onboarding-requests", body);

export const listOnboardingRequests = (status?: string) =>
  request<{ requests: OnboardingRequestRow[] }>("GET", "/firm/onboarding-requests", { query: { status } });

export const approveOnboarding = (requestId: string, frameworks: string[] | null, note: string) =>
  request<{ id: string; org_id: string; engagement_id: string; frameworks: string[] }>(
    "POST", `/firm/onboarding-requests/${requestId}/approve`, { json: { frameworks, note } });

export const rejectOnboarding = (requestId: string, note: string) =>
  request<{ id: string; status: string }>("POST", `/firm/onboarding-requests/${requestId}/reject`, { json: { note } });

export type FirmEngagement = {
  id: string;
  org_id: string;
  org_name: string;
  status: string;
  frameworks: string[];
  auditors: { user_id: string; email: string; role: string; assigned_at: string }[];
  progress: { controls: number; evaluated: number; locked: number; open_gaps: number };
};

export const listFirmEngagements = () =>
  request<{ engagements: FirmEngagement[] }>("GET", "/firm/engagements");

export const listFirmAuditors = () =>
  request<{ auditors: { id: string; email: string; role: string }[] }>("GET", "/firm/auditors");

export const staffAuditor = (engagementId: string, userId: string) =>
  request<{ id: string; user_id: string }>("POST", `/firm/engagements/${engagementId}/auditors`, { json: { user_id: userId } });

export const unstaffAuditor = (engagementId: string, userId: string) =>
  request<void>("DELETE", `/firm/engagements/${engagementId}/auditors/${userId}`);

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
export const reprocessEvidence = (evidenceId: string) =>
  request<EvidenceUploadResult>("POST", `/evidence/${evidenceId}/reprocess`);

export type EvidenceUploadMetadata = {
  description?: string;
  validUntil?: string;     // yyyy-mm-dd
  isEncrypted?: boolean;
};
export function uploadEvidence(
  file: File, artefactType: string, meta: EvidenceUploadMetadata = {},
): Promise<EvidenceUploadResult> {
  const form = new FormData();
  form.append("file", file);
  if (meta.description) form.append("description", meta.description);
  if (meta.validUntil) form.append("valid_until", meta.validUntil);
  if (meta.isEncrypted) form.append("is_encrypted", "true");
  return request("POST", `/evidence?artefact_type=${encodeURIComponent(artefactType)}`, { form });
}

export function uploadEvidenceVersion(
  evidenceId: string, file: File, artefactType?: string,
): Promise<EvidenceUploadResult> {
  const form = new FormData();
  form.append("file", file);
  const path = artefactType
    ? `/evidence/${evidenceId}/versions?artefact_type=${encodeURIComponent(artefactType)}`
    : `/evidence/${evidenceId}/versions`;
  return request("POST", path, { form });
}

export const updateEvidenceMetadata = (
  evidenceId: string, body: { description?: string | null; valid_until?: string | null },
) => request<{ id: string; description: string | null; valid_until: string | null }>(
  "PATCH", `/evidence/${evidenceId}`, { json: body },
);

export const deleteEvidence = (evidenceId: string) =>
  request<void>("DELETE", `/evidence/${evidenceId}`);

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
  // Present only when the caller is an auditor — absent (not merely empty) for
  // everyone else. See docs/adr/012-auditor-only-ai-nutshell.md.
  nutshell?: string;
  // Visible to every role — see docs/adr/013-organization-defined-commitments.md.
  commitment_stale: boolean;
  stale_reason: string;
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

// ---------------------------------------------------------------- live pipeline events

/** A gap as it arrives on the live stream: the evaluator's finding, before the
 * GapRow it will be persisted as exists. No id and no status yet — deliberately
 * a narrower type than `Gap` rather than a `Gap` with holes in it, so a
 * consumer can't reach for a field that isn't there. */
export type StreamedGap = {
  kind: string;
  attribute: string;
  detail: string;
  actual_value: string | null;
  required_value: string | null;
};
export type StreamedLink = {
  id: string; framework: string; clause: string;
  verdict: string; locked: boolean; gaps: StreamedGap[];
};

export type PipelineEvent =
  | { event: "status"; data: { status: string; detail: string } }
  | { event: "attribute"; data: EvidenceAttribute }
  | { event: "link"; data: StreamedLink }
  | { event: "ping"; data: Record<string, never> }
  | { event: "done"; data: { evidence_id: string } };

/** Watch a running pipeline. Uses fetch + a stream reader rather than
 * EventSource, which cannot send the Authorization header this app
 * authenticates with. Returns an abort function; the caller must still treat
 * the ordinary endpoints as the source of truth — this is a live preview of
 * work being persisted anyway (see app/events.py). */
export function streamEvidenceEvents(
  id: string,
  onEvent: (e: PipelineEvent) => void,
): () => void {
  const controller = new AbortController();

  void (async () => {
    try {
      const res = await fetch(new URL(`/evidence/${id}/events`, window.location.origin), {
        headers: authHeaders(),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) return;
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) return;
        buffer += decoder.decode(value, { stream: true });
        // SSE frames are separated by a blank line
        let split: number;
        while ((split = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, split);
          buffer = buffer.slice(split + 2);
          let name = "";
          let payload = "";
          for (const line of frame.split("\n")) {
            if (line.startsWith("event: ")) name = line.slice(7).trim();
            else if (line.startsWith("data: ")) payload += line.slice(6);
          }
          if (!name) continue;
          try {
            onEvent({ event: name, data: JSON.parse(payload || "{}") } as PipelineEvent);
          } catch {
            // a malformed frame is skipped, never surfaced as a fact
          }
        }
      }
    } catch {
      // Aborted, or the stream failed — the caller's polling fallback covers it.
    }
  })();

  return () => controller.abort();
}

export type RemediationDraft = { draft: string; evidence_needed: string[] };
/** Suggested wording that would close a gap. A drafting aid — it writes
 * nothing and cannot move a verdict (see ADR-004). */
export const draftRemediation = (gapId: string) =>
  request<RemediationDraft>("POST", `/gaps/${gapId}/draft-remediation`);

export type EvidenceDetail = {
  id: string;
  version: number;
  artefact_type: string;
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
  description: string | null;
  valid_until: string | null;
  is_encrypted: boolean;
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
  // Auditor-only — see EvidenceLink.nutshell above.
  nutshell?: string;
  commitment_stale: boolean;
  stale_reason: string;
};
export type ControlDetail = {
  id: string; framework: string; clause: string; title: string; text: string;
  owner_emails: string[]; locked: boolean; links: ControlLinkRow[];
};
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
  status: "OPEN" | "DONE";
  is_manual: boolean;
  gap_id: string | null;
  framework: string | null;
  clause: string | null;
  required_action: string;
  detail: string;
  actual_value: string | null;
  required_value: string | null;
  evidence_id: string | null;
  owner_user_id: string | null;
  owner_email: string | null;
  due_at: string | null;
  priority: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  created_by: string;
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
export const updateTask = (
  id: string,
  update: Partial<{ owner_user_id: string | null; due_at: string | null; priority: string; status: "OPEN" | "DONE" }>
) => request<TaskRow>("PATCH", `/tasks/${id}`, { json: update });
export const createTask = (task: {
  title: string;
  description?: string;
  owner_user_id?: string | null;
  due_at?: string | null;
  priority?: string;
  org_control_id?: string | null;
}) => request<TaskRow>("POST", "/tasks", { json: task });

// ---------------------------------------------------------------- control messages

export type ControlMessage = {
  id: string;
  org_control_id: string;
  kind: "EVIDENCE_REQUEST" | "UNLOCK_REQUEST" | "COMMENT";
  body: string;
  status: "OPEN" | "RESOLVED";
  created_by: string;
  created_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
  resolution_note: string | null;
};
export const listControlMessages = (controlId: string) =>
  request<ControlMessage[]>("GET", `/controls/${controlId}/messages`);
export const postControlMessage = (controlId: string, kind: ControlMessage["kind"], body: string) =>
  request<ControlMessage>("POST", `/controls/${controlId}/messages`, { json: { kind, body } });
export const resolveControlMessage = (controlId: string, messageId: string, resolutionNote: string) =>
  request<ControlMessage>("PATCH", `/controls/${controlId}/messages/${messageId}/resolve`, {
    json: { resolution_note: resolutionNote },
  });

export type RequestRow = ControlMessage & { framework: string; clause: string };
export const listRequests = (filters: { status?: string; kind?: string } = {}) =>
  request<RequestRow[]>("GET", "/requests", { query: filters });

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

export type ExpiringEvidence = {
  evidence_id: string;
  original_filename: string;
  artefact_type: string;
  clauses: string[];
  detail: string;
};
export type StalledEvidence = {
  evidence_id: string;
  original_filename: string;
  status: string;
  age_minutes: number;
  detail: string;
};
export type AttentionReport = {
  org_id: string;
  checked_at: string;
  horizon_days: number;
  total: number;
  expired: ExpiringEvidence[];
  expiring_soon: ExpiringEvidence[];
  stuck: StalledEvidence[];
  failed: StalledEvidence[];
};
export const getAttention = () => request<AttentionReport>("GET", "/analytics/attention");

export type Dashboard = {
  controls: { total: number; locked: number; by_verdict: Record<string, number> };
  gaps_open: number;
  tasks_open: number;
  requests_open: number;
  evidence: { ready: number; total: number };
  reuse: ReuseStats;
  readiness: FrameworkReadiness[];
  attention: AttentionReport;
};
/** Everything Overview needs, in one round trip — see docs/adr's dashboard note
 * and app/routers/analytics.py::dashboard. Replaces what used to be 7 separate
 * calls plus one GET /controls/{id} per control. */
export const getDashboard = () => request<Dashboard>("GET", "/analytics/dashboard");

// ---------------------------------------------------------------- notifications

export type NotificationItem = {
  kind: string;
  severity: string;
  message: string;
  link: string;
  at: string;
};
export const listNotifications = () =>
  request<{ items: NotificationItem[]; count: number }>("GET", "/notifications");

// ---------------------------------------------------------------- glossary

/** Reference data, identical for every org. Two layers: ~70 curated entries
 * hand-written in app/content/glossary.yaml, and ~3.9k imported verbatim from
 * NIST's public-domain CSRC glossary (`imported: true`). `source` names the
 * document that settles the wording — a law outranks a standard outranks
 * PLATFORM, our own — so a definition is attributable, not merely asserted. */
export type GlossaryTerm = {
  term: string;
  /** The cited source's own words when `source` names a publication. */
  definition: string;
  /** Our editorial gloss, deliberately separate so a quoted definition is never
   * mixed with our commentary under that source's citation. */
  note: string;
  source: string;
  source_url: string;
  aliases: string[];
  tags: string[];
  imported: boolean;
};
/** With no `q`, this returns the curated layer only — the imported corpus is
 * reachable by searching, never by scrolling past it. */
export const listGlossary = (filters: { q?: string; tag?: string; limit?: number } = {}) =>
  request<GlossaryTerm[]>("GET", "/glossary", { query: filters });
export const getGlossaryTerm = (name: string) =>
  request<GlossaryTerm>("GET", `/glossary/${encodeURIComponent(name)}`);

// ---------------------------------------------------------------- activity

export type ActivityEvent = {
  action: string;
  actor: string;
  entity_type: string;
  entity: string;
  detail: Record<string, unknown>;
  reason: string;
  at: string;
};
export const getActivity = () => request<ActivityEvent[]>("GET", "/activity");

// ---------------------------------------------------------------- export

/** Triggers a browser download of an authenticated response. There is no
 * cookie session here — every request carries a custom Authorization header
 * (see authHeaders above) — so a plain `<a href>` can't work; fetch, blob,
 * and a throwaway object URL is the standard workaround. */
export async function downloadFile(
  path: string, filename: string, params: Record<string, string | undefined> = {},
): Promise<void> {
  const url = new URL(path, window.location.origin);
  for (const [key, value] of Object.entries(params)) {
    if (value) url.searchParams.set(key, value);
  }
  const res = await fetch(url, { headers: authHeaders() });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
}
export const downloadComplianceExport = (format: "csv" | "xlsx" = "csv", params: Record<string, string | undefined> = {}) =>
  downloadFile(`/export/compliance.${format}`, `compliance-export.${format}`, params);
export const downloadGapsExport = (params: Record<string, string | undefined> = {}) =>
  downloadFile("/export/gaps.xlsx", "gaps-export.xlsx", params);
export const downloadTasksExport = (params: Record<string, string | undefined> = {}) =>
  downloadFile("/export/tasks.xlsx", "tasks-export.xlsx", params);

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
