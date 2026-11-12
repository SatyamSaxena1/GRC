import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { REVIEWED, SOC2_LESSONS } from "../lib/soc2Lessons";

/** Public lessons (ADR-065): free to read, no sign-in, nothing recorded. The practice questions are checked in the
 *  browser against the answers on the page; they grade nothing and change nothing. */
export function LearnPage() {
  const { slug } = useParams();
  const at = Math.max(0, SOC2_LESSONS.findIndex((l) => l.slug === slug));
  const lesson = SOC2_LESSONS[at];
  const next = SOC2_LESSONS[at + 1];
  const [picked, setPicked] = useState<Record<string, number>>({});

  return (
    <div style={{ maxWidth: 760, margin: "0 auto", padding: "24px 16px" }}>
      <p className="muted" style={{ margin: 0 }}>Free lessons · no account needed</p>
      <h1 style={{ margin: "4px 0 12px" }}>SOC 2 in plain words</h1>
      {!REVIEWED && <div className="alert alert-info">Draft: these lessons are still being reviewed.</div>}
      <nav style={{ display: "flex", gap: 6, flexWrap: "wrap", margin: "12px 0" }}>
        {SOC2_LESSONS.map((l, i) => (
          <Link key={l.slug} to={`/learn/soc-2/${l.slug}`} className={`btn btn-sm${i === at ? " btn-primary" : ""}`}>
            {i + 1}. {l.title}
          </Link>
        ))}
      </nav>
      <article className="card">
        <h2 style={{ marginTop: 0 }}>{at + 1}. {lesson.title}</h2>
        <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.6 }}>{lesson.body}</div>
      </article>
      <h3>Try it</h3>
      {lesson.questions.map((q, qi) => {
        const key = `${lesson.slug}-${qi}`;
        const p = picked[key];
        return (
          <fieldset key={key} className="card" style={{ marginBottom: 10 }}>
            <legend style={{ fontSize: 13 }}>Situation {qi + 1}</legend>
            <p style={{ marginTop: 0 }}>{q.scenario}</p>
            {q.choices.map((c, ci) => (
              <label key={ci} style={{ display: "block" }}>
                <input type="radio" name={key} checked={p === ci} disabled={p !== undefined}
                  onChange={() => setPicked({ ...picked, [key]: ci })} /> {c}
              </label>
            ))}
            {p !== undefined && (
              <p className="stat-sub">
                <span className={`badge ${p === q.answer ? "badge-pass" : "badge-fail"}`}>{p === q.answer ? "Right" : "Not quite"}</span>{" "}
                {p !== q.answer && <>The answer is “{q.choices[q.answer]}”. </>}{q.why}
              </p>
            )}
          </fieldset>
        );
      })}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 16, gap: 12, flexWrap: "wrap" }}>
        {next ? <Link className="btn btn-primary" to={`/learn/soc-2/${next.slug}`}>Next: {next.title}</Link> : <span />}
        <span className="muted">Ready to collect the evidence? <Link to="/login">Start free</Link></span>
      </div>
    </div>
  );
}
