import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ApiError, listAiModels, listEvidence, uploadEvidence, uploadEvidenceVersion,
  type EvidenceSummary,
} from "../api/client";
import { downloadSample, expectedSummary, listSamples, renderSample, sampleById, type Sample } from "./samples";

const TYPE_LABEL: Record<string, string> = {
  POLICY: "Policy", SCAN_REPORT: "Scan report", REVIEW_RECORD: "Review record",
};
const label = (t: string) => TYPE_LABEL[t] ?? t;

/** The filename up to the run id, e.g. "demo-access-control-policy-" - how an
 *  uploaded copy of a sample is recognised later. */
const prefixOf = (s: Sample) => s.filename.split("{{runid}}")[0];

export default function DemoPanel({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const samples = useMemo(listSamples, []);
  const [selected, setSelected] = useState<Sample>(samples[0]);
  const [uploaded, setUploaded] = useState<EvidenceSummary[]>([]);
  const [modelUp, setModelUp] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showText, setShowText] = useState(false);

  useEffect(() => {
    listAiModels().then((m) => setModelUp(m.available)).catch(() => setModelUp(null));
    listEvidence({ lifecycle_status: "CURRENT" }).then(setUploaded).catch(() => setUploaded([]));
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // A sample that corrects an earlier one is best uploaded as a new *version* of
  // that earlier upload (that is the carry-forward story), when it is on file.
  const base = selected.revises ? sampleById(selected.revises) : undefined;
  const baseUpload = useMemo(() => {
    if (!base) return undefined;
    const prefix = prefixOf(base);
    // "demo-...-policy-" also prefixes "demo-...-policy-v2-": take the newest match.
    return uploaded.filter((e) => e.original_filename.startsWith(prefix))
      .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  }, [base, uploaded]);

  const rendered = useMemo(() => renderSample(selected, "preview"), [selected]);

  const upload = async (asVersion: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const { file } = renderSample(selected);          // fresh run id: never a duplicate of an earlier upload
      const type = selected.upload_as ?? selected.artefact_type;
      const result = asVersion && baseUpload
        ? await uploadEvidenceVersion(baseUpload.id, file, selected.upload_as)
        : await uploadEvidence(file, type, { description: "Demo guide sample" });
      onClose();
      navigate(`/evidence/${result.evidence_id ?? result.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? String(err.message) : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="demo-backdrop" onClick={onClose}>
      <div className="demo-panel" role="dialog" aria-modal="true" aria-label="Demo documents"
           onClick={(e) => e.stopPropagation()}>
        <header className="demo-panel__head">
          <div>
            <h2>Demo documents</h2>
            <p>One scenario per document. Each tells you what is going on, what to watch for, and what should happen.</p>
          </div>
          <button type="button" className="demo-x" aria-label="Close" onClick={onClose}>×</button>
        </header>

        {modelUp === false && (
          <div className="demo-warn">
            The AI model host looks unreachable right now. Uploads still work, but they will land in
            Needs review with no extracted values until it is back.
          </div>
        )}

        <div className="demo-body">
          <ul className="demo-list" aria-label="Scenarios">
            {samples.map((s, i) => (
              <li key={s.id}>
                <button type="button" className={s.id === selected.id ? "is-on" : ""}
                        onClick={() => { setSelected(s); setShowText(false); setError(null); }}>
                  <span className="demo-list__n">{i + 1}</span>
                  <span>
                    <strong>{s.title}</strong>
                    <small>{label(s.upload_as ? `${s.upload_as}` : s.artefact_type)}{s.upload_as ? " (wrongly filed)" : ""}</small>
                  </span>
                </button>
              </li>
            ))}
          </ul>

          <section className="demo-card" aria-live="polite">
            <h3>{selected.title}</h3>
            <h4>The scene</h4>
            <p>{selected.story}</p>
            <h4>What to watch for</h4>
            <ul>{selected.watch.map((w) => <li key={w}>{w}</li>)}</ul>
            <h4>What should happen</h4>
            <p>{expectedSummary(selected)}</p>
            {base && (
              <p className="demo-note">
                {baseUpload
                  ? <>Best uploaded as a new version of <code>{baseUpload.original_filename}</code>, so you see the history carry forward.</>
                  : <>Works best after <strong>{base.title}</strong> is already uploaded; it is meant to replace it.</>}
              </p>
            )}
            <p className="demo-fine">
              The AI only reads facts out of the document. Every verdict comes from fixed rules, so the same
              facts always give the same result.
            </p>

            {error && <div className="alert alert-error">{error}</div>}
            <div className="demo-actions">
              {base && baseUpload && (
                <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void upload(true)}>
                  {busy ? "Uploading…" : "Upload as new version"}
                </button>
              )}
              <button type="button" className={`btn ${base && baseUpload ? "" : "btn-primary"}`} disabled={busy}
                      onClick={() => void upload(false)}>
                {busy ? "Uploading…" : base && baseUpload ? "Upload as a separate document" : "Upload this document"}
              </button>
              <button type="button" className="btn" onClick={() => downloadSample(selected)}>Download</button>
              <button type="button" className="btn" onClick={() => setShowText((v) => !v)}>
                {showText ? "Hide text" : "Show text"}
              </button>
            </div>
            {showText && <pre className="demo-text">{rendered.text}</pre>}
          </section>
        </div>
      </div>
    </div>
  );
}
