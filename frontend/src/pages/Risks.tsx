import { useState, type ReactNode } from "react";
import {
  ApiError, addRisk, draftRisk, listControls, listRisks, reviewRisk, updateRisk,
  type ControlSummary, type Risk, type RiskBand, type RiskDraft, type RiskHeatCell, type RiskIn, type RiskRegister,
} from "../api/client";
import { useApi } from "../lib/useApi";
import "./Risks.css";

const LIKELIHOOD = ["Rare", "Unlikely", "Possible", "Likely", "Almost certain"];
const IMPACT = ["Negligible", "Minor", "Moderate", "Major", "Severe"];
const CATEGORIES = ["SECURITY", "PRIVACY", "COMPLIANCE", "OPERATIONAL", "VENDOR", "AI", "OTHER"];
const TREATMENTS: [NonNullable<Risk["treatment"]>, string][] = [
  ["MITIGATE", "Reduce it"], ["ACCEPT", "Accept it"], ["TRANSFER", "Pass it on (insurance, contract)"], ["AVOID", "Stop doing the thing"],
];
const STATUSES: [Risk["status"], string][] = [["OPEN", "Open"], ["IN_TREATMENT", "Being treated"], ["CLOSED", "Closed"]];
const REVIEW_LABEL: Record<Risk["review_state"], string> = {
  OVERDUE: "Overdue", DUE_SOON: "Due soon", CURRENT: "Current", CLOSED: "Closed",
};
const word = (s: string) => s.charAt(0) + s.slice(1).toLowerCase().replace(/_/g, " ");

function fail(err: unknown): string {
  if (err instanceof ApiError) {
    // A 422 carries a list of {msg}; show the sentences, not "[object Object]".
    if (Array.isArray(err.detail)) return err.detail.map((d) => (d as { msg?: string }).msg ?? String(d)).join("; ");
    return String(err.detail);
  }
  return (err as Error).message;
}

function Band({ band, score }: { band: RiskBand; score?: number }) {
  return <span className={`band-chip band-${band}`}>{word(band)}{score !== undefined && ` · ${score}`}</span>;
}

type View = "inherent" | "current";

function HeatMap({ cells, bands, selected, onPick }: {
  cells: RiskHeatCell[]; bands: RiskRegister["bands"]; selected: [number, number] | null;
  onPick: (cell: [number, number] | null) => void;
}) {
  // The server sends all 25 cells, likelihood 5 down to 1, impact 1 to 5 across each row.
  const rows = [5, 4, 3, 2, 1];
  return (
    <div>
      <div className="heat" role="group" aria-label="Risk heat map: likelihood down the side, impact along the bottom">
        {rows.flatMap((l) => [
          <div key={`y${l}`} className="heat-axis" title={LIKELIHOOD[l - 1]}>{l}</div>,
          ...cells.filter((c) => c.likelihood === l).map((c) => {
            const on = selected?.[0] === c.likelihood && selected?.[1] === c.impact;
            return (
              <button key={`${c.likelihood}-${c.impact}`} type="button"
                className={`heat-cell band-${c.band}${c.count === 0 ? " is-empty" : ""}`} aria-pressed={on}
                aria-label={`Likelihood ${c.likelihood}, impact ${c.impact}: ${c.count} ${c.count === 1 ? "risk" : "risks"}, ${word(c.band)}`}
                onClick={() => onPick(on ? null : [c.likelihood, c.impact])}>
                {c.count > 0 ? c.count : "·"}<small>{c.score}</small>
              </button>
            );
          }),
        ])}
        <div className="heat-axis" />
        {[1, 2, 3, 4, 5].map((i) => <div key={`x${i}`} className="heat-axis" title={IMPACT[i - 1]}>{i}</div>)}
      </div>
      <p className="muted" style={{ fontSize: 12, margin: "6px 0 0" }}>
        Up the side: how likely (5 = almost certain). Along the bottom: how bad (5 = severe). Small number: score.
      </p>
      <div className="risk-legend">
        {[...bands].reverse().map((b) => <span key={b.band} className={`band-chip band-${b.band}`}>{word(b.band)} from {b.from}</span>)}
      </div>
    </div>
  );
}

