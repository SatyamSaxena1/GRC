/** Audit events in words. The raw action code and actor label are the record and stay on screen
 *  (muted); this only adds a sentence so a person can read the trail. Unknown actions fall back to
 *  the raw code, so a new backend event is never hidden or mis-described. */

export type EventLike = {
  action: string;
  actor: string;
  actor_display?: string;
  detail?: Record<string, unknown> | null;
  reason?: string;
};

type Detail = Record<string, unknown>;
const str = (v: unknown) => (typeof v === "string" && v ? v : "");
const overrode = (d: Detail) => (str(d.overrides_engine_verdict) ? ` (overriding the rules' ${str(d.overrides_engine_verdict)})` : "");

const SENTENCES: Record<string, (d: Detail) => string> = {
  EVIDENCE_UPLOADED: () => "uploaded evidence",
  EVIDENCE_PROCESSED: () => "finished analysing evidence",
  EVIDENCE_REPROCESS_REQUESTED: () => "asked for the analysis to be re-run",
  EVIDENCE_SUPERSEDED: () => "replaced evidence with a new version",
  EVIDENCE_DELETED: () => "removed evidence",
  EVIDENCE_METADATA_UPDATED: () => "edited an evidence record's details",
  EVIDENCE_CHANGED_AFTER_LOCK: () => "changed evidence after its verdict was locked",
  CONTROL_ASSIGNED: () => "assigned a control to an owner",
  CONTROL_SUBMITTED: () => "submitted a control for auditor review",
  AUDITOR_VERDICT: (d) => `recorded the verdict ${str(d.verdict) || "(none)"}${overrode(d)}`,
  CONTROL_LOCKED: (d) => `locked the control as ${str(d.verdict) || "closed"}${overrode(d)}`,
  CONTROL_UNLOCKED: () => "reopened the control",
  POLICY_ADDED: () => "added a policy as a draft",
  POLICY_EDITED: () => "changed a policy, making a new version",
  POLICY_APPROVED: () => "approved a policy version",
  POLICY_ACCEPTED: () => "accepted a policy",
  VERDICT_REGISTERED: (d) => (str(d.kind) === "REOPENED" ? "added a reopening to the verdict history" : "added a decision to the verdict history"),
  CONTROL_MESSAGE_CREATED: () => "posted on a control's discussion",
  CONTROL_MESSAGE_RESOLVED: () => "resolved a request",
  TASK_CREATED: () => "created a task",
  TASK_UPDATED: () => "updated a task",
  EXCEPTION_REQUESTED: () => "asked for a gap exception",
  EXCEPTION_REVOKED: () => "withdrew a gap exception",
  CONNECTOR_SYNCED: () => "collected evidence from a connector",
  CONNECTOR_RUN: (d) => `ran a connector (${(str(d.status) || "unknown").toLowerCase()})`,
  CONNECTOR_MARKED_NA: () => "marked a connector out of scope",
  ENGAGEMENT_OPENED: () => "opened an audit engagement",
  ENGAGEMENT_CLOSED: () => "closed an audit engagement",
  AUDITOR_STAFFED: () => "staffed an auditor on an engagement",
  AUDITOR_UNSTAFFED: () => "removed an auditor from an engagement",
  ONBOARDING_REQUESTED: () => "asked a firm to audit them",
  ONBOARDING_APPROVED: () => "approved an onboarding request",
  ONBOARDING_REJECTED: () => "rejected an onboarding request",
  BREACH_LOGGED: () => "logged a breach",
  BREACH_BOARD_NOTIFIED: () => "recorded the Board notification",
  BREACH_AFFECTED_NOTIFIED: () => "recorded notification of affected people",
  BREACH_CLOSED: () => "closed a breach",
  RIGHTS_REQUEST_LOGGED: () => "logged a data-subject request",
  RIGHTS_REQUEST_CLOSED: () => "closed a data-subject request",
  CISO_SYNC_FAILED: () => "could not push a result to CISO Assistant",
  SEGREGATION_OF_DUTIES_BLOCKED: () => "was blocked by segregation of duties",
  AUTHORIZATION_DENIED: () => "was refused access",
  FINDING_RAISED: (d) => `raised a ${(str(d.severity) || "").toLowerCase()} finding`.replace("  ", " "),
  FINDING_RESPONDED: () => "responded to a finding",
  FINDING_CLOSED: () => "closed a finding",
  FINDING_REOPENED: () => "reopened a finding",
  CHAIN_GENESIS: () => "started the audit trail",
  AUDIT_CHECKPOINT_ISSUED: () => "took a signed audit checkpoint",
  EXPORT_GENERATED: () => "exported a report",
  REVIEW_STANDARD_PUBLISHED: () => "published a review standard",
  REVIEW_STANDARD_ACTIVATED: () => "activated a review standard",
};

/** Who did it, in words when the backend could resolve them, else the raw label. */
export const whoOf = (e: EventLike) => e.actor_display || e.actor;

/** What happened, in words; the raw action code when this build does not know it. */
export function describeEvent(e: EventLike): string {
  const make = SENTENCES[e.action];
  return make ? make(e.detail ?? {}) : e.action;
}

export const isKnownAction = (action: string) => action in SENTENCES;
