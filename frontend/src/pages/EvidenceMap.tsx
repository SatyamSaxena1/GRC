import { lazy, Suspense, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getControl, listControls, listEvidence, type ControlDetail, type EvidenceSummary } from "../api/client";
import { useApi } from "../lib/useApi";
import { useSession } from "../lib/session";
import { roleOf } from "../lib/roles";
import { VERDICT_COLOR, type GraphEdge, type GraphNode } from "../lib/graph";

const EvidenceGraph3D = lazy(() => import("../components/EvidenceGraph3D"));

const RANK: Record<string, number> = { FAIL: 0, PARTIAL: 1, PASS: 2 };
const verdictOf = (l: { verdict: string; auditor_verdict: string | null }) => l.auditor_verdict ?? l.verdict;
const bestOf = (c: ControlDetail): string | null =>
  c.links.length === 0 ? null
    : c.links.map(verdictOf).reduce((a, b) => ((RANK[b] ?? -1) > (RANK[a] ?? -1) ? b : a));

export function EvidenceMapPage() {
  const navigate = useNavigate();
  const { identity } = useSession();
  const accent = roleOf(identity)?.color ?? "#3454d1";
  const [focus, setFocus] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);

  const data = useApi(async () => {
    const summaries = await listControls();
    const controls = await Promise.all(summaries.map((c) => getControl(c.id)));
    // Not every role may list evidence; the graph still stands on control links.
    const evidence = await listEvidence().catch(() => [] as EvidenceSummary[]);
    return { controls, evidence };
  }, []);

  const graph = useMemo(() => {
    if (!data.data) return null;
    const { controls, evidence } = data.data;
    const names = new Map(evidence.map((e) => [e.id, e.original_filename]));
    const nodes: GraphNode[] = [];
    const edges: GraphEdge[] = [];
    const fws = [...new Set(controls.map((c) => c.framework))].sort();
    for (const fw of fws) nodes.push({ kind: "framework", id: `fw:${fw}`, label: fw });
    const linkCount = new Map<string, number>();
    for (const c of controls) {
      nodes.push({ kind: "control", id: c.id, label: `${c.framework} ${c.clause}`, framework: `fw:${c.framework}`, verdict: bestOf(c) });
      for (const l of c.links) {
        edges.push({ from: `ev:${l.evidence_id}`, to: c.id, verdict: verdictOf(l) });
        linkCount.set(l.evidence_id, (linkCount.get(l.evidence_id) ?? 0) + 1);
      }
    }
    const evidenceIds = new Set([...linkCount.keys(), ...evidence.map((e) => e.id)]);
    for (const id of evidenceIds) {
      nodes.push({ kind: "evidence", id: `ev:${id}`, label: names.get(id) ?? `Evidence ${id.slice(0, 6)}`, links: linkCount.get(id) ?? 0 });
    }
    const perFw = fws.map((fw) => {
      const cs = controls.filter((c) => c.framework === fw);
      const v = cs.map(bestOf);
      return {
        fw, total: cs.length,
        pass: v.filter((x) => x === "PASS").length,
        partial: v.filter((x) => x === "PARTIAL").length,
        fail: v.filter((x) => x === "FAIL").length,
        none: v.filter((x) => x === null).length,
      };
    });
    const reused = [...evidenceIds]
      .map((id) => ({ id, name: names.get(id) ?? `Evidence ${id.slice(0, 6)}`, links: linkCount.get(id) ?? 0 }))
      .sort((a, b) => b.links - a.links);
    return { nodes, edges, perFw, reused, controls };
  }, [data.data]);

  const pick = (node: GraphNode) => {
    if (node.kind === "control") navigate(`/controls/${node.id}`);
    else if (node.kind === "evidence") navigate(`/evidence/${node.id.slice(3)}`);
    else setFocus((f) => (f === node.id ? null : node.id));
  };

  const hovered = graph?.nodes.find((n) => n.id === (hover ?? focus));
  const totals = graph?.perFw.reduce(
    (t, f) => ({ total: t.total + f.total, pass: t.pass + f.pass, partial: t.partial + f.partial, fail: t.fail + f.fail, none: t.none + f.none }),
    { total: 0, pass: 0, partial: 0, fail: 0, none: 0 },
  );

  return (
    <div className="map-page">
      <div className="map-stage">
        <div className="map-stage__hud">
          <strong>Evidence map</strong>
          <span>◆ artefact</span><span>● control</span><span>◯ framework</span>
          {Object.entries({ PASS: "pass", PARTIAL: "partial", FAIL: "fail", NONE: "no evidence" }).map(([k, v]) => (
            <span key={k}><i style={{ background: VERDICT_COLOR[k] }} />{v}</span>
          ))}
          <span className="map-stage__help">Drag to orbit · scroll to zoom · click a ring to isolate it, anything else to open it</span>
          <button type="button" className="btn btn-sm" onClick={data.reload}>Refresh</button>
        </div>
        {data.error && <div className="alert alert-error">{data.error}</div>}
        {graph && graph.nodes.length > 0 ? (
          <Suspense fallback={<div className="graph3d graph3d--loading">Loading 3D…</div>}>
            <EvidenceGraph3D nodes={graph.nodes} edges={graph.edges} focus={focus} accent={accent} onHover={setHover} onPick={pick} />
          </Suspense>
        ) : (
          <div className="graph3d graph3d--loading">{data.loading ? "Loading controls and evidence…" : "Nothing visible to this identity yet."}</div>
        )}
        {hovered && (
          <div className="map-stage__focus">
            <small>{hovered.kind}</small>
            <strong>{hovered.label}</strong>
            {hovered.kind === "evidence" && <span>{hovered.links} control links · click to open</span>}
            {hovered.kind === "control" && <span>{hovered.verdict ?? "no evidence yet"} · click to open</span>}
            {hovered.kind === "framework" && <span>{focus === hovered.id ? "isolated · click again to clear" : "click to isolate"}</span>}
          </div>
        )}
      </div>

      <aside className="map-side">
        {totals && (
          <div className="map-kpis">
            <div><b>{totals.total}</b><small>controls</small></div>
            <div style={{ color: VERDICT_COLOR.PASS }}><b>{totals.pass}</b><small>pass</small></div>
            <div style={{ color: VERDICT_COLOR.PARTIAL }}><b>{totals.partial}</b><small>partial</small></div>
            <div style={{ color: VERDICT_COLOR.FAIL }}><b>{totals.fail}</b><small>fail</small></div>
            <div><b>{totals.none}</b><small>uncovered</small></div>
          </div>
        )}
        <h4>Frameworks</h4>
        <ul className="map-fw">
          {graph?.perFw.map((f) => (
            <li key={f.fw}>
              <button
                type="button"
                className={focus === `fw:${f.fw}` ? "is-on" : ""}
                onClick={() => setFocus((x) => (x === `fw:${f.fw}` ? null : `fw:${f.fw}`))}
                onMouseEnter={() => setHover(`fw:${f.fw}`)}
                onMouseLeave={() => setHover(null)}
              >
                <span className="map-fw__name">{f.fw}</span>
                <span className="map-fw__bar">
                  {(["pass", "partial", "fail", "none"] as const).map((k) => (
                    <i key={k} style={{ flex: f[k], background: VERDICT_COLOR[k === "none" ? "NONE" : k.toUpperCase()] }} />
                  ))}
                </span>
                <span className="map-fw__n">{f.total - f.none}/{f.total}</span>
              </button>
            </li>
          ))}
        </ul>
        <h4>Most reused artefacts</h4>
        <ul className="map-ev">
          {graph?.reused.slice(0, 8).map((e) => (
            <li key={e.id}>
              <button
                type="button"
                onClick={() => navigate(`/evidence/${e.id}`)}
                onMouseEnter={() => setHover(`ev:${e.id}`)}
                onMouseLeave={() => setHover(null)}
              >
                <span>{e.name}</span><b>{e.links}</b>
              </button>
            </li>
          ))}
          {graph && graph.reused.length === 0 && <li className="muted">No evidence uploaded yet.</li>}
        </ul>
      </aside>
    </div>
  );
}
