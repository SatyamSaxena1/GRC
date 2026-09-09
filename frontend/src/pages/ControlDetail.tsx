import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ApiError,
  getCisoSyncStatus,
  getControl,
  getControlEvidence,
  getControlHistory,
  listControlMessages,
  lockLink,
  postControlMessage,
  recordVerdict,
  resolveControlMessage,
  submitControl,
  unlockLink,
  type CisoSyncStatus,
  type ControlMessage,
} from "../api/client";
import { useApi } from "../lib/useApi";
import { useSession } from "../lib/session";
import { Badge } from "../components/Badge";
import { CisoSyncBadge } from "../components/CisoSyncBadge";
import { PageTour } from "../components/PageTour";
import { Term } from "../components/Term";

const AUDITOR_VERDICTS = ["COMPLIANT", "PARTIALLY_COMPLIANT", "NON_COMPLIANT"];
const VERDICT_RANK: Record<string, number> = { PASS: 3, PARTIAL: 2, FAIL: 1 };

function buildTourSteps(isAuditor: boolean) {
  return [
    {
      title: "The state of this requirement, at a glance",
      body: "Verdict, owner, how much evidence backs it, and whether it's locked — the same six facts for every control, so you never have to hunt for them.",
      target: ".meta-strip",
    },
    {
      title: "Where it is in the process",
      body: "Evidence gets uploaded and evaluated, then submitted for review, then an auditor locks the conclusion. This tracks real progress — it isn't decorative.",
      target: ".stepper",
    },
    {
      title: isAuditor ? "Review, discuss, and see the trail" : "Discuss and see the trail",
      body: isAuditor
        ? "Overview lists the linked evidence. Auditor review is where you record the verdict and lock it. Discussion is for requesting missing evidence or an unlock. History is the immutable audit trail."
        : "Overview lists the linked evidence. Discussion is where your auditor can request something specific from you, or where you can ask to reopen a locked control. History is the immutable audit trail.",
      target: ".tab-strip",
    },
  ] as const;
}

function bestVerdict(links: { verdict: string }[]): string {
  if (links.length === 0) return "NO_EVIDENCE";
  return links.reduce((best, link) => {
    const rank = VERDICT_RANK[link.verdict] ?? 0;
    return rank > (VERDICT_RANK[best] ?? -1) ? link.verdict : best;
  }, links[0].verdict);
}

// A small glyph, not an icon library, for one badge-sized shape.
function RecordIcon({ locked }: { locked: boolean }) {
  return (
    <span className={`record-icon${locked ? " locked" : ""}`} aria-hidden="true">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
        {locked ? (
          <path d="M6 11V8a6 6 0 0 1 12 0v3M5 11h14v9H5z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
        ) : (
          <path d="M4 12.5l5 5L20 7" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
        )}
      </svg>
    </span>
  );
}

type TabId = "overview" | "review" | "discussion" | "history";

