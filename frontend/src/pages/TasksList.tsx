import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  createTask,
  getTask,
  listControls,
  listTaskOwners,
  listTasks,
  updateTask,
  type ControlSummary,
  type TaskRow,
} from "../api/client";
import { useApi } from "../lib/useApi";
import { DataTable, type Column } from "../components/DataTable";
import { Badge } from "../components/Badge";
import { PageTour } from "../components/PageTour";
import { useSession } from "../lib/session";

const STATUSES = ["", "OPEN", "DONE"];
const PRIORITIES = ["", "LOW", "MEDIUM", "HIGH", "CRITICAL"];

export function TasksListPage() {
  const { identity } = useSession();
  const isAdmin = identity?.kind === "org";
  const [status, setStatus] = useState("OPEN");
  const [priority, setPriority] = useState("");
  const [owner, setOwner] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<TaskRow | null>(null);
  const [showNewTask, setShowNewTask] = useState(false);
  const owners = useApi(() => listTaskOwners(), []);
  const allTasks = useApi(() => listTasks(), []);
  const tasks = useApi(
    () => listTasks({ status: status || undefined, priority: priority || undefined, owner_user_id: owner || undefined, q: query || undefined }),
    [status, priority, owner, query]
  );

  const columns: Column<TaskRow>[] = [
    {
      key: "title", header: "Task", render: (task) => (
        <>
          <strong>{task.title}</strong>
          <div className="muted">{task.is_manual ? "Assigned directly" : `${task.framework} ${task.clause}`}</div>
        </>
      ),
    },
    { key: "due", header: "Due", render: (task) => (task.due_at ? new Date(task.due_at).toLocaleDateString() : "Not scheduled") },
    { key: "owner", header: "Assignee", render: (task) => task.owner_email ?? "Unassigned" },
    { key: "priority", header: "Priority", render: (task) => <Badge value={task.priority} /> },
    { key: "status", header: "Status", render: (task) => <Badge value={task.status} /> },
  ];

  const total = allTasks.data?.length ?? 0;
  const done = allTasks.data?.filter((task) => task.status === "DONE").length ?? 0;
  const reload = () => { tasks.reload(); allTasks.reload(); };

  const tourSteps = [
    {
      title: "Where every task comes from",
      body: "Most tasks are created automatically — one per open gap, generated the moment evidence fails a requirement. The rest are handed out directly for work that isn't tied to a specific piece of evidence.",
      target: ".queue-summary",
    },
    {
      title: "Narrow the queue",
      body: "Search by title or remediation text, or filter by status, priority, and assignee — all four combine, so you can get straight to \"my overdue high-priority items\".",
      target: ".queue-filters",
    },
    ...(isAdmin ? [{
      title: "Hand out direct work",
      body: "Not every task needs a gap behind it — use this to assign something straight to an employee, with its own due date and priority.",
      target: "[data-tour='assign-task']",
    }] : []),
    {
      title: "Open a task for the full picture",
      body: "Click any row to see the required action, the observed vs. required value, who owns it, and its full activity timeline.",
      target: ".data-table, .empty-state",
    },
  ] as const;

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>{identity?.kind === "user" ? "My tasks" : "Remediation tasks"}</h2>
          <p>Find the exact gap, assign its owner and due date, then close it with corrected evidence.</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {isAdmin && (
            <button className="btn btn-primary" data-tour="assign-task" onClick={() => setShowNewTask((v) => !v)}>
              {showNewTask ? "Cancel" : "Assign a task"}
            </button>
          )}
          <PageTour id="tasks" steps={tourSteps} />
        </div>
      </div>

      {showNewTask && (
        <NewTaskForm
          onCreated={() => { setShowNewTask(false); reload(); }}
          onCancel={() => setShowNewTask(false)}
        />
      )}

      <div className="queue-summary">
        <div><span>Total</span><strong>{total}</strong></div>
        <div><span>Open</span><strong>{total - done}</strong></div>
        <div><span>Closed</span><strong>{done}</strong></div>
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
      {selected && (
        <TaskDrawer
          task={selected}
          canManage={isAdmin}
          isOwner={identity?.kind === "user" && identity.id === selected.owner_user_id}
          onClose={() => setSelected(null)}
          onSaved={reload}
        />
      )}
    </div>
  );
}

