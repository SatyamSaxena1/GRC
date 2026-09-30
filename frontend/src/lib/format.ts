// Turns the backend's raw field values into wording a person can act on. Shared by
// the evidence page and the gaps queue so the same gap never reads two ways.

const ACRONYMS = new Set(["mfa", "ip"]); // the only ones content-pack attribute names use today

export const humanize = (name: string) => {
  const t = name.split("_").map((w) => (ACRONYMS.has(w) ? w.toUpperCase() : w)).join(" ");
  return t.charAt(0).toUpperCase() + t.slice(1);
};

// Gap values arrive as Python reprs (e.g. "['remote access', 'admin']"); show them as prose.
export const prettyValue = (v: unknown): string => {
  if (v === null || v === undefined || v === "") return "—";
  if (Array.isArray(v)) return v.map(String).join(", ");
  const t = String(v);
  return /^\[.*\]$/.test(t) ? t.slice(1, -1).replace(/['"]/g, "").replace(/,\s*/g, ", ") : t;
};

const BOUND: Record<string, string> = {
  ">=": "be at least", "<=": "be at most", ">": "be more than", "<": "be less than", "==": "be exactly", "!=": "not be",
};

/** The requirement half of a check, phrased to follow "must" — "be at least 12",
 * "include remote access". (A plain presence check has no bound; callers word that
 * case themselves.) */
export function describeBound(operator: string, expected: unknown): string {
  if (operator === "contains_all") return `include ${prettyValue(expected)}`;
  if (operator === "one_of") return `be one of ${prettyValue(expected)}`;
  return `${BOUND[operator] ?? operator} ${prettyValue(expected)}`;
}