export function ControlDetailPage() {
  const { id = "" } = useParams();
  const { identity } = useSession();
  const control = useApi(() => getControl(id), [id]);
  const evidenceRows = useApi(() => getControlEvidence(id), [id]);
  const history = useApi(() => getControlHistory(id), [id]);
  const cisoSync = useApi(() => getCisoSyncStatus(), []);
  const messages = useApi(() => listControlMessages(id), [id]);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>("overview");

  const isAuditor = identity?.kind === "auditor";

  const submit = async () => {
    setError(null);
    try {
      await submitControl(id);
      control.reload();
      history.reload(); // the stepper's "submitted" step reads history, not control
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    }
  };

  // One dot per real state change, in the order it actually happens — not a
  // decorative count. Derived, not stored: nothing here needs its own column.
  const steps = useMemo(() => {
    const data = control.data;
    if (!data) return [];
    const submitted = history.data?.some((e) => e.action === "CONTROL_SUBMITTED") ?? false;
    const reviewed = data.links.some((l) => l.auditor_verdict != null);
    const flags = [
      { label: "Evidence collected", done: (evidenceRows.data?.length ?? 0) > 0 },
      { label: "Evaluated", done: data.links.length > 0 },
      { label: "Submitted for review", done: submitted || reviewed || data.locked },
      { label: "Auditor reviewed", done: reviewed || data.locked },
      { label: "Locked", done: data.locked },
    ];
    const current = flags.findIndex((f) => !f.done);
    return flags.map((f, i) => ({
      ...f,
      state: f.done ? "complete" : i === current ? "current" : "upcoming",
    }));
  }, [control.data, evidenceRows.data, history.data]);

  if (control.loading && !control.data) return <p className="muted">Loading…</p>;
  if (control.error) return <div className="alert alert-error">{control.error}</div>;
  if (!control.data) return null;

  const data = control.data;
  const verdict = bestVerdict(data.links);

  const tabs: { id: TabId; label: string; count?: number }[] = [
    { id: "overview", label: "Overview" },
    ...(isAuditor ? [{ id: "review" as TabId, label: "Auditor review", count: data.links.length }] : []),
    { id: "discussion", label: "Discussion", count: messages.data?.length },
    { id: "history", label: "History", count: history.data?.length },
  ];

  return (
    <div>
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <Link to="/controls">Controls</Link>
        <span className="crumb-sep">/</span>
        <span className="crumb-current">{data.framework} {data.clause}</span>
      </nav>

      <div className="record-header">
        <RecordIcon locked={data.locked} />
        <div className="record-title-block">
          <h2>{data.title || `${data.framework} ${data.clause}`}</h2>
          {data.text && <p>{data.text}</p>}
        </div>
        <div className="record-actions">
          {!isAuditor && !data.locked && (
            <button className="btn btn-primary" onClick={submit}>Submit for auditor review</button>
          )}
          <PageTour id="control-detail" steps={buildTourSteps(isAuditor)} />
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {!isAuditor && data.locked && (
        <div className="alert alert-info">This control has been closed by the auditor. Contents are read-only.</div>
      )}
      {data.links.filter((l) => l.commitment_stale).map((l) => (
        <div key={l.id} className="alert alert-info">{l.stale_reason}</div>
      ))}

      <div className="meta-strip">
        <div className="meta-item">
          <span className="meta-label">Framework</span>
          <span className="meta-value">{data.framework}</span>
        </div>
        <div className="meta-item">
          <span className="meta-label">Clause</span>
          <span className="meta-value mono">{data.clause}</span>
        </div>
        <div className="meta-item">
          <span className="meta-label"><Term>Verdict</Term></span>
          <span className="meta-value"><Badge value={verdict} /></span>
        </div>
        <div className="meta-item">
          <span className="meta-label">Owner</span>
          <span className="meta-value">{data.owner_emails.length ? data.owner_emails.join(", ") : "Unassigned"}</span>
        </div>
        <div className="meta-item">
          <span className="meta-label"><Term>Evidence</Term></span>
          <span className="meta-value">{evidenceRows.data?.length ?? "—"} linked</span>
        </div>
        <div className="meta-item">
          <span className="meta-label">State</span>
          <span className="meta-value">{data.locked ? "Locked" : "Open"}</span>
        </div>
      </div>

      <div className="stepper">
        {steps.map((step) => (
          <div key={step.label} className={`step ${step.state}`}>
            <div className="dot">{step.state === "complete" ? "✓" : ""}</div>
            <div className="step-label">{step.label}</div>
            <div className="step-sub">
              {step.state === "complete" ? "Complete" : step.state === "current" ? "In progress" : "Upcoming"}
            </div>
          </div>
        ))}
      </div>

      <div className="tab-strip" role="tablist">
        {tabs.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? "active" : ""} onClick={() => setTab(t.id)}>
            {t.label}
            {t.count != null && <span className="count">{t.count}</span>}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <>
          <div className="section-title">Linked evidence</div>
          {evidenceRows.data && evidenceRows.data.length === 0 && (
            <div className="card empty-state">No evidence linked to this control yet.</div>
          )}
          <div className="card-grid">
            {evidenceRows.data?.map((row) => (
              <a key={row.evidence_id} href={`/evidence/${row.evidence_id}`} className="card">
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <strong>{row.original_filename || "evidence"}</strong>
                  <Badge value={row.verdict} />
                </div>
                <div className="stat-sub">
                  v{row.version} · {row.lifecycle_status}
                  {row.locked && " · locked"}
                </div>
              </a>
            ))}
          </div>
        </>
      )}

      {tab === "review" && isAuditor && (
        <>
          {data.links.map((link) => (
            <AuditorLinkPanel
              key={link.id} linkId={link.id} verdict={link.verdict}
              auditorVerdict={link.auditor_verdict} locked={link.locked}
              nutshell={link.nutshell}
              onChanged={() => { control.reload(); cisoSync.reload(); history.reload(); }}
              syncStatus={cisoSync.data?.find((s) => s.entity_type === "evidence_control_link" && s.entity_id === link.id)}
            />
          ))}
        </>
      )}

      {tab === "discussion" && (
        <DiscussionThread
          controlId={id}
          locked={data.locked}
          isAuditor={isAuditor}
          messages={messages.data ?? []}
          onChanged={messages.reload}
        />
      )}

      {tab === "history" && (
        <ul className="timeline">
          {history.data?.map((e, i) => (
            <li key={i}>
              <div className="ts">{new Date(e.at).toLocaleString()}</div>
              <strong>{e.action}</strong> by {e.actor}
              {e.reason && <span className="muted"> — {e.reason}</span>}
            </li>
          ))}
          {history.data?.length === 0 && <li className="muted">No events yet.</li>}
        </ul>
      )}
    </div>
  );
}

