// Shared by the evidence map page and its lazily loaded three.js scene, kept
// apart so importing these never pulls three.js into the main bundle.

export type GraphNode =
  | { kind: "framework"; id: string; label: string }
  | { kind: "control"; id: string; label: string; framework: string; verdict: string | null }
  | { kind: "evidence"; id: string; label: string; links: number };
export type GraphEdge = { from: string; to: string; verdict: string };

export const VERDICT_COLOR: Record<string, string> = {
  PASS: "#16a34a", PARTIAL: "#d97706", FAIL: "#dc2626", NONE: "#6b7280",
};
