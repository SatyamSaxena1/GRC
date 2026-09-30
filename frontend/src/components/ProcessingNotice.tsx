import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { listEvidence } from "../api/client";
import { useApi } from "../lib/useApi";
import { Spinner } from "./Spinner";

const TERMINAL = new Set(["READY", "FAILED", "NEEDS_REVIEW"]);

/**
 * Gaps, tasks and controls only exist once a document's processing finishes, so a
 * list that says "nothing here" while one is still running is telling a small lie.
 * This says what is actually happening, polls until it's done, and then asks the
 * page to reload itself so the empty list fills in without a manual refresh.
 * Renders nothing when nothing is in flight (or the caller can't list evidence).
 */
export function ProcessingNotice({ onSettled }: { onSettled?: () => void }) {
  const evidence = useApi(() => listEvidence({ lifecycle_status: "CURRENT" }), []);
  const busy = (evidence.data ?? []).filter((e) => !TERMINAL.has(e.status));
  const wasBusy = useRef(false);

  useEffect(() => {
    if (busy.length > 0) {
      wasBusy.current = true;
      const timer = setInterval(evidence.reload, 3000);
      return () => clearInterval(timer);
    }
    if (wasBusy.current && !evidence.loading) {
      wasBusy.current = false;
      onSettled?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy.length, evidence.loading]);

  if (busy.length === 0) return null;
  return (
    <div className="alert alert-info" style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <Spinner size={14} />
      <span>
        <strong>{busy.length} document{busy.length > 1 ? "s are" : " is"} still being processed</strong> — results appear here
        as soon as {busy.length > 1 ? "they finish" : "it finishes"}.{" "}
        <Link to={`/evidence/${busy[0].id}`}>Watch {busy[0].original_filename}</Link>
      </span>
    </div>
  );
}
