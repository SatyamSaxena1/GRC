import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getReadinessAll, type FrameworkReadiness } from "../api/client";
import { useApi } from "../lib/useApi";
import { Badge } from "../components/Badge";
import { DataTable, type Column } from "../components/DataTable";

type Clause = FrameworkReadiness["clauses"][number];

const NEEDS_WORK = new Set(["FAIL", "PARTIAL", "NO_EVIDENCE"]);
const ORDER = ["FAIL", "NO_EVIDENCE", "PARTIAL", "PASS", "NOT_APPLICABLE"];

/** One page per framework: how ready you are, which clauses are covered and which still need something. The figures come
 *  from the same readiness call as the Overview, so the two pages cannot disagree. A framework you have not subscribed to
 *  shows what the evidence already on file would satisfy (day-1 readiness). */
export function FrameworksPage() {
  const state = useApi(() => getReadinessAll(), []);
  const [params, setParams] = useSearchParams();
  const [show, setShow] = useState<"attention" | "all">("attention");
  const [query, setQuery] = useState("");

  const frameworks = state.data ?? [];
  const chosen = params.get("f") ?? "";
  const current = frameworks.find((f) => f.framework === chosen) ?? frameworks.find((f) => f.already_subscribed) ?? frameworks[0];

  const rows = useMemo(() => {
    if (!current) return [];
    const q = query.trim().toLowerCase();
    return current.clauses
      .filter((c) => (show === "all" || NEEDS_WORK.has(c.verdict)) && (!q || `${c.clause} ${c.title}`.toLowerCase().includes(q)))
      .sort((a, b) => ORDER.indexOf(a.verdict) - ORDER.indexOf(b.verdict) || a.clause.localeCompare(b.clause, undefined, { numeric: true }));
  }, [current, show, query]);

  if (state.error) return <div className="alert alert-error">{state.error}</div>;
  if (!state.data) return <p className="muted">Loading…</p>;

  const missing = current ? current.total_requirements - current.satisfied - current.partial : 0;
  const columns: Column<Clause>[] = [
    { key: "clause", header: "Clause", render: (c) => <span className="mono">{c.clause}</span> },
    { key: "title", header: "What it asks", render: (c) => c.title },
    { key: "verdict", header: "Verdict", render: (c) => <Badge value={c.verdict} /> },
  ];

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Frameworks</h2>
          <p>
            For each framework: how much of it your evidence already meets, and exactly which clauses still need
            something. A verdict is decided by fixed rules, never by a model.
          </p>
        </div>
      </div>

      <div className="card-grid" role="tablist" aria-label="Frameworks">
        {frameworks.map((f) => {
          const active = current?.framework === f.framework;
          return (
            <button key={f.framework} type="button" role="tab" aria-selected={active}
              className="card" style={{ textAlign: "left", cursor: "pointer", outline: active ? "2px solid var(--primary)" : undefined }}
              onClick={() => setParams({ f: f.framework })}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <strong>{f.framework}</strong>
                {f.already_subscribed ? <span className="badge badge-pass">subscribed</span> : <span className="badge badge-skipped">day-1 preview</span>}
              </div>
              <div className="readiness-bar"><div style={{ width: `${Math.round(f.readiness * 100)}%` }} /></div>
              <div className="stat-sub" style={{ marginTop: 6 }}>
                {Math.round(f.readiness * 100)}% · {f.satisfied} of {f.total_requirements} clauses met
              </div>
            </button>
          );
        })}
      </div>

      {current && (
        <>
          <div className="section-title">{current.framework}</div>
          <div className="card">
            <p>
              <strong>{current.satisfied}</strong> met, <strong>{current.partial}</strong> partly met,{" "}
              <strong>{Math.max(missing, 0)}</strong> not met or without evidence, out of{" "}
              <strong>{current.total_requirements}</strong> clauses we track for this framework.
              {!current.already_subscribed && " You are not subscribed yet: this counts only what your evidence on file already satisfies."}
            </p>
            <p className="stat-sub">
              Every clause we track is listed, but we do not yet cover every clause of the full standard. Meeting all of them
              here is progress, not a promise that an auditor will pass the whole framework.
              {" "}<Link to="/controls">Open controls</Link> · <Link to="/gaps">See gaps</Link>
            </p>
          </div>

          <div className="queue-filters" aria-label="Clause filters" style={{ gridTemplateColumns: "minmax(220px, 1fr) minmax(160px, auto)" }}>
            <input aria-label="Search clauses" placeholder="Search clause or title…" value={query} onChange={(e) => setQuery(e.target.value)} />
            <select aria-label="Which clauses" value={show} onChange={(e) => setShow(e.target.value as "attention" | "all")}>
              <option value="attention">Needs attention</option>
              <option value="all">All clauses</option>
            </select>
          </div>
          <DataTable columns={columns} rows={rows}
            emptyLabel={show === "attention" ? "Nothing needs attention here. Switch to all clauses to see everything." : "No clause matches."} />
        </>
      )}
    </div>
  );
}
