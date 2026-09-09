import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ApiError, listEvidence, reprocessEvidence, uploadEvidence, type EvidenceSummary,
} from "../api/client";
import { useSession } from "../lib/session";
import { useApi } from "../lib/useApi";
import { DataTable, type Column } from "../components/DataTable";
import { Badge } from "../components/Badge";
import { PageTour } from "../components/PageTour";
import { Spinner } from "../components/Spinner";

const TOUR_STEPS = [
  {
    title: "Upload once, evaluate everywhere",
    body: "Pick the artefact type so the extractor knows what to look for, then upload. The same document is automatically checked against every framework you're subscribed to — no per-framework re-upload.",
    target: "[data-tour='upload-form']",
  },
  {
    title: "Processing is visible, not a black box",
    body: "A spinner means it's still being read and evaluated. STUCK means it's been running unusually long — Retry re-runs the pipeline on the same stored file, nothing is re-uploaded.",
    target: ".data-table th:nth-child(4)",
  },
  {
    title: "Grouped by category",
    body: "Policies, scan reports and review records are grouped separately — the same categories the evaluator itself checks each artefact type against.",
    target: ".section-title",
  },
] as const;

// Must match app/routers/evidence.py::ARTEFACT_TYPES and the artefact_type
// values the content packs match on — see app/content/*.yaml. AI_POLICY and
// AI_INVENTORY are what NIST-AI-RMF evidences against; an AI governance policy
// is deliberately not a POLICY, so uploading the security policy cannot
// accidentally satisfy an AI clause. CERTIFICATE and SCREENSHOT have no
// evidence_requirements mapped yet — they upload and classify but won't
// produce any framework links until a content pack maps them to one.
const ARTEFACT_TYPES = [
  "POLICY", "SCAN_REPORT", "REVIEW_RECORD", "REPORT", "CERTIFICATE", "SCREENSHOT",
  "AI_POLICY", "AI_INVENTORY",
];

const ARTEFACT_LABELS: Record<string, string> = {
  POLICY: "Policies & procedures",
  SCAN_REPORT: "Scan reports",
  REVIEW_RECORD: "Review records",
  REPORT: "Reports",
  CERTIFICATE: "Certificates",
  SCREENSHOT: "Screenshots",
  AI_POLICY: "AI governance policies",
  AI_INVENTORY: "AI system inventories",
};

// What the type controls: which framework requirements this artefact can
// evaluate against (app/evaluate.py matches on artefact_type exactly).
const ARTEFACT_HELP: Record<string, string> = {
  POLICY: "A written policy or procedure document — access control, encryption, retention, and similar.",
  SCAN_REPORT: "Output from a vulnerability or penetration test scan (e.g. an ASV report).",
  REVIEW_RECORD: "A record that a periodic review happened — access reviews, log reviews.",
  REPORT: "A narrative finding or audit report, distinct from an automated scan.",
  CERTIFICATE: "A third-party attestation or certification (ISO, SOC 2, PCI AOC). Not yet evaluated against any framework requirement — upload to keep it on file.",
  SCREENSHOT: "A screen capture as supporting proof. Not yet evaluated against any framework requirement — upload to keep it on file.",
  AI_POLICY: "An AI governance policy — separate from a general security policy so it only satisfies AI-specific clauses.",
  AI_INVENTORY: "A system/model inventory for NIST AI RMF evidence.",
};
const TERMINAL = new Set(["READY", "FAILED", "NEEDS_REVIEW"]);
// Mirrors app/monitor.py's STUCK_AFTER_MINUTES — a display threshold only; the
// backend's /reprocess 409 is the real gate on whether retry is meaningful.
const STUCK_AFTER_MINUTES = 15;

