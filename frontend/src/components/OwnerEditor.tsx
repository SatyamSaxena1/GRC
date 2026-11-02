import { useState } from "react";
import { addControlOwner, ApiError, listTaskOwners, removeControlOwner } from "../api/client";
import { useApi } from "../lib/useApi";

/** Who owns a control, with add and remove for an organisation admin. Adding can also hand the
 *  control's open, unassigned tasks to the new owner. */
export function OwnerEditor({ controlId, ownerIds, ownerEmails, canEdit, onChanged }: {
  controlId: string; ownerIds: string[]; ownerEmails: string[]; canEdit: boolean; onChanged: () => void;
}) {
  const users = useApi(() => (canEdit ? listTaskOwners() : Promise.resolve([])), [canEdit]);
  const [pick, setPick] = useState("");
  const [withTasks, setWithTasks] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try { await fn(); setPick(""); onChanged(); }
    catch (err) { setError(err instanceof ApiError ? String(err.detail) : (err as Error).message); }
    finally { setBusy(false); }
  };

  if (!canEdit) return <span className="meta-value">{ownerEmails.length ? ownerEmails.join(", ") : "Unassigned"}</span>;
  const candidates = (users.data ?? []).filter((u) => !ownerIds.includes(u.id));
  return (
    <span className="meta-value">
      {ownerEmails.length === 0 && <span className="muted">Unassigned </span>}
      {ownerEmails.map((email, i) => (
        <span key={ownerIds[i]} className="badge" style={{ marginRight: 4 }}>
          {email}{" "}
          <button type="button" className="btn-link" aria-label={`Remove ${email} as owner`} disabled={busy}
                  onClick={() => act(() => removeControlOwner(controlId, ownerIds[i]))}>✕</button>
        </span>
      ))}
      {candidates.length > 0 && (
        <span className="form-row" style={{ display: "inline-flex", gap: 6, marginTop: 4 }}>
          <select aria-label="Add an owner" value={pick} onChange={(e) => setPick(e.target.value)}>
            <option value="">Add an owner…</option>
            {candidates.map((u) => <option key={u.id} value={u.id}>{u.email}</option>)}
          </select>
          <label style={{ fontSize: 12 }}>
            <input type="checkbox" checked={withTasks} onChange={(e) => setWithTasks(e.target.checked)} /> hand over open tasks
          </label>
          <button className="btn btn-sm" disabled={!pick || busy} onClick={() => act(() => addControlOwner(controlId, pick, withTasks))}>Add</button>
        </span>
      )}
      {error && <span className="alert alert-error" role="alert" style={{ display: "block" }}>{error}</span>}
    </span>
  );
}
