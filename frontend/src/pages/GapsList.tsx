import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, downloadGapsExport, getCisoSyncStatus, listGaps, type GapRow } from "../api/client";
import { useApi } from "../lib/useApi";
import { DataTable, type Column } from "../components/DataTable";
import { Badge } from "../components/Badge";
import { CisoSyncBadge } from "../components/CisoSyncBadge";
import { PageTour } from "../components/PageTour";

const STATUSES = ["", "OPEN", "RESOLVED_BY_EVIDENCE"];

const TOUR_STEPS = [
  {
    title: "A gap is specific, not generic",
    body: "Every row names the exact attribute, what was actually found (or missing), and what the requirement needed instead — never just \"insufficient evidence\".",
    target: ".data-table, .empty-state",
  },
  {
    title: "Filter by status",
    body: "OPEN is what still needs fixing. RESOLVED_BY_EVIDENCE stays visible as a record — a gap is closed by the evaluator confirming new evidence fixes it, never by hand.",
    target: "select",
  },
  {
    title: "Click through to fix it",
    body: "A row opens the evidence behind it. Upload a corrected version there and this gap re-evaluates automatically — no separate 'resolve' action here.",
    target: ".data-table",
  },
] as const;

export function GapsListPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState("OPEN");
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const gaps = useApi(() => listGaps(status || undefined), [status]);
  const cisoSync = useApi(() => getCisoSyncStatus(), []);

  // Exports exactly the filter currently on screen — "OPEN" here downloads
  // the same rows the table shows, not the whole history.
  const exportGaps = async () => {
    setExporting(true);
    setExportError(null);
    try {
      await downloadGapsExport({ status: status || undefined });
    } catch (err) {
      setExportError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    } finally {
      setExporting(false);
    }
  };

  const columns: Column<GapRow>[] = [
    { key: "framework", header: "Control", render: (g) => `${g.framework} ${g.clause}` },
    { key: "attribute", header: "Attribute", render: (g) => g.attribute },
    { key: "actual", header: "Actual", render: (g) => g.actual_value ?? "missing" },
    { key: "required", header: "Required", render: (g) => g.required_value ?? "—" },
    { key: "status", header: "Status", render: (g) => <Badge value={g.status} /> },
    {
      key: "ciso_sync", header: "CISO Assistant",
      render: (g) => (
        <CisoSyncBadge status={cisoSync.data?.find((s) => s.entity_type === "gap" && s.entity_id === g.id)} />
      ),
    },
  ];

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Gaps</h2>
          <p>Every unmet requirement, with the exact value observed and the exact value needed.</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s || "All statuses"}
              </option>
            ))}
          </select>
          <button className="btn" disabled={exporting} onClick={exportGaps}>
            {exporting ? "Preparing…" : "Export (XLSX)"}
          </button>
          <PageTour id="gaps" steps={TOUR_STEPS} />
        </div>
      </div>
      {exportError && <div className="alert alert-error">{exportError}</div>}
      {gaps.error && <div className="alert alert-error">{gaps.error}</div>}
      <DataTable
        columns={columns}
        rows={gaps.data ?? []}
        onRowClick={(g) => navigate(`/evidence/${g.evidence_id}`)}
        emptyLabel="No gaps at this status."
      />
    </div>
  );
}