type Form = {
  title: string; description: string; category: string; owner_email: string;
  il: number; ii: number; treatment: string; plan: string; rl: string; ri: string;
  status: Risk["status"]; next: string; controls: string[];
};
const blank: Form = {
  title: "", description: "", category: "OTHER", owner_email: "", il: 3, ii: 3, treatment: "", plan: "",
  rl: "", ri: "", status: "OPEN", next: "", controls: [],
};
const fromRisk = (r: Risk): Form => ({
  title: r.title, description: r.description, category: r.category, owner_email: r.owner_email,
  il: r.inherent.likelihood, ii: r.inherent.impact, treatment: r.treatment ?? "", plan: r.treatment_plan,
  rl: r.residual ? String(r.residual.likelihood) : "", ri: r.residual ? String(r.residual.impact) : "",
  status: r.status, next: r.next_review_date ?? "", controls: r.controls.map((c) => c.id),
});

function bandOf(score: number, bands: RiskRegister["bands"]): RiskBand {
  // The thresholds come from the server (highest first); this only looks the band up for the live preview.
  return (bands.find((b) => score >= b.from) ?? bands[bands.length - 1]).band;
}

function Select({ id, value, onChange, children, disabled }: {
  id: string; value: string | number; onChange: (v: string) => void; children: ReactNode; disabled?: boolean;
}) {
  return <select id={id} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>{children}</select>;
}

