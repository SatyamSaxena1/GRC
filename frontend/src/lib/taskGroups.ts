import type { TaskRow } from "../api/client";
import { humanize } from "./format";

/** Tasks that ask for the same fix, across controls and frameworks: one "approval date is not
 *  stated" in six frameworks is one piece of work, not six. Manual tasks (no gap behind them)
 *  group together. Pure aggregation of what the backend already created; nothing new is decided. */
export type TaskGroup = {
  key: string;
  label: string;
  tasks: TaskRow[];
  controls: number;
  frameworks: string[];
  unassigned: number;
};

export function groupTasksByFix(tasks: TaskRow[]): TaskGroup[] {
  const by = new Map<string, TaskGroup>();
  for (const t of tasks) {
    const key = t.attribute ? `${t.kind ?? ""}|${t.attribute}` : "manual";
    const g = by.get(key) ?? {
      key, label: t.attribute ? humanize(t.attribute) : "Assigned directly", tasks: [], controls: 0, frameworks: [], unassigned: 0,
    };
    g.tasks.push(t);
    by.set(key, g);
  }
  return [...by.values()]
    .map((g) => ({
      ...g,
      controls: new Set(g.tasks.map((t) => t.org_control_id ?? t.id)).size,
      frameworks: [...new Set(g.tasks.map((t) => t.framework).filter((f): f is string => !!f))].sort(),
      unassigned: g.tasks.filter((t) => !t.owner_user_id).length,
    }))
    .sort((a, b) => b.tasks.length - a.tasks.length || a.label.localeCompare(b.label));
}
