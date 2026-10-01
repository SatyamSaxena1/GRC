import { useEffect, useRef, useState } from "react";
import { getEvidenceFile } from "../api/client";

type Props = { evidenceId: string; filename?: string; page?: number | null; quote?: string | null };

const MAX_TEXT_CHARS = 200_000;

/** The uploaded file, next to the facts read from it. PDFs and images use the browser's own
 * viewer (a PDF jumps to the cited page); plain text is shown with the cited quote highlighted;
 * anything else is offered as a download. The file comes from /evidence/{id}/file, which only
 * serves types a browser can render without running anything the uploader wrote. */
export function DocumentViewer({ evidenceId, filename, page, quote }: Props) {
  const [blob, setBlob] = useState<Blob | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mark = useRef<HTMLElement>(null);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    setBlob(null); setUrl(null); setText(null); setError(null);
    getEvidenceFile(evidenceId)
      .then(async (b) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(b);
        setBlob(b);
        setUrl(objectUrl);
        if (b.type.startsWith("text/plain")) setText((await b.text()).slice(0, MAX_TEXT_CHARS));
      })
      .catch(() => !cancelled && setError("The file isn't available to view."));
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [evidenceId]);

  useEffect(() => { mark.current?.scrollIntoView({ block: "center" }); }, [quote, text]);

  if (error) return <p className="muted">{error}</p>;
  if (!blob || !url) return <p className="muted">Loading document…</p>;

  const download = <a className="btn-link" href={url} download={filename || "evidence"}>Download {filename || "file"}</a>;

  if (blob.type === "application/pdf") {
    return (
      <>
        <iframe key={page ?? 0} className="doc-frame" title="Uploaded document" src={`${url}#page=${page ?? 1}`} />
        <div>{download}</div>
      </>
    );
  }
  if (blob.type.startsWith("image/")) {
    return <><img className="doc-image" src={url} alt={filename || "Uploaded evidence"} /><div>{download}</div></>;
  }
  if (text !== null) {
    const at = quote ? text.indexOf(quote) : -1;
    return (
      <>
        <pre className="doc-text">
          {at < 0 ? text : (
            <>{text.slice(0, at)}<mark ref={mark}>{quote}</mark>{text.slice(at + (quote as string).length)}</>
          )}
        </pre>
        <div>{download}</div>
      </>
    );
  }
  return <p className="muted">This file type can't be previewed here. {download}</p>;
}
