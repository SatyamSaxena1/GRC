import { AskAIButton } from "../components/Assistant";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getControl, listControls, type ControlDetail } from "../api/client";
import { useApi } from "../lib/useApi";
import { DataTable, type Column } from "../components/DataTable";
import { Badge } from "../components/Badge";
import { PageTour } from "../components/PageTour";
import { ProcessingNotice } from "../components/ProcessingNotice";
import { useSession } from "../lib/session";

const VERDICT_RANK: Record<string, number> = { PASS: 3, PARTIAL: 2, FAIL: 1 };

const TOUR_STEPS = [
  {
    title: "One row per requirement",
    body: "Each row is one clause of one framework, with its current verdict, how many pieces of evidence back it, and whether an auditor has locked the conclusion.",
    target: ".data-table, .empty-state",
  },
  {
    title: "Verdict is deterministic",
    body: "PASS/PARTIAL/FAIL is computed by rules, not guessed by AI — the same evidence always produces the same verdict. \"stale\" means the organisation's own policy commitment changed since this was last evaluated.",
    target: ".data-table th:nth-child(3)",
  },
  {
    title: "Open a control for the full story",
    body: "Click through to see every piece of linked evidence, the exact gaps if it isn't passing, and — for an auditor — the review and lock controls.",
    target: ".data-table",
  },
] as const;

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

  const [query, setQuery] = useState("");
  const [framework, setFramework] = useState("");
  const [verdict, setVerdict] = useState("");
  const [sort, setSort] = useState("framework");
  const all = controls.data ?? [];
  const frameworks = useMemo(() => [...new Set(all.map((c) => c.framework))].sort(), [all]);
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matches = all.filter((c) =>
      (!framework || c.framework === framework) && (!verdict || bestVerdict(c) === verdict)
      && (!q || `${c.framework} ${c.clause} ${c.title} ${c.owner_emails.join(" ")}`.toLowerCase().includes(q)));
    const rank = (c: ControlDetail) => ["FAIL", "NO_EVIDENCE", "PARTIAL", "PASS"].indexOf(bestVerdict(c));
    return [...matches].sort((a, b) =>
      sort === "verdict" ? rank(a) - rank(b) || a.framework.localeCompare(b.framework)
      : sort === "owner" ? (a.owner_emails[0] ?? "~").localeCompare(b.owner_emails[0] ?? "~")
      : sort === "evidence" ? b.links.length - a.links.length
      : a.framework.localeCompare(b.framework) || a.clause.localeCompare(b.clause, undefined, { numeric: true }));
  }, [all, query, framework, verdict, sort]);

  const columns: Column<ControlDetail>[] = [
    { key: "framework", header: "Framework", render: (c) => c.framework },
    { key: "clause", header: "Clause", render: (c) => c.clause },
    { key: "verdict", header: "Verdict", render: (c) => <Badge value={bestVerdict(c)} /> },
    { key: "owner", header: "Owner", render: (c) => (c.owner_emails.length ? c.owner_emails.join(", ") : <span className="muted">Unassigned</span>) },
    { key: "evidence", header: "Evidence links", render: (c) => c.links.length },
    {
      key: "locked", header: "Status",
      render: (c) => (
        <>
          {c.locked ? <span className="badge badge-locked">locked</span> : <span className="muted">open</span>}
          {c.links.some((l) => l.commitment_stale) && (
            <span className="muted" title="Policy commitment changed since last evaluation"> · stale</span>
          )}
        </>
      ),
    },
  ];

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>{identity?.kind === "auditor" ? "Auditor review" : identity?.kind === "user" ? "My controls" : "Controls"}</h2> <AskAIButton question={"Which controls still need evidence, and which are only partly met?"} />
          <p>
            {identity?.kind === "auditor"
              ? "Review evidence, record the human verdict, and lock the conclusion."
              : identity?.kind === "user"
                ? "Only controls assigned to you are listed — enforced by the backend."
                : "Only controls visible to the current identity are listed — server-enforced, not a UI filter."}
          </p>
        </div>
        <PageTour id="controls" steps={TOUR_STEPS} />
      </div>
      <ProcessingNotice onSettled={controls.reload} />
      {controls.error && <div className="alert alert-error">{controls.error}</div>}
      <div className="queue-filters" aria-label="Control filters">
        <input aria-label="Search controls" placeholder="Search framework, clause, title or owner…" value={query}
               onChange={(e) => setQuery(e.target.value)} />
        <select aria-label="Filter by framework" value={framework} onChange={(e) => setFramework(e.target.value)}>
          <option value="">All frameworks</option>
          {frameworks.map((f) => <option key={f}>{f}</option>)}
        </select>
        <select aria-label="Filter by verdict" value={verdict} onChange={(e) => setVerdict(e.target.value)}>
          <option value="">All verdicts</option>
          {["FAIL", "NO_EVIDENCE", "PARTIAL", "PASS"].map((v) => <option key={v} value={v}>{v.replace("_", " ")}</option>)}
        </select>
        <select aria-label="Sort controls" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="framework">Sort: framework and clause</option>
          <option value="verdict">Sort: needs attention first</option>
          <option value="owner">Sort: owner</option>
          <option value="evidence">Sort: most evidence</option>
        </select>
      </div>
      <p className="muted" role="status" style={{ fontSize: 13 }}>Showing {rows.length} of {all.length} controls.</p>
      <DataTable
        columns={columns}
        rows={rows}
        onRowClick={(c) => navigate(`/controls/${c.id}`)}
        emptyLabel={all.length ? "No controls match these filters." : "No controls visible to this identity."}
      />
    </div>
  );
}
