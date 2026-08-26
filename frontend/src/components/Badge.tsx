// Evidence lifecycle statuses that mean "the model or a background job is
// actively working on this right now" — badges for these pulse, so a value
// that's genuinely mid-change looks different from one that's settled.
const PROCESSING = new Set(["SCANNING", "EXTRACTING", "ANALYZING", "EVALUATING"]);

export function Badge({ value }: { value: string | null | undefined }) {
  const label = value ?? "—";
  const processing = PROCESSING.has(label);
  const cls = `badge badge-${label.toLowerCase().replace(/\s+/g, "_")}${processing ? " processing" : ""}`;
  return <span className={cls}>{label}</span>;
}
