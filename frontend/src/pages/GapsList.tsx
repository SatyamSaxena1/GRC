import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, downloadGapsExport, getCisoSyncStatus, listGaps, listTasks, type GapRow } from "../api/client";
import { useApi } from "../lib/useApi";
import { DataTable, type Column } from "../components/DataTable";
import { Badge } from "../components/Badge";
import { CisoSyncBadge } from "../components/CisoSyncBadge";
import { GapFinding } from "../components/GapFinding";
import { PageTour } from "../components/PageTour";
import { ProcessingNotice } from "../components/ProcessingNotice";

const STATUSES: [string, string][] = [["", "All statuses"], ["OPEN", "Open"], ["RESOLVED_BY_EVIDENCE", "Resolved by evidence"]];
const PRIORITY_RANK = { CRITICAL: 3, HIGH: 2, MEDIUM: 1, LOW: 0 };

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
  const [framework, setFramework] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const gaps = useApi(() => listGaps(status || undefined), [status]);
  const cisoSync = useApi(() => getCisoSyncStatus(), []);
  // Owner, due date and priority live on the task each gap opens — join, don't duplicate.
  const tasks = useApi(() => listTasks(), []);
  const taskByGap = useMemo(
    () => new Map((tasks.data ?? []).flatMap((t) => (t.gap_id ? [[t.gap_id, t] as const] : []))),
    [tasks.data],
  );
  const frameworks = [...new Set([...(framework ? [framework] : []), ...(gaps.data ?? []).map((g) => g.framework)])].sort();
  // Work-queue order: open first, then priority, then soonest due, then a stable tiebreak.
  const order = (g: GapRow) => {
    const t = taskByGap.get(g.id);
    return [g.status === "OPEN" ? 0 : 1, -PRIORITY_RANK[t?.priority ?? "MEDIUM"], t?.due_at ?? "9999-12-31", g.framework, g.clause] as const;
  };
  const rows = (gaps.data ?? [])
    .filter((g) => !framework || g.framework === framework)
    .sort((a, b) => {
      const x = order(a), y = order(b);
      for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] < y[i] ? -1 : 1;
      return 0;
    });

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
    { key: "gap", header: "Gap", render: (g) => <GapFinding gap={g} /> },
    {
      key: "priority", header: "Priority",
      render: (g) => { const t = taskByGap.get(g.id); return t ? <Badge value={t.priority} /> : <span className="muted">—</span>; },
    },
    {
      key: "owner", header: "Owner",
      render: (g) => taskByGap.get(g.id)?.owner_email ?? <span className="muted">Unassigned</span>,
    },
    {
      key: "due", header: "Due",
      render: (g) => { const d = taskByGap.get(g.id)?.due_at; return d ? new Date(d).toLocaleDateString() : <span className="muted">—</span>; },
    },
    {
      key: "status", header: "Status",
      // A waived gap stays OPEN (the evaluator owns it); the exception is shown beside it and
      // stops counting by itself at expiry or when the rule or value changes (ADR-021).
      render: (g) => g.waived && g.exception ? (
        <span title={`Exception approved by ${g.exception.decided_by ?? "an auditor"}`}>
          <Badge value="WAIVED" />{" "}
          <span className="muted" style={{ fontSize: 12 }}>until {new Date(g.exception.expires_at).toLocaleDateString()}</span>
        </span>
      ) : <Badge value={g.status} />,
    },
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
          <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUSES.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <select aria-label="Framework" value={framework} onChange={(e) => setFramework(e.target.value)}>
            <option value="">All frameworks</option>
            {frameworks.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
          <button className="btn" disabled={exporting} onClick={exportGaps}>
            {exporting ? "Preparing…" : "Export (XLSX)"}
          </button>
          <PageTour id="gaps" steps={TOUR_STEPS} />
        </div>
      </div>
      <ProcessingNotice onSettled={() => { gaps.reload(); tasks.reload(); }} />
      {exportError && <div className="alert alert-error">{exportError}</div>}
      {gaps.error && <div className="alert alert-error">{gaps.error}</div>}
      <DataTable
        columns={columns}
        rows={rows}
        onRowClick={(g) => navigate(`/evidence/${g.evidence_id}`)}
        emptyLabel={framework ? "No gaps match these filters." : "No gaps at this status."}
      />
    </div>
  );
}
