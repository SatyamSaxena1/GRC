import { useState } from "react";
import { replayLink, type Provenance, type ReplayResult } from "../api/client";

const short = (h: string | null) => (h ? h.slice(0, 10) : "—");

const STATUS_TEXT: Record<ReplayResult["status"], string> = {
  REPRODUCED: "Reproduced: the same rule over the same inputs gives the same verdict.",
  DIFFERS: "Differs: re-running the recorded rule no longer gives the recorded result.",
  NOT_RECORDED: "Judged before provenance was recorded, so it cannot be replayed.",
  RULE_BODY_INVALID: "The stored rule no longer matches its fingerprint — it was edited.",
};

/** What produced this verdict, and a button that proves it (ADR-022). */
export function VerdictProvenance({ evidenceId, linkId, provenance }: {
  evidenceId: string; linkId: string; provenance: Provenance;
}) {
  const [result, setResult] = useState<ReplayResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const replay = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await replayLink(evidenceId, linkId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
      <span title={`rule ${provenance.rule_hash}\nevaluation ${provenance.evaluation_hash}`}>
        Rules <span className="mono">{short(provenance.rule_hash)}</span> · engine {provenance.engine_version} ·
        build <span className="mono">{short(provenance.build_id)}</span>
        {provenance.as_of && <> · judged as of {provenance.as_of}</>}
      </span>
      {provenance.rules_changed_since && (
        <span className="badge badge-rule_changed" style={{ marginLeft: 6 }}>rules changed since</span>
      )}{" "}
      <button type="button" className="btn btn-sm" onClick={replay} disabled={busy}>
        {busy ? "Replaying…" : "Replay"}
      </button>
      {error && <div className="alert alert-error">{error}</div>}
      {result && (
        <div style={{ marginTop: 4 }}>
          <span className={`badge badge-${result.status === "REPRODUCED" ? "pass" : "fail"}`}>
            {result.status.toLowerCase().replace("_", " ")}
          </span>{" "}
          {STATUS_TEXT[result.status]}
          {result.rules_changed_since && result.under_current_rules && (
            <> Today's rules would say <strong>{result.under_current_rules.verdict}</strong>.</>
          )}
        </div>
      )}
    </div>
  );
}
