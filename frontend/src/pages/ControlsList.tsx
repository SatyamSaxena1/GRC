import { useNavigate } from "react-router-dom";
import { getControl, listControls, type ControlDetail } from "../api/client";
import { useApi } from "../lib/useApi";
import { DataTable, type Column } from "../components/DataTable";
import { Badge } from "../components/Badge";
import { useSession } from "../lib/session";

const VERDICT_RANK: Record<string, number> = { PASS: 3, PARTIAL: 2, FAIL: 1 };

function bestVerdict(control: ControlDetail): string {
  if (control.links.length === 0) return "NO_EVIDENCE";
  return control.links.reduce((best, link) => {
    const rank = VERDICT_RANK[link.verdict] ?? 0;
    return rank > (VERDICT_RANK[best] ?? -1) ? link.verdict : best;
  }, control.links[0].verdict);
}

export function ControlsListPage() {
  const navigate = useNavigate();
  const { identity } = useSession();
  const controls = useApi(async () => {
    const summaries = await listControls();
    return Promise.all(summaries.map((c) => getControl(c.id)));
  }, []);

  const columns: Column<ControlDetail>[] = [
    { key: "framework", header: "Framework", render: (c) => c.framework },
    { key: "clause", header: "Clause", render: (c) => c.clause },
    { key: "verdict", header: "Verdict", render: (c) => <Badge value={bestVerdict(c)} /> },
    { key: "evidence", header: "Evidence links", render: (c) => c.links.length },
    { key: "locked", header: "Status", render: (c) => (c.locked ? <span className="badge badge-locked">locked</span> : <span className="muted">open</span>) },
  ];

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>{identity?.kind === "auditor" ? "Auditor review" : identity?.kind === "user" ? "My controls" : "Controls"}</h2>
          <p>
            {identity?.kind === "auditor"
              ? "Review evidence, record the human verdict, and lock the conclusion."
              : identity?.kind === "user"
                ? "Only controls assigned to you are listed — enforced by the backend."
                : "Only controls visible to the current identity are listed — server-enforced, not a UI filter."}
          </p>
        </div>
      </div>
      {controls.error && <div className="alert alert-error">{controls.error}</div>}
      <DataTable
        columns={columns}
        rows={controls.data ?? []}
        onRowClick={(c) => navigate(`/controls/${c.id}`)}
        emptyLabel="No controls visible to this identity."
      />
    </div>
  );
}
