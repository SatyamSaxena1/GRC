import { useState } from "react";
import { getEvidenceExceptions } from "../api/client";
import { useApi } from "../lib/useApi";

const RULE_LABELS: Record<string, string> = {
  DEPLOY_NOT_FROM_DEFAULT: "Deployed from outside the default branch",
  DEPLOY_OF_UNREVIEWED_CHANGE: "Deployed an unreviewed change",
  NO_INDEPENDENT_APPROVAL: "No independent approval",
  GATE_PATH_UNDER_REVIEWED: "Gate file changed with too few approvals",
  CHECKS_FAILED_OR_MISSING: "Checks failed or missing",
  DIRECT_PUSH: "Direct push",
  GATE_FILE_REMOVED: "Gate file removed (advisory)",
  GATE_NEVER_FAILED: "Check never seen failing (advisory)",
};

const KIND_LABELS: Record<string, string> = {
  PULL_REQUEST: "pull request",
  DIRECT_PUSH: "push",
  GATE_CHECK: "check",
  DEPLOYMENT: "deployment",
};

// Most serious first: an unreviewed merge matters more than a push that skipped the PR flow.
const rank = (rule: string) => {
  const i = Object.keys(RULE_LABELS).indexOf(rule);
  return i === -1 ? Number.MAX_SAFE_INTEGER : i;
};

/** The merges and pushes behind a change-control snapshot's counts — what the auditor
 *  opens on GitHub to test each exception (ADR-020). Rows come from the stored snapshot,
 *  so they are exactly what was collected. */
export function ChangeExceptions({ evidenceId }: { evidenceId: string }) {
  const rows = useApi(() => getEvidenceExceptions(evidenceId), [evidenceId]);
  const all = rows.data?.exceptions ?? [];
  const leftOut = rows.data?.exceptions_left_out ?? 0;
  // One noisy rule (say, 70 direct pushes) must not bury the few merges that matter most.
  const [rule, setRule] = useState<string | null>(null);
  const counts = new Map<string, number>();
  for (const row of all) for (const r of row.reasons) counts.set(r.rule, (counts.get(r.rule) ?? 0) + 1);
  const exceptions = rule ? all.filter((row) => row.reasons.some((r) => r.rule === rule)) : all;

  return (
    <>
      <div className="section-title">
        Exceptions{rows.data && <span className="muted"> · {all.length + leftOut}</span>}
      </div>
      <div className="card" data-tour="change-exceptions">
        {rows.loading && <p className="muted">Loading the merges behind these counts…</p>}
        {rows.error && <p className="muted">Could not load the exception list.</p>}
        {rows.data && all.length === 0 && (
          <p className="muted">No merge or push in this period failed a change-control rule.</p>
        )}
        {all.length > 0 && (
          <>
            <p className="muted" style={{ margin: "0 0 10px", fontSize: 12 }}>
              Every merge, push or production deployment that failed a rule, newest first. Open each one on GitHub to test it;
              the counts above are decided from the same rules. Checks that never went red during the period
              are listed last: advisory only, they do not change a verdict, but an auditor relying on a check
              should see it fail once.
            </p>
            {counts.size > 1 && (
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
                <button type="button" className={rule === null ? "btn btn-primary btn-sm" : "btn btn-sm"}
                        onClick={() => setRule(null)}>All · {all.length}</button>
                {[...counts].sort(([a], [b]) => rank(a) - rank(b)).map(([key, n]) => (
                  <button key={key} type="button" className={rule === key ? "btn btn-primary btn-sm" : "btn btn-sm"}
                          onClick={() => setRule(key)}>{RULE_LABELS[key] ?? key} · {n}</button>
                ))}
              </div>
            )}
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr><th>Change</th><th>When</th><th>Author</th><th>AI-assisted</th><th>Why it is an exception</th></tr>
                </thead>
                <tbody>
                  {exceptions.map((row) => (
                    <tr key={`${row.repo}-${row.kind}-${row.ref}`}>
                      <td>
                        {row.url
                          ? <a href={row.url} target="_blank" rel="noopener noreferrer">{row.repo} {row.ref}</a>
                          : <>{row.repo} {row.ref}</>}
                        <div className="muted" style={{ fontSize: 11 }}>{KIND_LABELS[row.kind] ?? row.kind}</div>
                      </td>
                      <td>{row.at ? new Date(row.at).toLocaleDateString() : "—"}</td>
                      <td>{row.author ?? "—"}</td>
                      <td>{row.ai_assisted == null ? "—" : row.ai_assisted ? "yes (declared)" : "no"}</td>
                      <td>
                        {row.reasons.map((r) => (
                          <div key={r.rule}>
                            <strong>{RULE_LABELS[r.rule] ?? r.rule}</strong>
                            <span className="muted"> — {r.detail}</span>
                          </div>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {leftOut > 0 && (
              <p className="muted" style={{ marginTop: 8, fontSize: 12 }}>
                {leftOut} more not listed (the snapshot keeps the newest {all.length}); the counts include them.
              </p>
            )}
          </>
        )}
      </div>
    </>
  );
}
