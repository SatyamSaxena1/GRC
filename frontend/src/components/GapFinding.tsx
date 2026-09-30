import type { Gap } from "../api/client";
import { humanize, prettyValue } from "../lib/format";

/** One gap as a sentence a person can act on. Wording follows the gap's kind, so
 * "missing" never reads like a wrong value and a wrong value shows found → needs. */
export function GapFinding({ gap }: { gap: Pick<Gap, "kind" | "attribute" | "detail" | "actual_value" | "required_value"> }) {
  return (
    <span className="gap-line">
      <strong>{humanize(gap.attribute)}</strong>
      {gap.kind === "MISSING_ATTRIBUTE" && <span> — not stated in the document.</span>}
      {gap.kind === "DELTA" && (
        <span className="gap-delta">
          <span className="found">found {prettyValue(gap.actual_value)}</span>
          <span aria-hidden="true">→</span>
          <span className="needs">needs {prettyValue(gap.required_value)}</span>
        </span>
      )}
      {gap.kind !== "MISSING_ATTRIBUTE" && gap.kind !== "DELTA" && <span> — {gap.detail}</span>}
    </span>
  );
}
