import { getCisoSyncStatus, retryCisoSync, type CisoSyncStatus } from "../api/client";
import { useApi } from "../lib/useApi";
import { useSession } from "../lib/session";
import { DataTable, type Column } from "../components/DataTable";
import { CisoSyncBadge } from "../components/CisoSyncBadge";
import { PageTour } from "../components/PageTour";

const TOUR_STEPS = [
  {
    title: "One-way, and it never blocks you",
    body: "Every locked verdict and every gap a corrected upload resolves gets pushed into CISO Assistant. A push failing here never undoes the lock or the resolution — this list is how you notice and retry it, not a gate on anything else.",
    target: ".page-header",
  },
  {
    title: "Retry is manual",
    body: "There's no background queue re-attempting a failed push on its own (see ADR-009) — Retry here is the only way one gets tried again.",
    target: ".data-table, .empty-state",
  },
] as const;

const ENTITY_LABEL: Record<CisoSyncStatus["entity_type"], string> = {
  evidence_control_link: "Control verdict",
  gap: "Gap resolution",
};

export function CisoSyncPage() {
  const { identity } = useSession();
  const canWrite = identity?.kind === "org";
  const rows = useApi(() => getCisoSyncStatus(), []);

  const retry = async (row: CisoSyncStatus) => {
    await retryCisoSync(row.entity_type, row.entity_id);
    rows.reload();
  };

  const columns: Column<CisoSyncStatus>[] = [
    { key: "entity_type", header: "What", render: (r) => ENTITY_LABEL[r.entity_type] },
    { key: "entity_id", header: "Which one", render: (r) => <span className="mono">{r.entity_id.slice(0, 8)}…</span> },
    { key: "status", header: "Status", render: (r) => <CisoSyncBadge status={r} /> },
    {
      key: "last_synced_at", header: "Last attempt",
      render: (r) => (r.last_synced_at ? new Date(r.last_synced_at).toLocaleString() : "Never"),
    },
    {
      key: "retry", header: "",
      render: (r) =>
        canWrite && r.status !== "OK" && r.status !== "PENDING" ? (
          <button className="btn" onClick={() => retry(r)}>Retry</button>
        ) : null,
    },
  ];

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>CISO Assistant sync</h2>
          <p>
            Every locked verdict and resolved gap this org has pushed to CISO Assistant, and whether it
            actually landed.
          </p>
        </div>
        <PageTour id="ciso-sync" steps={TOUR_STEPS} />
      </div>
      {rows.error && <div className="alert alert-error">{rows.error}</div>}
      <DataTable
        columns={columns}
        rows={rows.data ?? []}
        emptyLabel="Nothing has been locked or resolved yet — there's nothing to push."
      />
    </div>
  );
}
