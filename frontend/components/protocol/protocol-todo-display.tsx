"use client";

import { useTranslations } from "next-intl";

import { dueInfo, type TodoDueInfo, type TodoDueTone } from "@/components/todos/todo-overview-utils";
import { formatDate } from "@/lib/utils/format";
import type { ProtocolTodo, TodoListItem } from "@/types/api";

// Darstellung der Pendenzen im Protokoll (Design «Termine, Listen & Pendenzen»): Fälligkeit
// farbig wie in der Pendenzen-Übersicht, Fortschritt, Initialen. Nur Anzeige.

type DueFields = Pick<ProtocolTodo, "due_date" | "due_marker" | "resolved_due_date" | "todo_status_code" | "submission_assignment_id">;

/** Gleiche Regel wie die Übersicht (dueInfo, SOON_DAYS): überfällig gegen heute, bald = 14 Tage. */
export function protocolTodoDue(todo: DueFields, today: string): TodoDueInfo {
  // Frisch gesetzte freie Daten haben lokal noch kein resolved_due_date
  const resolved = todo.resolved_due_date ?? todo.due_date ?? null;
  const item = {
    resolved_due_date: resolved,
    due_marker: todo.due_marker ?? null,
    submission_assignment_id: todo.submission_assignment_id ?? null,
    todo_status_code: todo.todo_status_code,
  } as unknown as TodoListItem;
  return dueInfo(item, today);
}

export function protocolTodoDueTone(todo: DueFields, today: string): TodoDueTone {
  return protocolTodoDue(todo, today).tone;
}

type TFunc = (key: string, values?: Record<string, string | number>) => string;

/** Text des Fälligkeits-Badges (Entwurf): «Überfällig · TT.MM.», «Heute», «In N Tagen», sonst
 * der bisherige Menütext (Datum, Nächste Sitzung, Termin …). `t` = Namespace protocols.tables. */
export function todoDueBadgeLabel(info: TodoDueInfo, fallback: string, t: TFunc): string {
  if (info.days === null || !info.date) return fallback;
  if (info.tone === "overdue") return t("todoDueOverdueBadge", { date: formatDate(info.date).slice(0, 6) });
  if (info.tone === "soon") return info.days === 0 ? t("todoDueToday") : t("todoDueInDays", { count: info.days });
  return fallback;
}

export function todoDueTriggerClass(tone: TodoDueTone): string {
  if (tone === "overdue") return "todo-due-trigger todo-due-trigger-overdue";
  if (tone === "soon") return "todo-due-trigger todo-due-trigger-soon";
  return "todo-due-trigger";
}

/** Screenreader-Hinweis zur Farbe (Farbe ist nie die einzige Information). */
export function TodoDueToneHint({ tone }: { tone: TodoDueTone }) {
  const t = useTranslations("protocols.tables");
  if (tone !== "overdue" && tone !== "soon") return null;
  return (
    <>
      <span className="todo-due-tone-dot" aria-hidden="true" />
      <span className="visually-hidden">{tone === "overdue" ? t("todoOverdue") : t("todoDueSoon")}</span>
    </>
  );
}

export function personInitials(name: string | null | undefined): string {
  return String(name ?? "")
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export function TodoAssigneeAvatar({ name }: { name: string | null | undefined }) {
  const initials = personInitials(name);
  if (!initials) return null;
  return <span className="todo-assignee-avatar" aria-hidden="true">{initials}</span>;
}

/** Kopf des Pendenzen-Blocks: «X offen · Y erledigt» links, Fortschrittsbalken mit % rechts. */
export function TodoProgress({ done, total }: { done: number; total: number }) {
  const t = useTranslations("protocols.tables");
  if (!total) return null;
  const percent = Math.round((done / total) * 100);
  return (
    <div className="todo-progress">
      <span className="todo-progress-summary">{t("todoSummary", { open: total - done, done })}</span>
      <div
        className="todo-progress-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={done}
        aria-label={t("todoProgress", { done, total })}
      >
        <span className="todo-progress-bar" style={{ width: `${percent}%` }} />
      </div>
      <span className="todo-progress-count">{t("todoProgressPercentShort", { percent })}</span>
    </div>
  );
}
