import { useState } from "react";
import type { BulkTaskChange, TaskOwner } from "../api/client";

const PRIORITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];

/** Apply one change to every selected task. Fields left blank are not touched. */
export function BulkTaskBar({ count, owners, busy, error, onApply, onClear }: {
  count: number; owners: TaskOwner[]; busy: boolean; error: string | null;
  onApply: (change: BulkTaskChange) => void; onClear: () => void;
}) {
  const [owner, setOwner] = useState("");
  const [due, setDue] = useState("");
  const [priority, setPriority] = useState("");
  const change: BulkTaskChange = {};
  if (owner) change.owner_user_id = owner === "__none__" ? null : owner;
  if (due) change.due_at = `${due}T00:00:00Z`;
  if (priority) change.priority = priority;
  const nothing = Object.keys(change).length === 0;

  return (
    <div className="card" role="region" aria-label="Bulk task actions" style={{ position: "sticky", top: 0, zIndex: 2, marginBottom: 12 }}>
      <strong>{count} selected</strong>
      <div className="form-row" style={{ marginTop: 8 }}>
        <label>Assignee
          <select value={owner} onChange={(e) => setOwner(e.target.value)}>
            <option value="">Leave as is</option>
            <option value="__none__">Unassign</option>
            {owners.map((o) => <option key={o.id} value={o.id}>{o.email}</option>)}
          </select>
        </label>
        <label>Due date
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
        </label>
        <label>Priority
          <select value={priority} onChange={(e) => setPriority(e.target.value)}>
            <option value="">Leave as is</option>
            {PRIORITIES.map((p) => <option key={p}>{p}</option>)}
          </select>
        </label>
        <button className="btn btn-primary" disabled={busy || nothing} onClick={() => onApply(change)}>
          {busy ? "Applying…" : `Apply to ${count}`}
        </button>
        <button className="btn" disabled={busy} onClick={onClear}>Clear selection</button>
      </div>
      {error && <div className="alert alert-error" style={{ marginTop: 8 }}>{error}</div>}
    </div>
  );
}
