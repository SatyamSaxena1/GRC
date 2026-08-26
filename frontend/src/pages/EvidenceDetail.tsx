import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ApiError,
  getEvidence,
  getEvidenceAttributes,
  getEvidenceHistory,
  getEvidenceStatus,
  getEvidenceVersions,
  type EvidenceVersion,
  uploadEvidenceVersion,
} from "../api/client";
import { useApi } from "../lib/useApi";
import { Badge } from "../components/Badge";
import { Spinner } from "../components/Spinner";

const TERMINAL = new Set(["READY", "FAILED", "NEEDS_REVIEW"]);

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

  // Poll while the pipeline is still running; stop once it reaches a terminal state.
  useEffect(() => {
    if (!detail.data || TERMINAL.has(detail.data.status)) return;
    const timer = setInterval(() => {
      detail.reload();
      status.reload();
    }, 2000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.data?.status]);

  if (detail.loading && !detail.data) return <p className="muted">Loading…</p>;
  if (detail.error) return <div className="alert alert-error">{detail.error}</div>;
  if (!detail.data) return null;

  const evidence = detail.data;

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
      {evidence.status === "FAILED" && <div className="alert alert-error">{status.data?.detail || "Processing failed."}</div>}

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

      {evidence.quality && (
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
      <div className="card">
        {!TERMINAL.has(evidence.status) && (
          <p className="muted" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Spinner size={12} /> Waiting on extraction — values will appear here as they're found.
          </p>
        )}
        {TERMINAL.has(evidence.status) && attributes.data && attributes.data.filter((a) => a.value !== null).length === 0 && (
          <p className="muted">Nothing extracted — no model was available, or the document did not state these values.</p>
        )}
        {attributes.data
          ?.filter((a) => a.value !== null)
          .map((a) => (
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

      <div className="section-title">Evaluation, per framework</div>
      {evidence.links.length === 0 && (
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
      <div className="card-grid">
        {evidence.links.map((link) => (
          <div key={link.id} className="card">
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <strong>{link.framework} {link.clause}</strong>
              <Badge value={link.verdict} />
            </div>
            {link.locked && <div className="badge badge-locked" style={{ marginTop: 6 }}>locked</div>}
            {link.gaps.filter((g) => g.status === "OPEN").map((gap) => (
              <div key={gap.id} style={{ marginTop: 10, fontSize: 13, borderTop: "1px solid var(--border)", paddingTop: 8 }}>
                <div>
                  <strong>{gap.attribute}</strong> — actual <code>{gap.actual_value ?? "missing"}</code>, required{" "}
                  <code>{gap.required_value ?? "n/a"}</code>
                </div>
                <div className="muted">{gap.required_action}</div>
              </div>
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
      <div className="card">
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