export function EvidenceListPage() {
  const { identity } = useSession();
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [artefactType, setArtefactType] = useState(ARTEFACT_TYPES[0]);
  const [description, setDescription] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [isEncrypted, setIsEncrypted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);
  // When a row was last (re)kicked off, client-side. A retry restarts the
  // stuck clock — without this, retrying evidence uploaded over 15 minutes ago
  // would read as "stuck" from its *original* upload time the instant the
  // retry click lands, before the background task even finishes, and — because
  // a stuck row is excluded from the poll below — the page would stop
  // refreshing and never show it flip to READY without a manual reload.
  const [startedAt, setStartedAt] = useState<Record<string, number>>({});

  const evidence = useApi(() => listEvidence({ lifecycle_status: "CURRENT" }), []);

  const isStuck = (row: EvidenceSummary): boolean => {
    if (TERMINAL.has(row.status)) return false;
    const reference = Math.max(new Date(row.created_at).getTime(), startedAt[row.id] ?? 0);
    return (Date.now() - reference) / 60000 > STUCK_AFTER_MINUTES;
  };

  // Only count rows still plausibly working — one stuck past the threshold
  // isn't going to finish on its own, so it stops driving the poll and gets a
  // Retry action instead of spinning forever.
  const processingCount = useMemo(
    () => (evidence.data ?? []).filter((r) => !TERMINAL.has(r.status) && !isStuck(r)).length,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [evidence.data, startedAt]
  );

  useEffect(() => {
    if (processingCount === 0) return;
    const timer = setInterval(() => evidence.reload(), 2500);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [processingCount]);

  const retry = async (evidenceId: string) => {
    setRetrying(evidenceId);
    setError(null);
    try {
      await reprocessEvidence(evidenceId);
      setStartedAt((prev) => ({ ...prev, [evidenceId]: Date.now() }));
      evidence.reload();
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    } finally {
      setRetrying(null);
    }
  };

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const result = await uploadEvidence(file, artefactType, {
        description: description.trim() || undefined,
        validUntil: validUntil || undefined,
        isEncrypted,
      });
      navigate(`/evidence/${result.evidence_id}`);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 409 ? "This exact file has already been uploaded." : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // Grouped the way the reference product's project evidence queues are —
  // one category per artefact type — rather than a single flat list.
  const byCategory = useMemo(() => {
    const groups = new Map<string, EvidenceSummary[]>();
    for (const row of evidence.data ?? []) {
      const list = groups.get(row.artefact_type) ?? [];
      list.push(row);
      groups.set(row.artefact_type, list);
    }
    return groups;
  }, [evidence.data]);

  const columns: Column<EvidenceSummary>[] = [
    { key: "filename", header: "File", render: (r) => r.original_filename || "(unnamed)" },
    { key: "version", header: "Version", render: (r) => `v${r.version}` },
    { key: "quality", header: "Quality", render: (r) => (r.quality_score != null ? `${r.quality_score} / 5` : "—") },
    {
      key: "status",
      header: "Status",
      render: (r) => {
        const stuck = isStuck(r);
        const badge = TERMINAL.has(r.status) && !stuck ? (
          <Badge value={r.status} />
        ) : (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            {!stuck && <Spinner />}
            <Badge value={stuck ? "STUCK" : r.status} />
          </span>
        );
        const canRetry = identity?.kind !== "auditor" && (r.status === "FAILED" || stuck);
        return (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            {badge}
            {canRetry && (
              <button
                className="btn"
                disabled={retrying === r.id}
                onClick={(e) => { e.stopPropagation(); retry(r.id); }}
              >
                {retrying === r.id ? "Retrying…" : "Retry"}
              </button>
            )}
          </span>
        );
      },
    },
    { key: "uploaded_by", header: "Uploaded by", render: (r) => r.uploaded_by },
    { key: "created_at", header: "Uploaded", render: (r) => new Date(r.created_at).toLocaleString() },
  ];

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Evidence</h2>
          <p>Upload once — the same artefact is evaluated against every subscribed framework independently.</p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {processingCount > 0 && (
            <span className="live-indicator">
              <span className="live-dot" /> {processingCount} item{processingCount > 1 ? "s" : ""} still being
              analysed — updating live
            </span>
          )}
          <PageTour id="evidence" steps={TOUR_STEPS} />
        </div>
      </div>

      {identity?.kind === "auditor" ? (
        <div className="alert alert-info">Auditors review evidence; they do not upload it. Sign in as the organisation to upload.</div>
      ) : (
        <div className="card" data-tour="upload-form" style={{ maxWidth: 460, marginBottom: 24 }}>
          {error && <div className="alert alert-error">{error}</div>}
          <div className="form-grid">
            <div>
              <label>Artefact type</label>
              <select value={artefactType} onChange={(e) => setArtefactType(e.target.value)}>
                {ARTEFACT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {ARTEFACT_LABELS[t] ?? t}
                  </option>
                ))}
              </select>
              <p className="muted" style={{ fontSize: 12, margin: "4px 0 0" }}>{ARTEFACT_HELP[artefactType]}</p>
            </div>
            <div>
              <label>File</label>
              <input type="file" accept=".pdf,.docx,.xlsx,.png,.jpg,.jpeg,.txt,.csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </div>
            <div>
              <label>Description (optional)</label>
              <input
                type="text" placeholder="e.g. Q3 access review, signed"
                value={description} onChange={(e) => setDescription(e.target.value)}
              />
            </div>
            <div>
              <label>Valid until (optional)</label>
              <input type="date" value={validUntil} onChange={(e) => setValidUntil(e.target.value)} />
            </div>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 400 }}>
              <input type="checkbox" checked={isEncrypted} onChange={(e) => setIsEncrypted(e.target.checked)} />
              This file is password-protected
            </label>
            <button className="btn btn-primary" disabled={!file || busy} onClick={submit}>
              {busy ? "Uploading…" : "Upload"}
            </button>
          </div>
        </div>
      )}

      {evidence.error && <div className="alert alert-error">{evidence.error}</div>}

      {evidence.loading && !evidence.data && (
        <div className="card">
          <div className="skeleton-row" />
          <div className="skeleton-row" style={{ width: "80%" }} />
          <div className="skeleton-row" style={{ width: "60%" }} />
        </div>
      )}

      {evidence.data && byCategory.size === 0 && (
        <div className="card empty-state">No evidence uploaded yet.</div>
      )}

      {[...byCategory.entries()].map(([category, rows]) => (
        <div key={category}>
          <div className="section-title">
            {ARTEFACT_LABELS[category] ?? category}{" "}
            <span className="muted">({rows.length})</span>
          </div>
          <DataTable columns={columns} rows={rows} onRowClick={(r) => navigate(`/evidence/${r.id}`)} />
        </div>
      ))}
    </div>
  );
}
