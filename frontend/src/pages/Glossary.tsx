import { useState } from "react";
import { listGlossary, type GlossaryTerm } from "../api/client";
import { useApi } from "../lib/useApi";
import { PageTour } from "../components/PageTour";

const TOUR_STEPS = [
  {
    title: "Every definition names its source",
    body: "A law or regulation outranks a standard, which outranks wording we wrote ourselves. The source line tells you which applies, so a disputed term is traceable to the document that settles it rather than just asserted.",
    target: ".glossary-list",
  },
  {
    title: "Search the term or the acronym",
    body: "People type MFA, not multi-factor authentication. Acronyms are indexed alongside the full term, and the search also looks inside definitions when nothing matches by name.",
    target: ".glossary-search",
  },
] as const;

const TAGS = ["", "platform", "iam", "data", "privacy", "pci", "audit", "risk", "standards", "ai"];

/** Which layer an entry came from — see ADR-015. Worth surfacing because the
 * three differ in who wrote the words: ours, NIST's, or a third party NIST
 * merely quoted. */
function layerLabel(t: GlossaryTerm): string {
  if (!t.imported) return "written for this product";
  return t.tags.includes("ai") ? "AI reference corpus" : "NIST reference";
}

export function GlossaryPage() {
  const [q, setQ] = useState("");
  const [tag, setTag] = useState("");
  const terms = useApi(() => listGlossary({ q, tag, limit: 200 }), [q, tag]);

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Glossary</h2>
          <p>What the words on screen mean, and which document says so.</p>
        </div>
        <PageTour id="glossary" steps={TOUR_STEPS} />
      </div>

      <div className="form-row glossary-search">
        <input
          placeholder="Search a term or acronym — MFA, PHI, SoA…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Search the glossary"
        />
        <select value={tag} onChange={(e) => setTag(e.target.value)} aria-label="Filter by topic">
          {TAGS.map((t) => (
            <option key={t} value={t}>{t || "All topics"}</option>
          ))}
        </select>
      </div>

      {terms.error && <div className="alert alert-error">{terms.error}</div>}
      {terms.data?.length === 0 && (
        <div className="card empty-state">
          Nothing matches “{q}” in either the terms written for this product or the NIST reference
          corpus.
        </div>
      )}

      {!q && !tag && (
        <p className="muted" style={{ fontSize: 12, margin: "0 0 10px" }}>
          Showing the vocabulary this product uses. Search to reach the reference corpora as
          well — about 4,200 more definitions from NIST's security and AI glossaries.
        </p>
      )}

      <div className="glossary-list">
        {terms.data?.map((t) => (
          <div key={t.term} className="card glossary-entry">
            <div className="glossary-entry-head">
              <strong>{t.term}</strong>
              {t.aliases.length > 0 && <span className="muted">{t.aliases.join(" · ")}</span>}
            </div>
            <p>{t.definition}</p>
            {t.note && <p className="glossary-note">{t.note}</p>}
            <div className="glossary-entry-foot">
              {t.source_url.startsWith("http") ? (
                <a href={t.source_url} target="_blank" rel="noopener noreferrer">{t.source} ↗</a>
              ) : (
                <span>{t.source}</span>
              )}
              <span className="muted">
                {layerLabel(t)}
                {t.tags.length > 0 && ` · ${t.tags.join(" · ")}`}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
