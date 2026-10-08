import { useState } from "react";
import {
  ApiError, decideException, listExceptions, listGaps, requestException,
  type GapException, type GapRow,
} from "../api/client";
import { useApi } from "../lib/useApi";
import { Badge } from "./Badge";

const STATE_HELP: Record<GapException["state"], string> = {
  ACTIVE: "In force: the gap is waived until the expiry date.",
  REQUESTED: "Waiting for an auditor on the engagement to decide.",
  REJECTED: "An auditor declined it.",
  REVOKED: "Withdrawn.",
  EXPIRED: "Past its expiry date; the gap counts again.",
  RULE_CHANGED: "The rule it was written against has changed since; request it again if still needed.",
  VALUE_CHANGED: "The gap's value changed since it was accepted; the old acceptance does not cover it.",
};

const inDays = (n: number) => new Date(Date.now() + n * 86400000).toISOString().slice(0, 10);

/** Accepted gaps for one control (ADR-021). The auditee requests an exception for an open gap;
 *  an auditor on the engagement approves or rejects it; either side can revoke it. The server
 *  decides whether one still applies (expiry, rule or value change), so this only shows its answer. */
export function GapExceptions({ framework, clause, isAuditor, canRequest }: {
  framework: string; clause: string; isAuditor: boolean; canRequest: boolean;
}) {
  const gaps = useApi(() => listGaps("OPEN"), []);
  const exceptions = useApi(() => listExceptions(), []);
  const [formFor, setFormFor] = useState<string | null>(null);
  const [form, setForm] = useState({ justification: "", compensating_control: "", expires: inDays(90) });
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mine = (g: GapRow) => g.framework === framework && g.clause === clause;
  const openGaps = (gaps.data ?? []).filter(mine);
  const rows = (exceptions.data ?? []).filter((e) => e.framework === framework && e.clause === clause);
  if (!openGaps.length && !rows.length) return null;

  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      setFormFor(null); setNote("");
      gaps.reload(); exceptions.reload();
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    }
  };

  return (
    <>
      <div className="section-title">Exceptions</div>
      <div className="card" data-tour="gap-exceptions">
        <p className="muted" style={{ margin: "0 0 10px", fontSize: 12 }}>
          An accepted gap stays open. An exception waives it only while it is approved, unexpired, and the rule
          and the gap's value are unchanged.
        </p>
        {error && <p className="error">{error}</p>}

        {openGaps.map((g) => (
          <div key={g.id} className="attr-row" style={{ alignItems: "flex-start" }}>
            <div style={{ flex: 1 }}>
              <strong>{g.attribute.replace(/_/g, " ")}</strong>
              <div className="muted" style={{ fontSize: 12 }}>{g.detail}</div>
            </div>
            <div>
              {g.waived && g.exception ? (
                <span><Badge value="WAIVED" /> <span className="muted" style={{ fontSize: 12 }}>until {new Date(g.exception.expires_at).toLocaleDateString()}</span></span>
              ) : canRequest && formFor !== g.id ? (
                <button type="button" className="btn btn-sm" onClick={() => setFormFor(g.id)}>Request exception</button>
              ) : null}
            </div>
            {formFor === g.id && (
              <form style={{ width: "100%", marginTop: 8 }} onSubmit={(e) => {
                e.preventDefault();
                run(() => requestException(g.id, {
                  justification: form.justification, compensating_control: form.compensating_control,
                  expires_at: new Date(form.expires + "T23:59:59Z").toISOString(),
                }));
              }}>
                <label>Why accept this gap for now? (at least 20 characters)</label>
                <textarea required minLength={20} rows={2} value={form.justification}
                          onChange={(e) => setForm({ ...form, justification: e.target.value })} />
                <label>Compensating control (optional)</label>
                <input value={form.compensating_control}
                       onChange={(e) => setForm({ ...form, compensating_control: e.target.value })} />
                <label>Expires on (at most 180 days)</label>
                <input type="date" required min={inDays(1)} max={inDays(180)} value={form.expires}
                       onChange={(e) => setForm({ ...form, expires: e.target.value })} />
                <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                  <button type="submit" className="btn btn-primary btn-sm">Send to auditor</button>
                  <button type="button" className="btn btn-sm" onClick={() => setFormFor(null)}>Cancel</button>
                </div>
              </form>
            )}
          </div>
        ))}

        {rows.map((e) => (
          <div key={e.id} className="attr-row" style={{ alignItems: "flex-start", borderTop: "1px solid var(--border)", paddingTop: 8 }}>
            <div style={{ flex: 1 }}>
              <div><Badge value={e.state} /> <strong>{e.attribute.replace(/_/g, " ")}</strong>
                {e.actual_value != null && <span className="muted"> = {e.actual_value}</span>}</div>
              <div style={{ fontSize: 13 }}>{e.justification}</div>
              {e.compensating_control && <div className="muted" style={{ fontSize: 12 }}>Compensating control: {e.compensating_control}</div>}
              {e.same_rule?.miscalibration_suspected && (e.status === "REQUESTED" || e.status === "APPROVED") && (
                <div className="alert alert-warning" style={{ fontSize: 12, margin: "4px 0" }}>
                  This rule has {e.same_rule.open} open and {e.same_rule.ended} past exception(s) here. Repeated
                  exceptions usually mean the rule is miscalibrated, not that the risk is acceptable: review the
                  rule before {e.status === "REQUESTED" ? "approving" : "renewing"}.
                </div>
              )}
              <div className="muted" style={{ fontSize: 12 }}>
                {STATE_HELP[e.state]} Requested by {e.requested_by}; expires {new Date(e.expires_at).toLocaleDateString()}
                {e.decided_by && <>; {e.status.toLowerCase()} by {e.decided_by}{e.decision_note && ` ("${e.decision_note}")`}</>}.
              </div>
            </div>
            {(e.status === "REQUESTED" || e.status === "APPROVED") && (isAuditor || canRequest) && (
              <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 220 }}>
                <input placeholder="Note (required)" value={note} onChange={(ev) => setNote(ev.target.value)} />
                <div style={{ display: "flex", gap: 6 }}>
                  {isAuditor && e.status === "REQUESTED" && (<>
                    <button type="button" className="btn btn-primary btn-sm" disabled={!note}
                            onClick={() => run(() => decideException(e.id, "approve", note))}>Approve</button>
                    <button type="button" className="btn btn-sm" disabled={!note}
                            onClick={() => run(() => decideException(e.id, "reject", note))}>Reject</button>
                  </>)}
                  <button type="button" className="btn btn-sm" disabled={!note}
                          onClick={() => run(() => decideException(e.id, "revoke", note))}>Revoke</button>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