function AuditorLinkPanel({
  linkId,
  verdict,
  auditorVerdict,
  locked,
  nutshell,
  onChanged,
  syncStatus,
}: {
  linkId: string;
  verdict: string;
  auditorVerdict: string | null;
  locked: boolean;
  nutshell?: string;
  onChanged: () => void;
  syncStatus?: CisoSyncStatus;
}) {
  const [choice, setChoice] = useState(auditorVerdict ?? AUDITOR_VERDICTS[0]);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card" style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <span className="muted">Deterministic verdict:</span>
        <Badge value={verdict} />
      </div>
      {nutshell && <p className="muted" style={{ marginTop: 8 }}>{nutshell}</p>}
      {locked && <CisoSyncBadge status={syncStatus} />}
      {error && <div className="alert alert-error">{error}</div>}
      {locked ? (
        <div style={{ marginTop: 10 }}>
          <div className="badge badge-locked">locked — {auditorVerdict}</div>
          <div className="form-row" style={{ marginTop: 10 }}>
            <input placeholder="reason for unlocking (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
            <button className="btn btn-danger" disabled={busy || reason.trim().length < 3} onClick={() => act(() => unlockLink(linkId, reason))}>
              Unlock
            </button>
          </div>
        </div>
      ) : (
        <div className="form-row" style={{ marginTop: 10 }}>
          <select value={choice} onChange={(e) => setChoice(e.target.value)}>
            {AUDITOR_VERDICTS.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
          <input placeholder="remarks (optional)" value={reason} onChange={(e) => setReason(e.target.value)} />
          <button className="btn btn-primary" disabled={busy} onClick={() => act(() => recordVerdict(linkId, choice, reason))}>
            Record verdict
          </button>
          <button className="btn" disabled={busy} onClick={() => act(() => lockLink(linkId, choice))}>
            Lock
          </button>
        </div>
      )}
      <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
        Recording COMPLIANT locks the control in the same step. The uploader of this evidence cannot
        be the one recording its verdict — the backend rejects that as a segregation-of-duties
        violation.
      </p>
    </div>
  );
}

const KIND_LABEL: Record<ControlMessage["kind"], string> = {
  EVIDENCE_REQUEST: "Evidence requested",
  UNLOCK_REQUEST: "Unlock requested",
  COMMENT: "Comment",
};

function DiscussionThread({
  controlId,
  locked,
  isAuditor,
  messages,
  onChanged,
}: {
  controlId: string;
  locked: boolean;
  isAuditor: boolean;
  messages: ControlMessage[];
  onChanged: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async (kind: ControlMessage["kind"]) => {
    if (!draft.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await postControlMessage(controlId, kind, draft.trim());
      setDraft("");
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const resolve = async (messageId: string) => {
    setBusy(true);
    setError(null);
    try {
      await resolveControlMessage(controlId, messageId, "");
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      {error && <div className="alert alert-error">{error}</div>}
      {messages.length === 0 && <p className="muted">No messages on this control yet.</p>}
      <ul className="timeline">
        {messages.map((m) => (
          <li key={m.id}>
            <div className="ts">{new Date(m.created_at).toLocaleString()}</div>
            <strong>{KIND_LABEL[m.kind]}</strong> by {m.created_by}
            {m.kind !== "COMMENT" && <Badge value={m.status} />}
            <p style={{ margin: "4px 0" }}>{m.body}</p>
            {m.status === "RESOLVED" && (
              <p className="muted">Resolved by {m.resolved_by}{m.resolution_note && `: ${m.resolution_note}`}</p>
            )}
            {isAuditor && m.status === "OPEN" && m.kind !== "COMMENT" && (
              <button className="btn" disabled={busy} onClick={() => resolve(m.id)}>Resolve</button>
            )}
          </li>
        ))}
      </ul>

      <div className="form-row" style={{ marginTop: 12 }}>
        <input placeholder="Write a message…" value={draft} onChange={(e) => setDraft(e.target.value)} />
        <button className="btn btn-primary" disabled={busy || !draft.trim()} onClick={() => send("COMMENT")}>
          Comment
        </button>
        {isAuditor && (
          <button className="btn" disabled={busy || !draft.trim()} onClick={() => send("EVIDENCE_REQUEST")}>
            Request evidence
          </button>
        )}
        {!isAuditor && locked && (
          <button className="btn" disabled={busy || !draft.trim()} onClick={() => send("UNLOCK_REQUEST")}>
            Request unlock
          </button>
        )}
      </div>
    </div>
  );
}
