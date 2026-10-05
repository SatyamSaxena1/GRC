import data from "./samples.json";

// The demo document library. samples.json is the single source of truth: this
// renders it for the browser, and evaluation/samples.py renders the very same
// text for the model-reliability harness (their output is pinned together by
// the `golden` block in samples.json).

export type Sample = {
  id: string;
  title: string;
  artefact_type: string;
  upload_as?: string;       // declared type when the scenario is "filed under the wrong type"
  expect_status?: string;   // a status the scenario is *meant* to end in (e.g. NEEDS_REVIEW)
  filename: string;
  needs_model: boolean;
  body: string[];
  attrs: Record<string, unknown>;
  expect: Record<string, string>;
  story: string;
  watch: string[];
  while_waiting: string[];
  revises?: string;         // the sample this one is a corrected/newer version of
  base_of?: string;
  commitments?: Record<string, unknown>;
};

const SAMPLES = data.samples as unknown as Sample[];
export const listSamples = (): Sample[] => SAMPLES;
export const sampleById = (id: string): Sample | undefined => SAMPLES.find((s) => s.id === id);

// Hard-coded names: toLocaleDateString would differ by browser locale, and the
// Python renderer has to produce the identical string.
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
  "September", "October", "November", "December"];
const pad = (n: number) => String(n).padStart(2, "0");
const shifted = (today: Date, days: number) =>
  new Date(today.getFullYear(), today.getMonth(), today.getDate() + days);

/** {{date:±N}} -> "12 March 2026", {{iso:±N}} -> "2026-03-12", {{runid}} -> the run id. */
export function renderTokens(text: string, today: Date, runId: string): string {
  return text.replace(/\{\{([a-z]+(?::[+-]?\d+)?)\}\}/g, (_m, spec: string) => {
    const [kind, offset] = spec.split(":");
    if (kind === "runid") return runId;
    const d = shifted(today, Number(offset));
    return kind === "date"
      ? `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`
      : `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  });
}

// A fresh id per upload keeps the file's hash unique: the server answers 409 to
// "this exact file again", which is exactly what a presenter re-running a
// scenario would otherwise hit.
export const newRunId = (): string => Math.random().toString(36).slice(2, 8);

export type RenderedSample = { sample: Sample; text: string; filename: string; file: File };

export function renderSample(sample: Sample, runId = newRunId(), today = new Date()): RenderedSample {
  const text = renderTokens(sample.body.join("\n") + "\n", today, runId);
  const filename = renderTokens(sample.filename, today, runId);
  return { sample, text, filename, file: new File([text], filename, { type: "text/plain" }) };
}

export function downloadSample(sample: Sample): void {
  const { text, filename } = renderSample(sample);
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** What a presenter should expect, in a sentence, derived from the same rules-engine
 *  output the story is checked against (tests/test_demo_samples.py). */
export function expectedSummary(sample: Sample): string {
  if (sample.expect_status === "NEEDS_REVIEW") {
    return "It lands in Needs review, with a plain explanation of what the document really looks like.";
  }
  const counts: Record<string, number> = {};
  for (const verdict of Object.values(sample.expect)) counts[verdict] = (counts[verdict] ?? 0) + 1;
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const parts = ["PASS", "PARTIAL", "FAIL"]
    .filter((v) => counts[v])
    .map((v) => `${counts[v]} ${v.toLowerCase()}`);
  return `${total} clauses judged: ${parts.join(", ")}.`;
}

// Dev-only: the renderer must agree with evaluation/samples.py. Cheap enough to
// run on every load in development, absent from production builds.
if (import.meta.env.DEV) {
  const [y, m, d] = (data.golden.today as string).split("-").map(Number);
  for (const c of data.golden.cases as { token: string; text: string }[]) {
    const got = renderTokens(c.token, new Date(y, m - 1, d), "RUNID");
    console.assert(got === c.text, `demo sample renderer drifted: ${c.token} -> ${got}, expected ${c.text}`);
  }
}
