import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { askAssistant, getAssistantStatus, type AssistantTurn } from "../api/client";

// "Ask the workspace": a chat panel on every signed-in page, backed by POST /assistant/ask
// (app/routers/assistant.py). The model only reads, through the caller's own scoped API,
// and never decides a verdict. Any button in the app can open it with a question already
// asked: call askAI("…") (an event, so no prop-drilling through every page).
const ASK_EVENT = "grc:ask";
export function askAI(question: string): void {
  window.dispatchEvent(new CustomEvent(ASK_EVENT, { detail: question }));
}

/** Small models answer in markdown even when asked not to: show bullets and emphasis as
 *  plain text rather than raw asterisks and backticks (screen readers read those aloud). */
const plain = (text: string) =>
  text.replace(/^(\s*)[*-]\s+/gm, "$1• ").replace(/\*\*(.+?)\*\*/g, "$1").replace(/`([^`]+)`/g, "$1");

function suggestionsFor(path: string): string[] {
  if (path.startsWith("/evidence/")) return [
    "Summarise this evidence and its verdicts in plain words.",
    "Which facts on this document should a person double-check?",
    "What single change to this document would close the most gaps?",
  ];
  if (path.startsWith("/gaps")) return ["Which open gaps matter most, and why?", "Group my open gaps by what's missing."];
  if (path.startsWith("/tasks")) return ["What should I work on first?", "Which tasks are overdue or unassigned?"];
  if (path.startsWith("/controls")) return ["Which controls still need evidence?", "Explain the controls that are only partly met."];
  if (path.startsWith("/glossary")) return ["What's the difference between a control and a requirement?"];
  if (path.startsWith("/ai-compliance")) return ["How ready are we for the NIST AI RMF GOVERN function?"];
  return ["What needs my attention today?", "Which evidence files have the most gaps?", "Explain our compliance status in plain words."];
}

export function AssistantPanel() {
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<AssistantTurn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<{ available: boolean; model: string } | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const log = useRef<HTMLDivElement>(null);

  const send = async (question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    const history = turns;
    setTurns([...history, { role: "user", content: q }]);
    setDraft("");
    setBusy(true);
    setError(null);
    try {
      const res = await askAssistant(q, pathname, history);
      setTurns((t) => [...t, { role: "assistant", content: plain(res.answer) }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The assistant could not answer.");
    } finally {
      setBusy(false);
    }
  };

  const show = () => {
    opener.current = document.activeElement as HTMLElement | null;
    setOpen(true);
  };
  const hide = () => {
    setOpen(false);
    opener.current?.focus();
  };

  useEffect(() => {
    const onAsk = (e: Event) => {
      show();
      void send(String((e as CustomEvent).detail ?? ""));
    };
    window.addEventListener(ASK_EVENT, onAsk);
    return () => window.removeEventListener(ASK_EVENT, onAsk);
  });

  useEffect(() => {
    if (!open) return;
    input.current?.focus();
    getAssistantStatus().then(setStatus).catch(() => setStatus({ available: false, model: "" }));
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && hide();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight });
  }, [turns, busy]);

  return (
    <>
      <button type="button" className="assistant-fab" aria-expanded={open} aria-controls="assistant-panel"
        onClick={() => (open ? hide() : show())}>
        {open ? "Close assistant" : "Ask AI"}
      </button>
      {open && (
        <section id="assistant-panel" className="assistant" role="dialog" aria-modal="false" aria-labelledby="assistant-title">
          <header className="assistant__head">
            <h2 id="assistant-title">Ask the workspace</h2>
            <span className="assistant__model" role="status">
              {status === null ? "Checking model…" : status.available ? `Model: ${status.model}` : "Model offline"}
            </span>
            <button type="button" className="assistant__close" onClick={hide} aria-label="Close assistant">×</button>
          </header>
          <p className="assistant__note">Answers come only from what you can already see. The AI explains; verdicts are decided by fixed rules.</p>
          <div className="assistant__log" ref={log} role="log" aria-live="polite" aria-label="Conversation">
            {turns.length === 0 && (
              <div className="assistant__suggest">
                <p>Try asking:</p>
                {suggestionsFor(pathname).map((s) => (
                  <button type="button" key={s} onClick={() => void send(s)}>{s}</button>
                ))}
              </div>
            )}
            {turns.map((t, i) => (
              <div key={i} className={`assistant__msg assistant__msg--${t.role}`}>
                <span className="sr-only">{t.role === "user" ? "You asked:" : "Assistant:"}</span>
                {t.content}
              </div>
            ))}
            {busy && <div className="assistant__msg assistant__msg--assistant">Looking through your workspace…</div>}
            {error && <div className="alert alert-error" role="alert">{error}</div>}
          </div>
          <form className="assistant__form" onSubmit={(e) => { e.preventDefault(); void send(draft); }}>
            <label htmlFor="assistant-input" className="sr-only">Your question</label>
            <textarea id="assistant-input" ref={input} rows={2} value={draft} maxLength={2000}
              placeholder="Ask about your evidence, gaps, tasks or frameworks…"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(draft); } }} />
            <button type="submit" className="btn btn-primary" disabled={busy || !draft.trim()}>Ask</button>
          </form>
          {turns.length > 0 && (
            <button type="button" className="assistant__clear" onClick={() => { setTurns([]); setError(null); }}>
              Start a new conversation
            </button>
          )}
        </section>
      )}
    </>
  );
}

/** A small "Ask AI" button for any page: opens the panel with this question already asked. */
export function AskAIButton({ question, label = "Ask AI" }: { question: string; label?: string }) {
  return (
    <button type="button" className="btn ask-ai-btn" onClick={(e) => { e.stopPropagation(); askAI(question); }} title={question}>
      ✦ {label}
    </button>
  );
}
