import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ApiError,
  getEvidence,
  getEvidenceAttributes,
  getEvidenceHistory,
  getEvidenceStatus,
  getEvidenceVersions,
  draftRemediation,
  reprocessEvidence,
  streamEvidenceEvents,
  type EvidenceAttribute,
  type EvidenceVersion,
  type Gap,
  type RemediationDraft,
  type StreamedGap,
  uploadEvidenceVersion,
} from "../api/client";
import { useApi } from "../lib/useApi";
import { Badge } from "../components/Badge";
import { PageTour } from "../components/PageTour";
import { Spinner } from "../components/Spinner";

// Persisted gaps carry an id/status/required_action; streamed ones don't yet.
// One display type that is honest about which fields may be absent, rather
// than casting a partial object to the full shape.
type ShownGap = StreamedGap & Partial<Pick<Gap, "id" | "status" | "required_action">>;
type LiveLink = {
  id: string; framework: string; clause: string; verdict: string;
  locked: boolean; gaps: ShownGap[];
};

const TERMINAL = new Set(["READY", "FAILED", "NEEDS_REVIEW"]);

const TOUR_STEPS = [
  {
    title: "Every fact has a source",
    body: "Each extracted attribute shows the model's confidence and, where available, the exact page and quote it came from — you can verify every value against the original document.",
    target: "[data-tour='extracted-attributes']",
  },
  {
    title: "One artefact, every framework",
    body: "This same document is checked against every framework you're subscribed to independently. A gap here names the exact attribute, what was found, and what was required.",
    target: "[data-tour='evaluation-links']",
  },
  {
    title: "Corrections are new versions",
    body: "Nothing here is ever edited in place. Upload a revised file and it becomes a new version — the old one stays in the lineage, and any gap it fixes closes automatically.",
    target: "[data-tour='version-lineage']",
  },
] as const;

// What the user actually cares about at each stage — not the enum name.
const STAGE_COPY: Record<string, string> = {
  UPLOADED: "Queued for processing…",
  SCANNING: "Scanning the file for malware and validating its type…",
  STORED: "Stored. Reading the document…",
  EXTRACTING: "Reading the document and pulling out structured facts…",
  ANALYZING: "Asking the model to extract attributes — this is the slow step on CPU…",
  EVALUATING: "Evaluating the extracted facts against every subscribed framework…",
};

