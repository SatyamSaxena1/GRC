import { useEffect, useState, type ReactNode } from "react";
import { listGlossary, type GlossaryTerm } from "../api/client";
import { Hint } from "./Hint";

/** One request for the curated glossary, shared by every <Term> on every page.
 * Fetching per-term on hover would be N round trips for ~20KB — and it would
 * only start on hover, exactly when the user is waiting.
 *
 * Curated only, deliberately: an empty query returns the ~70 hand-written
 * entries rather than the ~3.9k imported NIST corpus, which would be 1.5MB
 * downloaded to annotate a handful of words. Tooltips mark product vocabulary;
 * the imported corpus is for searching on the glossary page. */
let cache: Promise<Map<string, GlossaryTerm>> | null = null;

function glossary(): Promise<Map<string, GlossaryTerm>> {
  cache ??= listGlossary({ limit: 200 })
    .then((rows) =>
      new Map(
        rows.flatMap((r) => [r.term, ...r.aliases].map((n) => [n.toLowerCase(), r] as const)),
      ),
    )
    // A missing glossary must never break a page it only annotates.
    .catch(() => new Map<string, GlossaryTerm>());
  return cache;
}

/** Marks a word the product can define, and reveals the definition on hover or
 * keyboard focus. An unknown term renders as plain text rather than a dead
 * underline, so wrapping a word is safe before its entry exists. */
export function Term({ name, children }: { name?: string; children: ReactNode }) {
  const key = (name ?? String(children)).trim().toLowerCase();
  const [entry, setEntry] = useState<GlossaryTerm | null>(null);

  useEffect(() => {
    let live = true;
    void glossary().then((m) => {
      if (live) setEntry(m.get(key) ?? null);
    });
    return () => {
      live = false;
    };
  }, [key]);

  if (!entry) return <>{children}</>;

  return (
    <span className="term" tabIndex={0} role="button" aria-label={`${entry.term}: ${entry.definition}`}>
      {children}
      <Hint>
        <strong>{entry.term}</strong>
        <span className="term-def">{entry.definition}</span>
        <span className="term-source">{entry.source}</span>
      </Hint>
    </span>
  );
}