function RiskDrawer({ risk, register, controls, onClose, onSaved }: {
  risk: Risk | null; register: RiskRegister; controls: ControlSummary[];
  onClose: () => void; onSaved: () => void;
}) {
  const isNew = risk === null;
  const canEdit = isNew ? register.can_write_all : register.can_write;
  const admin = register.can_write_all;
  const [f, setF] = useState<Form>(risk ? fromRisk(risk) : blank);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<RiskDraft | null>(null);
  const [note, setNote] = useState("");
  const set = <K extends keyof Form>(key: K, value: Form[K]) => setF((prev) => ({ ...prev, [key]: value }));

  const residualHalf = (f.rl === "") !== (f.ri === "");
  const inherentScore = f.il * f.ii;
  const residualScore = f.rl && f.ri ? Number(f.rl) * Number(f.ri) : null;
  const valid = f.title.trim().length >= 3 && !residualHalf;

  const run = async (fn: () => Promise<unknown>, done: () => void) => {
    setBusy(true);
    setError(null);
    try { await fn(); done(); } catch (err) { setError(fail(err)); } finally { setBusy(false); }
  };

  const payload = (): Partial<RiskIn> & Pick<RiskIn, "title" | "inherent_likelihood" | "inherent_impact"> => ({
    title: f.title.trim(), description: f.description, category: f.category, owner_email: f.owner_email.trim(),
    inherent_likelihood: f.il, inherent_impact: f.ii, treatment: (f.treatment || null) as Risk["treatment"],
    treatment_plan: f.plan, residual_likelihood: f.rl ? Number(f.rl) : null, residual_impact: f.ri ? Number(f.ri) : null,
    status: f.status, ...(f.next ? { next_review_date: f.next } : {}), control_ids: f.controls,
  });

  const save = () => run(async () => {
    if (isNew) return addRisk(payload());
    // A control owner may not change the owner or the linked controls; leave them out rather than be refused.
    const { owner_email: _o, control_ids: _c, ...rest } = payload();
    return updateRisk(risk.id, admin ? payload() : rest);
  }, onSaved);

  const suggest = () => run(async () => setDraft(await draftRisk(f.title.trim(), f.description)), () => undefined);

  return (
    <div className="drawer-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="task-drawer" aria-label={isNew ? "Add a risk" : "Risk details"} style={{ width: "min(640px, 96vw)" }}>
        <div className="drawer-header">
          <div>
            <span className="muted">{isNew ? "New risk" : `${word(risk.category)} risk`}</span>
            <h3>{isNew ? "Add a risk" : risk.title}</h3>
          </div>
          <button className="drawer-close" onClick={onClose} aria-label="Close risk details">×</button>
        </div>

        {error && <div className="alert alert-error" style={{ marginTop: 14 }}>{error}</div>}
        {!canEdit && <p className="muted">You can read the register. An organisation admin, or the risk's owner, changes it.</p>}

        <div className="risk-form">
          <label className="wide">What could go wrong
            <input id="r-title" value={f.title} disabled={!canEdit} maxLength={200} onChange={(e) => set("title", e.target.value)}
              placeholder="For example: a laptop with customer data is stolen" /></label>
          <label className="wide">Description
            <textarea id="r-desc" value={f.description} disabled={!canEdit} maxLength={4000} onChange={(e) => set("description", e.target.value)} /></label>
        </div>

        {canEdit && (
          <div style={{ marginBottom: 14 }}>
            <button className="btn btn-sm" type="button" disabled={busy || f.title.trim().length < 3} onClick={suggest}>
              Suggest wording with AI
            </button>{" "}
            <span className="muted" style={{ fontSize: 12 }}>Wording only. It never sets a score, and nothing is saved until you save.</span>
          </div>
        )}
        {draft && (
          <div className="risk-draft" role="region" aria-label="Draft wording from a model">
            <strong>Draft from {draft.model}: not yet part of the register</strong>
            <div className="muted" style={{ fontSize: 12 }}>{draft.notice}</div>
            {draft.description && <><div style={{ marginTop: 8 }}><em>Description</em></div><pre>{draft.description}</pre>
              <button className="btn btn-sm" type="button" onClick={() => set("description", draft.description)}>Put in the description</button></>}
            {draft.treatment_plan && <><div style={{ marginTop: 8 }}><em>Treatment plan</em></div><pre>{draft.treatment_plan}</pre>
              <button className="btn btn-sm" type="button" onClick={() => set("plan", draft.treatment_plan)}>Put in the treatment plan</button></>}{" "}
            <button className="btn btn-sm" type="button" onClick={() => setDraft(null)}>Dismiss</button>
          </div>
        )}

        <div className="section-title">How bad, before any treatment</div>
        <div className="risk-form">
          <label>Likelihood
            <Select id="r-il" value={f.il} disabled={!canEdit} onChange={(v) => set("il", Number(v))}>
              {LIKELIHOOD.map((t, i) => <option key={t} value={i + 1}>{i + 1} · {t}</option>)}</Select></label>
          <label>Impact
            <Select id="r-ii" value={f.ii} disabled={!canEdit} onChange={(v) => set("ii", Number(v))}>
              {IMPACT.map((t, i) => <option key={t} value={i + 1}>{i + 1} · {t}</option>)}</Select></label>
          <div className="risk-score-preview wide">
            Score {inherentScore} <Band band={bandOf(inherentScore, register.bands)} />
            <span className="muted">Worked out by fixed rules: likelihood times impact. It cannot be typed in.</span>
          </div>
        </div>

        <div className="section-title">What you are doing about it</div>
        <div className="risk-form">
          <label>Treatment
            <Select id="r-treat" value={f.treatment} disabled={!canEdit} onChange={(v) => set("treatment", v)}>
              <option value="">Not decided yet</option>
              {TREATMENTS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}</Select></label>
          <label>Status
            <Select id="r-status" value={f.status} disabled={!canEdit} onChange={(v) => set("status", v as Risk["status"])}>
              {STATUSES.map(([k, label]) => <option key={k} value={k}>{label}</option>)}</Select></label>
          <label className="wide">Treatment plan
            <textarea id="r-plan" value={f.plan} disabled={!canEdit} maxLength={4000} onChange={(e) => set("plan", e.target.value)} /></label>
          <label>Likelihood after treatment
            <Select id="r-rl" value={f.rl} disabled={!canEdit} onChange={(v) => set("rl", v)}>
              <option value="">Not assessed yet</option>
              {LIKELIHOOD.map((t, i) => <option key={t} value={i + 1}>{i + 1} · {t}</option>)}</Select></label>
          <label>Impact after treatment
            <Select id="r-ri" value={f.ri} disabled={!canEdit} onChange={(v) => set("ri", v)}>
              <option value="">Not assessed yet</option>
              {IMPACT.map((t, i) => <option key={t} value={i + 1}>{i + 1} · {t}</option>)}</Select></label>
          <div className="risk-score-preview wide">
            {residualScore === null
              ? <span className="muted">{residualHalf ? "Give both the likelihood and the impact after treatment, or neither." : "Until you assess it, the risk stays where it started."}</span>
              : <>After treatment: score {residualScore} <Band band={bandOf(residualScore, register.bands)} /></>}
          </div>
        </div>

        <div className="section-title">Who and when</div>
        <div className="risk-form">
          <label>Owner's email
            <input id="r-owner" type="email" value={f.owner_email} disabled={!admin} onChange={(e) => set("owner_email", e.target.value)}
              placeholder="the person who answers for this risk" /></label>
          <label>Category
            <Select id="r-cat" value={f.category} disabled={!canEdit} onChange={(v) => set("category", v)}>
              {CATEGORIES.map((c) => <option key={c} value={c}>{word(c)}</option>)}</Select></label>
          <label>Next review
            <input id="r-next" type="date" value={f.next} disabled={!canEdit} onChange={(e) => set("next", e.target.value)} /></label>
          <span className="muted" style={{ fontSize: 12, alignSelf: "end" }}>
            {isNew && !f.next ? "Left empty, it is set from the score: critical 30 days, high 90, medium 180, low 365." : ""}
          </span>
          <div className="wide">
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 5 }}>Controls that treat this risk</div>
            <div className="risk-controls">
              {controls.length === 0 && <span className="muted">No controls registered yet.</span>}
              {controls.map((c) => (
                <label key={c.id}>
                  <input type="checkbox" checked={f.controls.includes(c.id)} disabled={!admin}
                    onChange={(e) => set("controls", e.target.checked ? [...f.controls, c.id] : f.controls.filter((x) => x !== c.id))} />
                  {c.framework} {c.clause}
                </label>
              ))}
            </div>
          </div>
        </div>

        {canEdit && <button className="btn btn-primary" disabled={busy || !valid} onClick={save}>{busy ? "Saving…" : isNew ? "Add to the register" : "Save changes"}</button>}

        {!isNew && canEdit && risk.status !== "CLOSED" && (
          <>
            <div className="section-title">Review</div>
            <p className="muted" style={{ fontSize: 13, margin: "0 0 8px" }}>
              {risk.last_reviewed_at ? `Last reviewed ${risk.last_reviewed_at.slice(0, 10)}. ` : "Never reviewed. "}
              Recording a review sets the next one from the current band ({risk.review_every_days} days).
            </p>
            <div style={{ display: "flex", gap: 8 }}>
              <input aria-label="Review note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="What did you check?"
                style={{ flex: 1, padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 8 }} />
              <button className="btn" disabled={busy || note.trim().split(/\s+/).length < 3}
                onClick={() => run(() => reviewRisk(risk.id, note), onSaved)}>Mark reviewed</button>
            </div>
          </>
        )}
      </aside>
    </div>
  );
}

