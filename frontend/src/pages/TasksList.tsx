import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getTask, listTaskOwners, listTasks, updateTask, type TaskRow } from "../api/client";
import { useApi } from "../lib/useApi";
import { DataTable, type Column } from "../components/DataTable";
import { Badge } from "../components/Badge";
import { useSession } from "../lib/session";

const STATUSES = ["", "OPEN", "DONE"];
const PRIORITIES = ["", "LOW", "MEDIUM", "HIGH", "CRITICAL"];

export function TasksListPage() {
  const { identity } = useSession();
  const [status, setStatus] = useState("OPEN");
  const [priority, setPriority] = useState("");
  const [owner, setOwner] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<TaskRow | null>(null);
  const owners = useApi(() => listTaskOwners(), []);
  const allTasks = useApi(() => listTasks(), []);
  const tasks = useApi(
    () => listTasks({ status: status || undefined, priority: priority || undefined, owner_user_id: owner || undefined, q: query || undefined }),
    [status, priority, owner, query]
  );

  const columns: Column<TaskRow>[] = [
    { key: "title", header: "Task", render: (task) => <><strong>{task.title}</strong><div className="muted">{task.framework} {task.clause}</div></> },
    { key: "due", header: "Due", render: (task) => (task.due_at ? new Date(task.due_at).toLocaleDateString() : "Not scheduled") },
    { key: "owner", header: "Assignee", render: (task) => task.owner_email ?? "Unassigned" },
    { key: "priority", header: "Priority", render: (task) => <Badge value={task.priority} /> },
    { key: "status", header: "Status", render: (task) => <Badge value={task.status} /> },
  ];

  const total = allTasks.data?.length ?? 0;
  const done = allTasks.data?.filter((task) => task.status === "DONE").length ?? 0;
  const reload = () => { tasks.reload(); allTasks.reload(); };

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>{identity?.kind === "user" ? "My tasks" : "Remediation tasks"}</h2>
          <p>Find the exact gap, assign its owner and due date, then close it with corrected evidence.</p>
        </div>
      </div>

      <div className="queue-summary">
        <div><span>Total</span><strong>{total}</strong></div>
        <div><span>Open</span><strong>{total - done}</strong></div>
        <div><span>Closed by evidence</span><strong>{done}</strong></div>
      </div>

      <div className="queue-filters" aria-label="Task filters">
        <input aria-label="Search tasks" placeholder="Search title or remediation…" value={query} onChange={(event) => setQuery(event.target.value)} />
        <select aria-label="Filter by status" value={status} onChange={(event) => setStatus(event.target.value)}>
          {STATUSES.map((value) => <option key={value} value={value}>{value || "All statuses"}</option>)}
        </select>
        <select aria-label="Filter by priority" value={priority} onChange={(event) => setPriority(event.target.value)}>
          {PRIORITIES.map((value) => <option key={value} value={value}>{value || "All priorities"}</option>)}
        </select>
        <select aria-label="Filter by assignee" value={owner} onChange={(event) => setOwner(event.target.value)}>
          <option value="">All assignees</option>
          {owners.data?.map((item) => <option key={item.id} value={item.id}>{item.email}</option>)}
        </select>
      </div>

      {tasks.error && <div className="alert alert-error">{tasks.error}</div>}
      <DataTable columns={columns} rows={tasks.data ?? []} onRowClick={setSelected} emptyLabel="No tasks match these filters." />
      {selected && <TaskDrawer task={selected} canManage={identity?.kind === "org"} onClose={() => setSelected(null)} onSaved={reload} />}
    </div>
  );
}

function TaskDrawer({ task, canManage, onClose, onSaved }: { task: TaskRow; canManage: boolean; onClose: () => void; onSaved: () => void }) {
  const detail = useApi(() => getTask(task.id), [task.id]);
  const owners = useApi(() => listTaskOwners(), []);
  const [owner, setOwner] = useState(task.owner_user_id ?? "");
  const [due, setDue] = useState(task.due_at?.slice(0, 10) ?? "");
  const [priority, setPriority] = useState(task.priority);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!detail.data) return;
    setOwner(detail.data.owner_user_id ?? "");
    setDue(detail.data.due_at?.slice(0, 10) ?? "");
    setPriority(detail.data.priority);
  }, [detail.data]);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await updateTask(task.id, {
        owner_user_id: owner || null,
        due_at: due ? new Date(`${due}T00:00:00Z`).toISOString() : null,
        priority,
      });
      detail.reload();
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const data = detail.data ?? task;
  const history = detail.data?.history ?? [];
  return (
    <div className="drawer-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="task-drawer" aria-label="Task details">
        <div className="drawer-header">
          <div><span className="muted">{data.framework} {data.clause}</span><h3>{data.title}</h3></div>
          <button className="drawer-close" onClick={onClose} aria-label="Close task details">×</button>
        </div>

        {error && <div className="alert alert-error">{error}</div>}
        <div className="task-description">
          <strong>Required action</strong>
          <p>{data.required_action}</p>
          <div className="value-pair"><span>Observed<strong>{data.actual_value ?? "Missing"}</strong></span><span>Required<strong>{data.required_value ?? "See action"}</strong></span></div>
        </div>

        <div className="section-title">Work item</div>
        <div className="drawer-form">
          <label>Assignee<select disabled={!canManage} value={owner} onChange={(event) => setOwner(event.target.value)}><option value="">Unassigned</option>{owners.data?.map((item) => <option key={item.id} value={item.id}>{item.email}</option>)}</select></label>
          <label>Due date<input disabled={!canManage} type="date" value={due} onChange={(event) => setDue(event.target.value)} /></label>
          <label>Priority<select disabled={!canManage} value={priority} onChange={(event) => setPriority(event.target.value as TaskRow["priority"])}>{PRIORITIES.slice(1).map((value) => <option key={value}>{value}</option>)}</select></label>
          <label>Status<div><Badge value={data.status} /></div></label>
        </div>
        {canManage && <button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save assignment"}</button>}
        {!canManage && <p className="muted">Assignment and scheduling are managed by the organisation administrator.</p>}
        <p className="muted">Status is evidence-driven: uploading a corrected version closes the task when the evaluator confirms the gap is fixed.</p>
        <Link to={`/evidence/${data.evidence_id}`}>Open related evidence</Link>

        <div className="section-title">Activity timeline</div>
        <ul className="timeline">
          {history.map((event, index) => <li key={index}><div className="ts">{new Date(event.at).toLocaleString()}</div><strong>{event.action}</strong> by {event.actor}</li>)}
          {history.length === 0 && <li><div className="ts">{new Date(data.created_at).toLocaleString()}</div><strong>Task created</strong> from an evidence gap</li>}
        </ul>
      </aside>
    </div>
  );
}
