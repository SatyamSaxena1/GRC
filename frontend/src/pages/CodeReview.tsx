import { useState } from "react";
import {
  ApiError,
  activateReviewStandard,
  listReviewPacks,
  listReviewStandards,
  publishReviewStandard,
  reviewProblems,
  tryReviewStandard,
  type ReviewProblem,
  type ReviewResult,
} from "../api/client";
import { useApi } from "../lib/useApi";
import { useSession } from "../lib/session";

/** Review Standards (ADR-027): the organisation's code-review rules, versioned and hashed, so
 *  every review result names the exact rules it was judged by. */
export function CodeReviewPage() {
  const { identity } = useSession();
  // The backend re-checks: only an organisation admin can publish or activate.
  const isAdmin = identity?.kind === "org" || ((identity?.kind === "user" || identity?.kind === "oidc")
    && (identity.role ?? "ORG_ADMIN") === "ORG_ADMIN" && !identity.engagementId);
  const canWrite = identity?.kind !== "auditor" && !(identity && "engagementId" in identity && identity.engagementId)
    && identity?.role !== "COMPLIANCE_VIEWER";
  const standards = useApi(() => listReviewStandards(), []);
  const packs = useApi(() => listReviewPacks(), []);
  const active = standards.data?.versions.find((v) => v.is_active);
  const activeVersion = active?.version ?? 0;
  const inForce = active
    ? { name: active.name, version: `v${active.version}`, hash: active.body_hash, yaml: active.source_yaml }
    : standards.data && { name: standards.data.default.name, version: "built-in", hash: standards.data.default.body_hash,
                          yaml: standards.data.default.source_yaml };
  const [draft, setDraft] = useState<string | null>(null);
  const [problems, setProblems] = useState<ReviewProblem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const yaml = draft ?? inForce?.yaml ?? "";

  const publish = async () => {
    setBusy(true);
    setProblems(null);
    setError(null);
    try {
      await publishReviewStandard(yaml, activeVersion);
      setDraft(null);
      standards.reload();
    } catch (err) {
      const found = reviewProblems(err);
      if (found) setProblems(found);
      else setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const activate = async (id: string) => {
    setError(null);
    try {
      await activateReviewStandard(id, activeVersion);
      standards.reload();
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Code review</h2>
          <p>
            Your organisation's review standard: the rules every pull request is checked against. Rules decide;
            a model only ever advises. Each version is hashed, and publishing one is recorded in the audit trail.
          </p>
        </div>
      </div>

      {standards.loading && <p className="muted">Loading…</p>}
      {standards.error && <div className="alert alert-error">{standards.error}</div>}
      {error && <div className="alert alert-error">{error}</div>}

      {inForce && (
        <div className="card">
          <div className="section-title" style={{ marginTop: 0 }}>In force</div>
          <p style={{ margin: 0 }}>
            <strong>{inForce.name}</strong> <span className="badge badge-info">{inForce.version}</span>{" "}
            <code className="muted" title={inForce.hash}>{inForce.hash.slice(0, 12)}</code>
          </p>
          {!active && (
            <p className="muted" style={{ margin: "8px 0 0", fontSize: 13 }}>
              The built-in default applies until an admin publishes a standard. Nothing in it blocks a merge.
            </p>
          )}
        </div>
      )}

      <div className="section-title">{isAdmin ? "Edit and publish" : "Standard"}</div>
      <div className="card">
        {isAdmin && packs.data && packs.data.length > 0 && (
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
            <label htmlFor="pack" className="muted" style={{ fontSize: 13 }}>Start from a built-in pack</label>
            <select id="pack" defaultValue="" onChange={(e) => {
              const pack = packs.data?.find((p) => p.id === e.target.value);
              if (pack) { setDraft(pack.yaml); setProblems(null); }
            }}>
              <option value="" disabled>Choose…</option>
              {packs.data.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.rules} rules)</option>)}
            </select>
          </div>
        )}
        <textarea
          aria-label="Review standard (YAML)"
          value={yaml}
          readOnly={!isAdmin}
          onChange={(e) => setDraft(e.target.value)}
          rows={18}
          spellCheck={false}
          style={{ width: "100%", fontFamily: "var(--mono, monospace)", fontSize: 13 }}
        />
        {problems && (
          <div className="alert alert-error" style={{ marginTop: 10 }}>
            <strong>Not published: fix these first</strong>
            <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
              {problems.map((p, i) => (
                <li key={i}>{p.line ? `Line ${p.line}: ` : ""}{p.message}</li>
              ))}
            </ul>
          </div>
        )}
        {isAdmin && (
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <button className="btn btn-primary" type="button" disabled={busy || !yaml.trim()} onClick={publish}>
              {busy ? "Publishing…" : "Publish as new version"}
            </button>
            {draft !== null && (
              <button className="btn" type="button" onClick={() => { setDraft(null); setProblems(null); }}>
                Discard changes
              </button>
            )}
          </div>
        )}
      </div>

      {canWrite && <TryIt yaml={draft ?? undefined} />}

      {standards.data && standards.data.versions.length > 0 && (
        <>
          <div className="section-title">Versions</div>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr><th>Version</th><th>Name</th><th>Hash</th><th>Rules</th><th>Published by</th><th></th></tr>
              </thead>
              <tbody>
                {standards.data.versions.map((v) => (
                  <tr key={v.id}>
                    <td>v{v.version} {v.is_active && <span className="badge badge-active">active</span>}</td>
                    <td>{v.name}</td>
                    <td><code title={v.body_hash}>{v.body_hash.slice(0, 12)}</code></td>
                    <td>{v.rules.length}</td>
                    <td>{v.created_by} · {new Date(v.created_at).toLocaleString()}</td>
                    <td>
                      {isAdmin && !v.is_active && (
                        <button className="btn btn-sm" type="button" onClick={() => activate(v.id)}>Make active</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

const OUTCOME_BADGE: Record<string, string> = { passed: "pass", violated: "fail", incomplete: "pending", error: "failed" };

/** Paste a diff and see what the standard would say. Nothing is stored: the diff is code. */
function TryIt({ yaml }: { yaml?: string }) {
  const [diff, setDiff] = useState("");
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [problems, setProblems] = useState<ReviewProblem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    setError(null);
    setProblems(null);
    try {
      setResult(await tryReviewStandard(diff, yaml));
    } catch (err) {
      setResult(null);
      const found = reviewProblems(err);
      if (found) setProblems(found);
      else setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="section-title">Try it on a diff</div>
      <div className="card">
        <p className="muted" style={{ margin: "0 0 8px", fontSize: 13 }}>
          Paste the output of <code>git diff</code>. It is checked against {yaml ? "your unpublished edits" : "the standard in force"} and
          nothing is stored.
        </p>
        <textarea aria-label="Diff to review" value={diff} onChange={(e) => setDiff(e.target.value)} rows={8}
                  spellCheck={false} style={{ width: "100%", fontFamily: "var(--mono, monospace)", fontSize: 13 }} />
        <div style={{ marginTop: 10 }}>
          <button className="btn" type="button" disabled={busy || !diff.trim()} onClick={run}>
            {busy ? "Reviewing…" : "Review this diff"}
          </button>
        </div>
        {error && <div className="alert alert-error" style={{ marginTop: 10 }}>{error}</div>}
        {problems && (
          <div className="alert alert-error" style={{ marginTop: 10 }}>
            {problems.map((p, i) => <div key={i}>{p.line ? `Line ${p.line}: ` : ""}{p.message}</div>)}
          </div>
        )}
        {result && (
          <div style={{ marginTop: 12 }}>
            <p style={{ margin: "0 0 8px" }}>
              <span className={`badge badge-${OUTCOME_BADGE[result.outcome]}`}>{result.outcome}</span>{" "}
              {result.blocks_merge
                ? <span className="badge badge-fail">would block the merge</span>
                : <span className="badge badge-pass">would not block</span>}{" "}
              <span className="muted">{result.findings.length} finding(s) in {result.files} file(s)</span>
            </p>
            {result.skipped.length > 0 && (
              <p className="muted" style={{ fontSize: 13 }}>
                Not read ({result.skipped.length}): {result.skipped.slice(0, 5).map((s) => `${s.path} (${s.reason})`).join(", ")}
                {result.skipped.length > 5 ? "…" : ""}. A review that could not read everything is never a pass.
              </p>
            )}
            {result.findings.length > 0 && (
              <div className="table-scroll">
                <table className="data-table">
                  <thead><tr><th>Severity</th><th>Rule</th><th>Category</th><th>Where</th><th>Finding</th></tr></thead>
                  <tbody>
                    {result.findings.map((f, i) => (
                      <tr key={i}>
                        <td>
                          <span className={`badge badge-${f.severity}`}>{f.severity}</span>
                          {f.action === "block" && <span className="badge badge-fail" style={{ marginLeft: 4 }}>blocks</span>}
                          {f.kind === "rule_error" && <span className="badge badge-pending" style={{ marginLeft: 4 }}>not checked</span>}
                        </td>
                        <td><code>{f.rule_id}</code></td>
                        <td>{f.category}</td>
                        <td><code>{f.path}{f.line ? `:${f.line}${f.end_line && f.end_line !== f.line ? `-${f.end_line}` : ""}` : ""}</code></td>
                        <td>{f.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {result.not_evaluated.length > 0 && (
              <p className="muted" style={{ fontSize: 13 }}>
                Not evaluated yet (model-checked rules arrive with the AI reviewer): {result.not_evaluated.join(", ")}
              </p>
            )}
          </div>
        )}
      </div>
    </>
  );
}