/** The risk register (ADR-056): what could go wrong, how bad by fixed rules, what is being done, and when it is next
 *  due for review. A model may suggest wording; it never sets a score. */
export function RisksPage() {
  const register = useApi(() => listRisks(), []);
  const controls = useApi(() => listControls(), []);
  const [view, setView] = useState<View>("current");
  const [cell, setCell] = useState<[number, number] | null>(null);
  const [open, setOpen] = useState<Risk | "new" | null>(null);

  if (register.error) return <div className="alert alert-error">{register.error}</div>;
  if (!register.data) return <p className="muted">Loading the register…</p>;
  const reg = register.data;
  const rows = cell
    ? reg.risks.filter((r) => r.status !== "CLOSED" && r[view].likelihood === cell[0] && r[view].impact === cell[1])
    : reg.risks;
  const saved = () => { setOpen(null); register.reload(); };

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Risks</h2>
          <p>What could go wrong, how bad it is, what you are doing about it, and who answers for it. The score is
            likelihood times impact, worked out by fixed rules. A model may suggest wording; it never sets a score, and a
            person signs what is saved.</p>
        </div>
        {reg.can_write_all && <button className="btn btn-primary" onClick={() => setOpen("new")}>Add a risk</button>}
      </div>

      <div className="risk-summary">
        <div><span>Open risks</span><strong>{reg.summary.open}</strong></div>
        {(["CRITICAL", "HIGH", "MEDIUM", "LOW"] as RiskBand[]).map((b) => (
          <div key={b}><span>{word(b)}</span><strong>{reg.summary.by_band[b]}</strong></div>
        ))}
        <div className={reg.summary.reviews_overdue > 0 ? "is-warn" : undefined}>
          <span>Reviews overdue</span><strong>{reg.summary.reviews_overdue}</strong>
        </div>
      </div>

      <div className="risk-top">
        <div>
          <div className="heat-toggle" role="group" aria-label="Which position to show">
            <button type="button" aria-pressed={view === "inherent"} onClick={() => setView("inherent")}>Before treatment</button>
            <button type="button" aria-pressed={view === "current"} onClick={() => setView("current")}>Where they are now</button>
          </div>
          <HeatMap cells={reg.heatmap[view]} bands={reg.bands} selected={cell} onPick={setCell} />
        </div>
        <div className="muted" style={{ fontSize: 13 }}>
          <p style={{ marginTop: 0 }}>Each square counts the open risks at that likelihood and impact. Click a square to list just those.
            "Where they are now" uses the position after treatment once someone has assessed it, and the starting
            position until then.</p>
          <p>Reviews follow the band: critical every 30 days, high 90, medium 180, low 365.</p>
        </div>
      </div>

      {cell && (
        <div className="risk-filter">
          Showing open risks at likelihood {cell[0]}, impact {cell[1]}. <button className="btn-link" onClick={() => setCell(null)}>Show all</button>
        </div>
      )}

      <table className="data-table static">
        <thead><tr><th>Risk</th><th>Before treatment</th><th>Now</th><th>Treatment</th><th>Status</th><th>Review</th><th /></tr></thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={7} className="muted">
              {reg.risks.length === 0
                ? (reg.can_write_all ? "No risks yet. Add the first one." : "No risks are recorded for you.")
                : "No open risks at that square."}
            </td></tr>
          )}
          {rows.map((r) => (
            <tr key={r.id} className={r.review_state === "OVERDUE" ? "risk-row-overdue" : undefined}
              style={r.status === "CLOSED" ? { opacity: 0.6 } : undefined}>
              <td className="risk-title-cell">
                <strong>{r.title}</strong>
                <span className="muted">{word(r.category)} · {r.owner_email || "no owner yet"}</span>
              </td>
              <td><Band band={r.inherent.band} score={r.inherent.score} /></td>
              <td>{r.residual ? <Band band={r.current.band} score={r.current.score} /> : <span className="muted">not assessed</span>}</td>
              <td>{r.treatment ? word(r.treatment) : <span className="muted">not decided</span>}</td>
              <td>{word(r.status)}</td>
              <td>
                {r.review_state === "OVERDUE" ? <span className="badge badge-open">Overdue</span> : REVIEW_LABEL[r.review_state]}
                {r.status !== "CLOSED" && r.next_review_date && <div className="muted" style={{ fontSize: 12 }}>due {r.next_review_date}</div>}
              </td>
              <td><button className="btn btn-sm" onClick={() => setOpen(r)}>{reg.can_write ? "Open" : "View"}</button></td>
            </tr>
          ))}
        </tbody>
      </table>

      {open && (
        <RiskDrawer key={open === "new" ? "new" : open.id} risk={open === "new" ? null : open} register={reg}
          controls={controls.data ?? []} onClose={() => setOpen(null)} onSaved={saved} />
      )}
    </div>
  );
}