function NewTaskForm({ onCreated, onCancel }: { onCreated: () => void; onCancel: () => void }) {
  const owners = useApi(() => listTaskOwners(), []);
  const controls = useApi(() => listControls(), []);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [owner, setOwner] = useState("");
  const [due, setDue] = useState("");
  const [priority, setPriority] = useState<TaskRow["priority"]>("MEDIUM");
  const [controlId, setControlId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!title.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await createTask({
        title: title.trim(),
        description: description.trim(),
        owner_user_id: owner || null,
        due_at: due ? new Date(`${due}T00:00:00Z`).toISOString() : null,
        priority,
        org_control_id: controlId || null,
      });
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card" style={{ marginBottom: 24, maxWidth: 560 }}>
      <strong>Assign a task to an employee</strong>
      <p className="stat-sub">
        Not tied to a compliance gap — a direct to-do, e.g. "get the policy signed by Friday".
        The employee (or you) marks it done by hand.
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="form-grid">
        <div>
          <label>Title</label>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Sign the updated access control policy" />
        </div>
        <div>
          <label>Details (optional)</label>
          <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Any extra context for the assignee" />
        </div>
        <div>
          <label>Assignee</label>
          <select value={owner} onChange={(e) => setOwner(e.target.value)}>
            <option value="">Unassigned</option>
            {owners.data?.map((item) => <option key={item.id} value={item.id}>{item.email}</option>)}
          </select>
        </div>
        <div>
          <label>Due date (optional)</label>
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
        </div>
        <div>
          <label>Priority</label>
          <select value={priority} onChange={(e) => setPriority(e.target.value as TaskRow["priority"])}>
            {PRIORITIES.slice(1).map((value) => <option key={value}>{value}</option>)}
          </select>
        </div>
        <div>
          <label>Related control (optional)</label>
          <select value={controlId} onChange={(e) => setControlId(e.target.value)}>
            <option value="">No specific control</option>
            {controls.data?.map((c: ControlSummary) => (
              <option key={c.id} value={c.id}>{c.framework} {c.clause}</option>
            ))}
          </select>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn btn-primary" disabled={!title.trim() || busy} onClick={submit}>
            {busy ? "Assigning…" : "Assign task"}
          </button>
          <button className="btn" onClick={onCancel}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

function TaskDrawer({
  task, canManage, isOwner, onClose, onSaved,
}: { task: TaskRow; canManage: boolean; isOwner: boolean; onClose: () => void; onSaved: () => void }) {
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

  const setDone = async (done: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await updateTask(task.id, { status: done ? "DONE" : "OPEN" });
      detail.reload();
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const data = detail.data ?? task;
  const history = detail.data?.history ?? [];
  const canClose = canManage || isOwner;

  return (
    <div className="drawer-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="task-drawer" aria-label="Task details">
        <div className="drawer-header">
          <div>
            <span className="muted">{data.is_manual ? "Assigned directly" : `${data.framework} ${data.clause}`}</span>
            <h3>{data.title}</h3>
          </div>
          <button className="drawer-close" onClick={onClose} aria-label="Close task details">×</button>
        </div>

        {error && <div className="alert alert-error">{error}</div>}
        <div className="task-description">
          <strong>{data.is_manual ? "Details" : "Required action"}</strong>
          <p>{data.required_action || "No further detail was provided."}</p>
          {!data.is_manual && (
            <div className="value-pair"><span>Observed<strong>{data.actual_value ?? "Missing"}</strong></span><span>Required<strong>{data.required_value ?? "See action"}</strong></span></div>
          )}
        </div>

        <div className="section-title">Work item</div>
        <div className="drawer-form">
          <label>Assignee<select disabled={!canManage} value={owner} onChange={(event) => setOwner(event.target.value)}><option value="">Unassigned</option>{owners.data?.map((item) => <option key={item.id} value={item.id}>{item.email}</option>)}</select></label>
          <label>Due date<input disabled={!canManage} type="date" value={due} onChange={(event) => setDue(event.target.value)} /></label>
          <label>Priority<select disabled={!canManage} value={priority} onChange={(event) => setPriority(event.target.value as TaskRow["priority"])}>{PRIORITIES.slice(1).map((value) => <option key={value}>{value}</option>)}</select></label>
          <label>Status<div><Badge value={data.status} /></div></label>
        </div>
        {canManage && <button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save assignment"}</button>}
        {!canManage && !isOwner && <p className="muted">Assignment and scheduling are managed by the organisation administrator.</p>}

        {data.is_manual ? (
          canClose ? (
            <button
              className="btn"
              style={{ marginTop: 8 }}
              disabled={busy}
              onClick={() => setDone(data.status !== "DONE")}
            >
              {data.status === "DONE" ? "Reopen task" : "Mark done"}
            </button>
          ) : (
            <p className="muted">Only the organisation admin or the assigned employee can close this task.</p>
          )
        ) : (
          <p className="muted">
            Status is evidence-driven: uploading a corrected version closes the task when the evaluator confirms the gap is fixed.
          </p>
        )}
        {data.evidence_id && <Link to={`/evidence/${data.evidence_id}`}>Open related evidence</Link>}

        <div className="section-title">Activity timeline</div>
        <ul className="timeline">
          {history.map((event, index) => <li key={index}><div className="ts">{new Date(event.at).toLocaleString()}</div><strong>{event.action}</strong> by {event.actor}</li>)}
          {history.length === 0 && (
            <li>
              <div className="ts">{new Date(data.created_at).toLocaleString()}</div>
              <strong>Task created</strong> {data.is_manual ? `by ${data.created_by || "an admin"}` : "from an evidence gap"}
            </li>
          )}
        </ul>
      </aside>
    </div>
  );
}
