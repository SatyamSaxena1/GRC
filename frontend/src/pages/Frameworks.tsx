import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ApiError, attestControl, getReadinessAll, listAttestations, revokeAttestation, type Attestation, type FrameworkReadiness,
} from "../api/client";
import { useApi } from "../lib/useApi";
import { Badge } from "../components/Badge";
import { DataTable, type Column } from "../components/DataTable";

type Clause = FrameworkReadiness["clauses"][number];

const NEEDS_WORK = new Set(["FAIL", "PARTIAL", "NO_EVIDENCE"]);
const ORDER = ["FAIL", "NO_EVIDENCE", "PARTIAL", "ATTESTED", "PASS", "NOT_APPLICABLE"];

function inAYear(): string {
  const d = new Date();
  d.setFullYear(d.getFullYear() + 1);
  return d.toISOString().slice(0, 10);
}

/** A person's dated statement for a clause no rule judges yet (ADR-060). Never a PASS: the auditor judges it. */
function AttestCell({ framework, clause, current, subscribed, onDone }: {
  framework: string; clause: Clause; current: Attestation | undefined; subscribed: boolean; onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [statement, setStatement] = useState("");
  const [until, setUntil] = useState(inAYear());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      setOpen(false);
      setStatement("");
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : (e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  if (!clause.attestation_only) return <span className="stat-sub">Rules check your evidence</span>;
  if (current) {
    return (
      <div className="stat-sub">
        Attested by {current.attested_by_display ?? current.attested_by} until {current.valid_until}: “{current.statement}”{" "}
        <button type="button" className="btn btn-link" disabled={busy}
          onClick={() => run(() => revokeAttestation(current.id))}>Withdraw</button>
        {error && <div className="alert alert-error">{error}</div>}
      </div>
    );
  }
  if (!subscribed) return <span className="stat-sub">No rule yet: subscribe, then attest</span>;
  if (!open) {
    return (
      <span className="stat-sub">
        No rule yet.{" "}
        <button type="button" className="btn btn-sm" onClick={() => setOpen(true)}>Attest</button>
      </span>
    );
  }
  return (
    <form onSubmit={(e) => { e.preventDefault(); run(() => attestControl({ framework, clause: clause.clause, statement, valid_until: until })); }}>
      <label className="stat-sub" htmlFor={`st-${clause.clause}`}>How is this in place? Name the policy, tool or record an auditor can check.</label>
      <textarea id={`st-${clause.clause}`} required minLength={20} rows={3} value={statement}
        onChange={(e) => setStatement(e.target.value)} style={{ width: "100%" }} />
      <label className="stat-sub">Valid until{" "}
        <input type="date" required value={until} onChange={(e) => setUntil(e.target.value)} />
      </label>{" "}
      <button type="submit" className="btn btn-primary" disabled={busy || statement.trim().length < 20}>Attest</button>{" "}
      <button type="button" className="btn btn-link" onClick={() => setOpen(false)}>Cancel</button>
      {error && <div className="alert alert-error">{error}</div>}
    </form>
  );
}

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
  const attestations = useApi(
    () => (current ? listAttestations(current.framework) : Promise.resolve([] as Attestation[])), [current?.framework]);
  const inForce = useMemo(
    () => new Map((attestations.data ?? []).filter((a) => a.current).map((a) => [a.clause, a])), [attestations.data]);
  const reload = () => { state.reload(); attestations.reload(); };

  const rows = useMemo(() => {
    if (!current) return [];
    const q = query.trim().toLowerCase();
    return current.clauses
      .filter((c) => (show === "all" || NEEDS_WORK.has(c.verdict)) && (!q || `${c.clause} ${c.title}`.toLowerCase().includes(q)))
      .sort((a, b) => ORDER.indexOf(a.verdict) - ORDER.indexOf(b.verdict) || a.clause.localeCompare(b.clause, undefined, { numeric: true }));
  }, [current, show, query]);

  if (state.error) return <div className="alert alert-error">{state.error}</div>;
  if (!state.data) return <p className="muted">Loading…</p>;

  const attested = current?.attested ?? 0;
  const ruleLess = current ? current.clauses.filter((c) => c.attestation_only).length : 0;
  const missing = current ? current.total_requirements - current.satisfied - current.partial - attested : 0;
  const columns: Column<Clause>[] = [
    { key: "clause", header: "Clause", render: (c) => <span className="mono">{c.clause}</span> },
    { key: "title", header: "What it asks", render: (c) => c.title },
    { key: "verdict", header: "Verdict", render: (c) => <Badge value={c.verdict} /> },
    { key: "how", header: "How it is checked", render: (c) => current && (
      <AttestCell framework={current.framework} clause={c} current={inForce.get(c.clause)}
        subscribed={current.already_subscribed} onDone={reload} />) },
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
                {Math.round(f.readiness * 100)}% · {f.satisfied + (f.attested ?? 0)} of {f.total_requirements} clauses met
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
              <strong>{current.satisfied}</strong> met by the rules, <strong>{attested}</strong> attested,{" "}
              <strong>{current.partial}</strong> partly met,{" "}
              <strong>{Math.max(missing, 0)}</strong> not met or without evidence, out of{" "}
              <strong>{current.total_requirements}</strong> clauses we track for this framework.
              {!current.already_subscribed && " You are not subscribed yet: this counts only what your evidence on file already satisfies."}
            </p>
            <p className="stat-sub">
              {ruleLess > 0 && <>{ruleLess} of these clauses have no automatic rule yet: a named person attests each one,
                with a date, and your auditor judges the statement. Attested is never shown as passed by the rules. </>}
              Meeting every clause here is progress, not a promise that an auditor will pass the whole framework.
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
