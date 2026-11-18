import { daysBetween, isTodoDone, type TFunc } from "@/components/mobile/mobile-utils";
import { formatDate } from "@/lib/utils/format";
import type { TodoListItem } from "@/types/api";

// Reine Hilfsfunktionen der Pendenzen-Übersicht v2 (Liste nach Fälligkeit, Board je Person,
// Kalender). Ohne Hooks; übersetzte Texte kommen als `t` (Namespace "todos") herein.

/** Pendenzen der nächsten so vielen Tage gelten als «bald» (Gruppe «Nächste 14 Tage», amber). */
export const SOON_DAYS = 14;

export type TodoDueKind = "date" | "session" | "submission" | "none";
export type TodoGroupKey = "overdue" | "soon" | "later" | "session" | "submission" | "none" | "done";
export type TodoDueTone = "overdue" | "soon" | "normal" | "done";

/** Reihenfolge der Gruppen in der Liste (leere werden ausgeblendet). */
export const TODO_GROUP_ORDER: TodoGroupKey[] = ["overdue", "soon", "later", "session", "submission", "none", "done"];

export type TodoDueInfo = {
  kind: TodoDueKind;
  /** ISO-Datum (JJJJ-MM-TT) oder null */
  date: string | null;
  /** Tage bis fällig (negativ = überfällig), null ohne Datum */
  days: number | null;
  group: TodoGroupKey;
  tone: TodoDueTone;
};

export function dueInfo(todo: TodoListItem, today: string): TodoDueInfo {
  const date = todo.resolved_due_date ? todo.resolved_due_date.slice(0, 10) : null;
  const days = date ? daysBetween(today, date) : null;
  const done = isTodoDone(todo);
  let kind: TodoDueKind;
  let group: TodoGroupKey;
  if (todo.due_marker === "next_session") {
    kind = "session";
    group = "session";
  } else if (date && days !== null) {
    kind = "date";
    group = days < 0 ? "overdue" : days <= SOON_DAYS ? "soon" : "later";
  } else if (todo.submission_assignment_id) {
    kind = "submission";
    group = "submission";
  } else {
    kind = "none";
    group = "none";
  }
  let tone: TodoDueTone = "normal";
  if (done) tone = "done";
  else if (days !== null && days < 0) tone = "overdue";
  else if (days !== null && days <= SOON_DAYS) tone = "soon";
  return { kind, date, days, group: done ? "done" : group, tone };
}

export type TodoGroup = { key: TodoGroupKey; items: TodoListItem[] };

/** Gruppiert nach Fälligkeit in der festen Reihenfolge; innerhalb nach Tagen bis fällig, dann Titel. */
export function groupTodos(todos: TodoListItem[], today: string): TodoGroup[] {
  const buckets = new Map<TodoGroupKey, { todo: TodoListItem; days: number | null }[]>();
  todos.forEach((todo) => {
    const info = dueInfo(todo, today);
    const list = buckets.get(info.group) ?? [];
    list.push({ todo, days: info.days });
    buckets.set(info.group, list);
  });
  return TODO_GROUP_ORDER.filter((key) => (buckets.get(key)?.length ?? 0) > 0).map((key) => ({
    key,
    items: (buckets.get(key) ?? [])
      .sort((a, b) => {
        if (a.days !== b.days) {
          if (a.days === null) return 1;
          if (b.days === null) return -1;
          return a.days - b.days;
        }
        return a.todo.task.localeCompare(b.todo.task);
      })
      .map((entry) => entry.todo),
  }));
}

export type TodoAssignee = { id: string; name: string };

/** Alle Verantwortlichen mit Namen (Mehrfach-Zuweisung oder nur Hauptverantwortliche). */
export function todoAssignees(todo: TodoListItem, nameById?: Map<string, string>): TodoAssignee[] {
  const ids = todo.assigned_participant_ids?.length
    ? todo.assigned_participant_ids
    : todo.assigned_participant_id
      ? [todo.assigned_participant_id]
      : [];
  const names = todo.assigned_participant_names ?? [];
  const fallback = ids.length === 1 ? todo.assigned_participant_name : null;
  return ids.map((id, index) => ({ id, name: names[index] ?? nameById?.get(id) ?? fallback ?? "?" }));
}

/** Neue Verantwortliche nach dem Verschieben einer Board-Karte von `fromId` nach `toId`
 * (null = «Nicht zugewiesen»): Ausgangsperson entfernen, Zielperson ergänzen; Ziel «Nicht
 * zugewiesen» entfernt alle. */
export function reassignedIds(currentIds: string[], fromId: string | null, toId: string | null): string[] {
  if (toId === null) return [];
  const kept = currentIds.filter((id) => id !== fromId);
  return kept.includes(toId) ? kept : [...kept, toId];
}

/** Herkunft der Pendenz (graue Zeile unter dem Titel). */
export function todoSourceLabel(todo: TodoListItem, t: TFunc): string {
  if (todo.submission_assignment_id) {
    return todo.submission_title ? t("v2.sourceSubmission", { title: todo.submission_title }) : t("v2.sourceSubmissionUnnamed");
  }
  if (todo.protocol_id) {
    const name = todo.protocol_title || todo.protocol_number || "";
    return todo.protocol_date ? t("v2.sourceProtocol", { name, date: formatDate(todo.protocol_date) }) : name;
  }
  if (todo.task_package_name) return t("v2.sourcePackage", { name: todo.task_package_name });
  return t("manuallyCreated");
}

/** Hauptzeile der Spalte «Fällig». */
export function dueMainLabel(info: TodoDueInfo, t: TFunc): string {
  if (info.kind === "session") return t("v2.dueNextSession");
  if (info.kind === "submission") return t("v2.dueWithSubmission");
  if (info.kind === "date" && info.date) return formatDate(info.date);
  return t("v2.dueNone");
}

/** Unterzeile der Spalte «Fällig» (überfällig seit, in N Tagen/Wochen, Sitzungsdatum …). */
export function dueSubLabel(info: TodoDueInfo, t: TFunc): string {
  if (info.kind === "session") return info.date ? formatDate(info.date) : t("v2.dateOpen");
  if (info.kind === "submission") return t("v2.closesAutomatically");
  if (info.kind !== "date" || info.days === null) return "";
  if (info.days < 0) return t("v2.overdueSinceDays", { count: -info.days });
  if (info.days === 0) return t("v2.dueToday");
  if (info.days < SOON_DAYS) return t("v2.inDays", { count: info.days });
  return t("v2.inWeeks", { count: Math.round(info.days / 7) });
}

/** Kurzform auf der Board-Karte. */
export function dueShortLabel(info: TodoDueInfo, t: TFunc): string {
  if (info.kind === "session") return t("v2.boardDueSession");
  if (info.kind === "submission") return t("v2.boardDueSubmission");
  if (info.kind !== "date" || !info.date || info.days === null) return "";
  if (info.days < 0) return t("v2.boardOverdue", { count: -info.days });
  if (info.days === 0) return t("v2.boardDueToday");
  const dayMonth = formatDate(info.date).slice(0, 6);
  if (info.days <= SOON_DAYS) return t("v2.boardDueSoon", { date: dayMonth, count: info.days });
  return t("v2.boardDueLater", { date: formatDate(info.date) });
}

/** ISO-Datum plus `days` Tage. */
export function addDaysIso(iso: string, days: number): string {
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day + days));
  return date.toISOString().slice(0, 10);
}

/** Vorname bzw. erstes Wort eines Anzeigenamens (Kalender-Seitenleiste). */
export function firstName(name: string): string {
  return name.trim().split(/\s+/)[0] ?? name;
}
