import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, listEvidence, uploadEvidence, type EvidenceSummary } from "../api/client";
import { useSession } from "../lib/session";
import { useApi } from "../lib/useApi";
import { DataTable, type Column } from "../components/DataTable";
import { Badge } from "../components/Badge";
import { Spinner } from "../components/Spinner";

const ARTEFACT_TYPES = ["POLICY", "SCAN_REPORT"];
const TERMINAL = new Set(["READY", "FAILED", "NEEDS_REVIEW"]);

export function EvidenceListPage() {
  const { identity } = useSession();
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [artefactType, setArtefactType] = useState(ARTEFACT_TYPES[0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const evidence = useApi(() => listEvidence({ lifecycle_status: "CURRENT" }), []);

  const processingCount = useMemo(
    () => (evidence.data ?? []).filter((r) => !TERMINAL.has(r.status)).length,
    [evidence.data]
  );

  // The moment anything is still being extracted/evaluated, keep polling so the
  // list reflects real progress — a status that only updates on manual refresh
  // reads as "stuck", not "working".
  useEffect(() => {
    if (processingCount === 0) return;
    const timer = setInterval(() => evidence.reload(), 2500);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [processingCount]);

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const result = await uploadEvidence(file, artefactType);
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
      render: (r) =>
        TERMINAL.has(r.status) ? (
          <Badge value={r.status} />
        ) : (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <Spinner />
            <Badge value={r.status} />
          </span>
        ),
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
        {processingCount > 0 && (
          <span className="live-indicator">
            <span className="live-dot" /> {processingCount} item{processingCount > 1 ? "s" : ""} still being
            analysed — updating live
          </span>
        )}
      </div>

      {identity?.kind === "auditor" ? (
        <div className="alert alert-info">Auditors review evidence; they do not upload it. Sign in as the organisation to upload.</div>
      ) : (
        <div className="card" style={{ maxWidth: 460, marginBottom: 24 }}>
          {error && <div className="alert alert-error">{error}</div>}
          <div className="form-grid">
            <div>
              <label>Artefact type</label>
              <select value={artefactType} onChange={(e) => setArtefactType(e.target.value)}>
                {ARTEFACT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label>File</label>
              <input type="file" accept=".pdf,.docx,.xlsx,.png,.jpg,.jpeg,.txt,.csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </div>
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
            {category === "POLICY" ? "Policies & procedures" : category === "SCAN_REPORT" ? "Scan reports" : category}{" "}
            <span className="muted">({rows.length})</span>
          </div>
          <DataTable columns={columns} rows={rows} onRowClick={(r) => navigate(`/evidence/${r.id}`)} />
        </div>
      ))}
    </div>
  );
}
