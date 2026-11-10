// Filter des Pendenzen-Exports. Rechnet im Browser dieselbe Auswahl wie der Server
// (backend/app/documents/providers/todos.py: filter_rows), damit Liste, Zähler und Export
// übereinstimmen. Abweichungen hier zeigen sich als «12 ausgewählt», aber 11 im PDF.
import type { TodoListItem } from "@/types/api";

export type TodoStatusFilter = "open" | "in_progress" | "done" | "all";
export type TodoDueMode = "all" | "overdue" | "next_session" | "month" | "custom";

export type TodoExportFilter = {
  status: TodoStatusFilter;
  due: TodoDueMode;
  /** Datum bei due = "custom" (ISO) */
  due_date: string;
  /** Mit einer Fälligkeitsgrenze auch Pendenzen ohne Fälligkeit aufnehmen */
  include_undated: boolean;
  tag: string;
  participant_id: string;
  protocol_id: string;
  exclude_ids: string[];
};

export type TodoFilterDates = {
  today: string;
  /** Datum der nächsten Sitzung, falls eine Pendenz darauf verweist */
  nextSession: string | null;
};

const STATUSES: TodoStatusFilter[] = ["open", "in_progress", "done", "all"];

export function initialTodoExportFilter(pageParams: Record<string, unknown> = {}): TodoExportFilter {
  const status = String(pageParams.status ?? "open") as TodoStatusFilter;
  return {
    status: STATUSES.includes(status) ? status : "open",
    due: "all",
    due_date: "",
    include_undated: true,
    tag: typeof pageParams.tag === "string" ? pageParams.tag : "",
    participant_id: typeof pageParams.participant_id === "string" ? pageParams.participant_id : "",
    protocol_id: typeof pageParams.protocol_id === "string" ? pageParams.protocol_id : "",
    exclude_ids: [],
  };
}

/** Heutiges Datum (lokal) als ISO-String. */
export function localIsoDate(now: Date = new Date()): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export function endOfMonth(today: string): string {
  const [year, month] = today.split("-").map(Number);
  const last = new Date(year, month, 0).getDate();
  return `${today.slice(0, 7)}-${String(last).padStart(2, "0")}`;
}

function isOpen(todo: TodoListItem): boolean {
  const code = todo.todo_status_code ?? "open";
  return code === "open" || code === "in_progress";
}

/** Offen und die Fälligkeit liegt vor heute (heute fällig ist noch nicht überfällig). */
export function isOverdue(todo: TodoListItem, today: string): boolean {
  return isOpen(todo) && !!todo.resolved_due_date && todo.resolved_due_date < today;
}

/** Frühestes Datum «nächste Sitzung» ab heute unter den offenen Pendenzen. */
export function nextSessionDate(todos: TodoListItem[], today: string): string | null {
  const dates = todos
    .filter((todo) => todo.due_marker === "next_session" && isOpen(todo) && todo.resolved_due_date && todo.resolved_due_date >= today)
    .map((todo) => todo.resolved_due_date as string)
    .sort();
  return dates[0] ?? null;
}

/** Fälligkeitsgrenze des Filters; null = keine Grenze. */
export function dueUntil(filter: TodoExportFilter, dates: TodoFilterDates): string | null {
  if (filter.due === "next_session") return dates.nextSession;
  if (filter.due === "month") return endOfMonth(dates.today);
  if (filter.due === "custom") return filter.due_date || null;
  return null;
}

/** Wie filter_rows auf dem Server, ohne exclude_ids. */
export function matchesTodoFilter(todo: TodoListItem, filter: TodoExportFilter, dates: TodoFilterDates): boolean {
  const code = todo.todo_status_code ?? "open";
  if (filter.status === "open" && !isOpen(todo)) return false;
  if (filter.status === "in_progress" && code !== "in_progress") return false;
  if (filter.status === "done" && code !== "done") return false;
  if (filter.participant_id) {
    const ids = [todo.assigned_participant_id, ...(todo.assigned_participant_ids ?? [])];
    if (!ids.includes(filter.participant_id)) return false;
  }
  if (filter.tag) {
    const wanted = filter.tag.trim().toLowerCase();
    if (!(todo.tags ?? []).some((tag) => tag.toLowerCase() === wanted)) return false;
  }
  if (filter.due === "overdue" && !isOverdue(todo, dates.today)) return false;
  const limit = dueUntil(filter, dates);
  if (limit && (todo.resolved_due_date ? todo.resolved_due_date > limit : !filter.include_undated)) return false;
  if (filter.protocol_id && todo.protocol_id !== filter.protocol_id) return false;
  return true;
}

/** Sortierung wie im Export: nach Fälligkeit (ohne zuletzt), dann Aufgabe. */
export function sortTodos(todos: TodoListItem[]): TodoListItem[] {
  return [...todos].sort(
    (a, b) => String(a.resolved_due_date ?? "9999").localeCompare(String(b.resolved_due_date ?? "9999")) || a.task.localeCompare(b.task)
  );
}

/** Seitenkontext-Parameter für den Export. Status geht immer mit (ersetzt den der Seite). */
export function todoExportParams(filter: TodoExportFilter, dates: TodoFilterDates): Record<string, unknown> {
  const limit = dueUntil(filter, dates);
  return {
    status: filter.status,
    ...(filter.tag ? { tag: filter.tag } : {}),
    ...(filter.participant_id ? { participant_id: filter.participant_id } : {}),
    ...(filter.protocol_id ? { protocol_id: filter.protocol_id } : {}),
    ...(filter.due === "overdue" ? { overdue_only: true } : {}),
    ...(limit ? { due_until: limit, ...(filter.include_undated ? {} : { include_undated: false }) } : {}),
    ...(filter.exclude_ids.length ? { exclude_ids: filter.exclude_ids } : {}),
  };
}
