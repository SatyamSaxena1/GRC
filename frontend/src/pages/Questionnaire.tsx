import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, answerQuestion, type QuestionnaireAnswer } from "../api/client";

const LABEL: Record<QuestionnaireAnswer["status"], string> = {
  YES: "Yes", PARTIAL: "Partly", NO: "Not currently", NOT_EVIDENCED: "Not yet evidenced",
};
const MAX_QUESTIONS = 40;

type Row = { question: string; result?: QuestionnaireAnswer; error?: string };

const csvCell = (v: string) => `"${v.replace(/"/g, '""')}"`;

/** Draft answers to a customer's security questionnaire from this workspace's own controls (ADR-040).
 *  Each answer's status comes from your verdicts; a model only words it. They are drafts: review before sending. */
export function QuestionnairePage() {
  const [text, setText] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    const questions = text.split("\n").map((q) => q.trim()).filter((q) => q.length >= 3).slice(0, MAX_QUESTIONS);
    setRows(questions.map((question) => ({ question })));
    setBusy(true);
    for (let i = 0; i < questions.length; i++) {
      let next: Row;
      try {
        next = { question: questions[i], result: await answerQuestion(questions[i]) };
      } catch (err) {
        next = { question: questions[i], error: err instanceof ApiError ? String(err.detail) : (err as Error).message };
      }
      setRows((prev) => prev.map((r, j) => (j === i ? next : r)));
    }
    setBusy(false);
  };

  const download = () => {
    const lines = [["Question", "Status", "Answer", "Evidence"].map(csvCell).join(",")];
    for (const r of rows) {
      if (!r.result) continue;
      const cites = r.result.controls.map((c) => `${c.framework} ${c.clause} (${c.verdict})`).join("; ");
      lines.push([r.question, LABEL[r.result.status], r.result.answer, cites].map(csvCell).join(","));
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([lines.join("\r\n")], { type: "text/csv" }));
    a.download = "questionnaire-draft.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Questionnaires</h2>
          <p>Paste a customer's security questions, one per line. Each answer is drafted from your own controls.
            The status comes from your verdicts, and a model only words it. Review every draft before you send it.</p>
        </div>
      </div>

      <div className="card">
        <label htmlFor="questions">Questions (up to {MAX_QUESTIONS}, one per line)</label>
        <textarea id="questions" rows={6} value={text} onChange={(e) => setText(e.target.value)}
          placeholder={"Do you require multi-factor authentication for remote access?\nDo you keep audit logs?\nIs customer data encrypted at rest?"} />
        <div style={{ marginTop: 8 }}>
          <button className="btn btn-primary" disabled={busy || !text.trim()} onClick={run}>
            {busy ? "Answering…" : "Draft answers"}
          </button>{" "}
          <button className="btn" disabled={busy || !rows.some((r) => r.result)} onClick={download}>Download CSV</button>
        </div>
      </div>

      {rows.length > 0 && (
        <table className="data-table static" style={{ marginTop: 16 }}>
          <thead><tr><th>Question</th><th>Status</th><th>Draft answer</th><th>Based on</th></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td>{r.question}</td>
                <td>{r.result ? LABEL[r.result.status] : r.error ? "Error" : "…"}</td>
                <td>{r.error ?? r.result?.answer ?? "Working…"}</td>
                <td>
                  {r.result?.controls.map((c) => (
                    <div key={c.control_id}>
                      <Link to={`/controls/${c.control_id}`}>{c.framework} {c.clause}</Link>
                      <span className="muted"> {c.verdict}{c.reviewed_by_auditor ? ", auditor reviewed" : ""}</span>
                    </div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