export function EvidenceDetailPage() {
  const { id = "" } = useParams();
  const detail = useApi(() => getEvidence(id), [id]);
  const attributes = useApi(() => getEvidenceAttributes(id), [id]);
  const versions = useApi(() => getEvidenceVersions(id), [id]);
  const history = useApi(() => getEvidenceHistory(id), [id]);
  const status = useApi(() => getEvidenceStatus(id), [id]);

  // Facts and verdicts as the pipeline produces them, ~10s sooner than waiting
  // for the whole run. Preview only — the persisted rows below still win the
  // moment they land (see app/events.py).
  const [liveAttributes, setLiveAttributes] = useState<EvidenceAttribute[]>([]);
  const [liveLinks, setLiveLinks] = useState<LiveLink[]>([]);
  const [liveStatus, setLiveStatus] = useState<string | null>(null);
  const [rerunning, setRerunning] = useState(false);
  const [rerunError, setRerunError] = useState<string | null>(null);

  useEffect(() => {
    setLiveAttributes([]);
    setLiveLinks([]);
    setLiveStatus(null);
    const stop = streamEvidenceEvents(id, (e) => {
      if (e.event === "status") setLiveStatus(e.data.status);
      else if (e.event === "attribute")
        setLiveAttributes((prev) => [...prev.filter((a) => a.name !== e.data.name), e.data]);
      else if (e.event === "link")
        setLiveLinks((prev) => [...prev.filter((l) => l.id !== e.data.id), e.data]);
      else if (e.event === "done") {
        detail.reload();
        attributes.reload();
        history.reload();
        status.reload();
      }
    });
    return stop;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Polling stays as the fallback for anything the stream misses — a dropped
  // connection, a second tab opened after the run finished, a proxy that
  // buffers SSE. The stream makes it faster; it is not load-bearing.
  useEffect(() => {
    if (!detail.data || TERMINAL.has(detail.data.status)) return;
    const timer = setInterval(() => {
      detail.reload();
      status.reload();
    }, 2000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.data?.status, liveStatus]);

  if (detail.loading && !detail.data) return <p className="muted">Loading…</p>;
  if (detail.error) return <div className="alert alert-error">{detail.error}</div>;
  if (!detail.data) return null;

  const evidence = detail.data;
  // Persisted wins once it exists; live fills the gap while the run is going.
  const shownAttributes = (attributes.data ?? []).filter((a) => a.value !== null).length
    ? (attributes.data ?? []).filter((a) => a.value !== null)
    : liveAttributes.filter((a) => a.value !== null);
  const shownLinks: LiveLink[] = evidence.links.length
    ? evidence.links.map((l) => ({
        id: l.id, framework: l.framework, clause: l.clause, verdict: l.verdict,
        locked: l.locked, gaps: l.gaps,
      }))
    : liveLinks;

  // NEEDS_REVIEW with an "extraction …" detail means the analysis model was
  // unavailable or errored when this file was processed — the file is fine, the
  // run isn't. Offer to re-run rather than leaving a misleading all-FAIL result.
  const extractionIncomplete =
    evidence.status === "NEEDS_REVIEW" && (status.data?.detail ?? "").startsWith("extraction ");

  const rerun = async () => {
    setRerunning(true);
    setRerunError(null);
    try {
      await reprocessEvidence(id);
      detail.reload();
      attributes.reload();
      history.reload();
      status.reload();
    } catch (err) {
      setRerunError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    } finally {
      setRerunning(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>{evidence.mime_type ? evidence.mime_type.split("/").pop() : "Evidence"} · v{evidence.version}</h2>
          <p className="mono">{evidence.id}</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Badge value={evidence.status} />
          <Badge value={evidence.lifecycle_status} />
          <PageTour id="evidence-detail" steps={TOUR_STEPS} />
        </div>
      </div>

      {!TERMINAL.has(evidence.status) && (
        <div className="alert alert-info" style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Spinner size={16} />
          <span>
            <strong>{STAGE_COPY[evidence.status] ?? "Processing…"}</strong>
            <span className="muted" style={{ display: "block", fontSize: 12, marginTop: 2 }}>
              This page updates on its own every couple of seconds — no need to refresh.
            </span>
          </span>
        </div>
      )}
      {extractionIncomplete && (
        <div className="alert alert-warning">
          <strong>The analysis model was unavailable when this file was processed.</strong>
          <span className="muted" style={{ display: "block", fontSize: 12, margin: "2px 0 8px" }}>
            Your file is stored and its text was readable. The verdicts below were computed
            with no extracted facts, so they all read FAIL — re-run the analysis to get a real result.
          </span>
          <button className="btn" onClick={rerun} disabled={rerunning}>
            {rerunning ? "Re-running…" : "Re-run analysis"}
          </button>
          {rerunError && <span className="muted" style={{ marginLeft: 10 }}>{rerunError}</span>}
        </div>
      )}
      {evidence.status === "FAILED" && (
        <div className="alert alert-error">
          <span>{status.data?.detail || "Processing failed."}</span>
          <button className="btn" style={{ marginLeft: 10 }} onClick={rerun} disabled={rerunning}>
            {rerunning ? "Re-running…" : "Re-run analysis"}
          </button>
          {rerunError && <span className="muted" style={{ marginLeft: 10 }}>{rerunError}</span>}
        </div>
      )}

      <div className="card-grid">
        <div className="card stat-card">
          <div className="stat-label">Quality score</div>
          <div className="stat-value">{evidence.quality_score != null ? `${evidence.quality_score} / 5` : "—"}</div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">SHA-256</div>
          <div className="mono" style={{ fontSize: 11, wordBreak: "break-all" }}>{evidence.sha256}</div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">Size</div>
          <div className="stat-value" style={{ fontSize: 18 }}>{(evidence.size_bytes / 1024).toFixed(1)} KB</div>
        </div>
      </div>

      {evidence.quality?.dimensions && evidence.quality.dimensions.length > 0 && (
        <>
          <div className="section-title">Quality breakdown</div>
          <div className="card">
            <div className="quality-dims">
              {evidence.quality.dimensions.map((d) => (
                <div key={d.name} className="quality-dim">
                  <span style={{ textTransform: "capitalize" }}>{d.name.replace(/_/g, " ")}</span>
                  <div className="bar">
                    <div style={{ width: `${Math.round(d.score * 100)}%` }} />
                  </div>
                  <span className="muted">{d.reason}</span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      <div className="section-title">Extracted attributes</div>
      <div className="card" data-tour="extracted-attributes">
        {!TERMINAL.has(evidence.status) && (
          <p className="muted" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Spinner size={12} />
            {shownAttributes.length > 0
              ? `Extracting — ${shownAttributes.length} fact${shownAttributes.length > 1 ? "s" : ""} so far, live.`
              : "Waiting on extraction — values will appear here as they're found."}
          </p>
        )}
        {TERMINAL.has(evidence.status) && shownAttributes.length === 0 && (
          <p className="muted">Nothing extracted — no model was available, or the document did not state these values.</p>
        )}
        {shownAttributes.map((a) => (
          <div key={a.name} style={{ marginBottom: 10, fontSize: 13 }}>
            <strong>{a.name}</strong>: {JSON.stringify(a.value)}
            {a.confidence != null && <span className="muted"> (confidence {a.confidence.toFixed(2)})</span>}
            {a.sources.length > 0 && (
              <div className="muted" style={{ fontSize: 12 }}>
                {a.sources.map((s, i) => (
                  <span key={i}>{s.page ? `page ${s.page}` : ""} {s.quote ? `"${s.quote}"` : ""} </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="section-title">
        Evaluation, per framework
        {shownLinks.length > 0 && <span className="muted"> · {shownLinks.length} requirement{shownLinks.length > 1 ? "s" : ""} assessed from this one artefact</span>}
      </div>
      {shownLinks.length === 0 && (
        <div className="card empty-state">
          {TERMINAL.has(evidence.status) ? (
            "No links — nothing in scope for this artefact type."
          ) : (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
              <Spinner size={12} /> Evaluation runs after extraction finishes.
            </span>
          )}
        </div>
      )}
      <div className="card-grid" data-tour="evaluation-links">
        {shownLinks.map((link) => (
          <div key={link.id} className="card">
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <strong>{link.framework} {link.clause}</strong>
              <Badge value={link.verdict} />
            </div>
            {link.locked && <div className="badge badge-locked" style={{ marginTop: 6 }}>locked</div>}
            {link.gaps.filter((g) => g.status !== "RESOLVED_BY_EVIDENCE").map((gap, i) => (
              <GapRow key={gap.id ?? `${link.id}-${i}`} gap={gap} />
            ))}
          </div>
        ))}
      </div>

      <VersionsAndUpload evidenceId={id} data={versions.data} reload={versions.reload} />

      <div className="section-title">History</div>
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
    </div>
  );
}

/** One gap, with an on-demand LLM draft of wording that would close it.
 * The draft is a suggestion for a human to edit and adopt — requesting it
 * writes nothing and cannot move the verdict (see ADR-004). */
function GapRow({ gap }: { gap: ShownGap }) {
  const [draft, setDraft] = useState<RemediationDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const requestDraft = async () => {
    if (!gap.id) return; // a streamed gap has no persisted id to draft against yet
    setBusy(true);
    setError(null);
    try {
      setDraft(await draftRemediation(gap.id));
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ marginTop: 10, fontSize: 13, borderTop: "1px solid var(--border)", paddingTop: 8 }}>
      <div>
        <strong>{gap.attribute}</strong> — actual <code>{gap.actual_value ?? "missing"}</code>, required{" "}
        <code>{gap.required_value ?? "n/a"}</code>
      </div>
      {gap.required_action && <div className="muted">{gap.required_action}</div>}
      {error && <div className="alert alert-error" style={{ marginTop: 8 }}>{error}</div>}
      {!draft && gap.id && (
        <button className="btn" style={{ marginTop: 8 }} disabled={busy} onClick={requestDraft}>
          {busy ? "Drafting…" : "Draft wording to close this"}
        </button>
      )}
      {draft && (
        <div className="card" style={{ marginTop: 8, background: "var(--background)" }}>
          <span className="eyebrow">Suggested wording · review before adopting</span>
          <p style={{ margin: "6px 0 0" }}>{draft.draft || "No draft available — the model was unreachable."}</p>
          {draft.evidence_needed.length > 0 && (
            <>
              <div className="muted" style={{ marginTop: 10, fontWeight: 700 }}>An auditor would expect to see</div>
              <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                {draft.evidence_needed.map((item, i) => <li key={i} className="muted">{item}</li>)}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function VersionsAndUpload({
  evidenceId,
  data,
  reload,
}: {
  evidenceId: string;
  data: EvidenceVersion[] | null;
  reload: () => void;
}) {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const result = await uploadEvidenceVersion(evidenceId, file);
      // A client-side route change, not a full page reload — a real browser
      // navigation to /evidence/:id hits the Vite proxy's raw backend route
      // (see vite.config.ts bypass), which has no Authorization header to give it.
      navigate(`/evidence/${result.evidence_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="section-title">Version lineage</div>
      <div className="card" data-tour="version-lineage">
        {data?.map((v) => (
          <div key={v.id} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0" }}>
            <span>
              v{v.version} — {v.original_filename}
            </span>
            <Badge value={v.lifecycle_status} />
          </div>
        ))}
        <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
          {error && <div className="alert alert-error">{error}</div>}
          <div className="form-row">
            <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <button className="btn btn-primary" disabled={!file || busy} onClick={submit}>
              {busy ? "Uploading…" : "Upload revised version"}
            </button>
          </div>
          <p className="muted" style={{ fontSize: 12 }}>
            A locked control keeps its verdict on the old version; this only re-propagates to controls
            still open for review.
          </p>
        </div>
      </div>
    </>
  );
}
