"use client";

// Export-Dialog für Pendenzen: nur bis zu einem Fälligkeitsdatum, nur mit einem Tag und einzelne
// Pendenzen von Hand an- oder abwählen. Ergebnis sind Seitenkontext-Parameter (due_until, tag,
// exclude_ids), die der Server auf die Pendenzen-Tabellen der Vorlage anwendet (PDF, CSV, Excel,
// Text). Die Liste hier rechnet dieselben Filter wie der Server (providers/todos.filter_rows).
import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { DateInput } from "@/components/ui/date-input";
import { Select } from "@/components/ui/select";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate } from "@/lib/utils/format";
import { TodoListItem } from "@/types/api";

export type TodoExportFilter = { due_until: string; tag: string; exclude_ids: string[] };

export const EMPTY_TODO_EXPORT_FILTER: TodoExportFilter = { due_until: "", tag: "", exclude_ids: [] };

/** Parameter für den Export; leere Filter fallen weg (dann gelten die Filter der Seite). */
export function todoExportParams(filter: TodoExportFilter): Record<string, unknown> {
  return {
    ...(filter.due_until ? { due_until: filter.due_until } : {}),
    ...(filter.tag ? { tag: filter.tag } : {}),
    ...(filter.exclude_ids.length ? { exclude_ids: filter.exclude_ids } : {}),
  };
}

const CLOSED = new Set(["done", "cancelled"]);

type Props = {
  /** Filter der Seite (status, tag), Grundlage der Liste */
  pageParams: Record<string, unknown>;
  value: TodoExportFilter;
  onChange: (next: TodoExportFilter) => void;
};

export function TodoExportFilters({ pageParams, value, onChange }: Props) {
  const t = useTranslations("documentStudio.export.todoFilter");
  const [todos, setTodos] = useState<TodoListItem[] | null>(null);

  useEffect(() => {
    let active = true;
    browserApiFetch<TodoListItem[]>("/api/todos?limit=500")
      .then((loaded) => { if (active) setTodos(loaded ?? []); })
      .catch(() => { if (active) setTodos([]); });
    return () => { active = false; };
  }, []);

  const status = String(pageParams.status ?? "open");
  const tag = value.tag || String(pageParams.tag ?? "");
  const allTags = useMemo(
    () => [...new Set((todos ?? []).flatMap((todo) => todo.tags ?? []))].sort((a, b) => a.localeCompare(b)),
    [todos]
  );
  const candidates = useMemo(
    () =>
      (todos ?? [])
        .filter((todo) => (status === "open" ? !CLOSED.has(String(todo.todo_status_code ?? "")) : status === "done" ? todo.todo_status_code === "done" : true))
        .filter((todo) => !tag || (todo.tags ?? []).some((entry) => entry.toLowerCase() === tag.toLowerCase()))
        .filter((todo) => !value.due_until || !todo.resolved_due_date || todo.resolved_due_date <= value.due_until)
        .sort((a, b) => String(a.resolved_due_date ?? "9999").localeCompare(String(b.resolved_due_date ?? "9999")) || a.task.localeCompare(b.task)),
    [todos, status, tag, value.due_until]
  );
  const excluded = new Set(value.exclude_ids);
  const selectedCount = candidates.filter((todo) => !excluded.has(todo.id)).length;

  function setExcluded(ids: string[]) {
    onChange({ ...value, exclude_ids: ids });
  }

  return (
    <section className="studio-export-section" aria-labelledby="studio-export-todo-filter">
      <h3 id="studio-export-todo-filter" className="studio-section-title">
        {t("title")}
      </h3>
      <div className="two-col">
        <label className="field-stack">
          <span className="field-label">{t("dueUntil")}</span>
          <DateInput value={value.due_until} onChange={(next) => onChange({ ...value, due_until: next })} />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("tag")}</span>
          <Select value={value.tag} onChange={(event) => onChange({ ...value, tag: event.target.value })}>
            <option value="">{pageParams.tag ? t("tagFromPage", { tag: String(pageParams.tag) }) : t("allTags")}</option>
            {allTags.map((entry) => (
              <option key={entry} value={entry}>
                {entry}
              </option>
            ))}
          </Select>
        </label>
      </div>
      <div className="todo-export-list-head">
        <span className="field-label">{t("selection", { selected: selectedCount, total: candidates.length })}</span>
        <button type="button" className="button-secondary button-ghost" onClick={() => setExcluded([])}>
          {t("all")}
        </button>
        <button type="button" className="button-secondary button-ghost" onClick={() => setExcluded(candidates.map((todo) => todo.id))}>
          {t("none")}
        </button>
      </div>
      <div className="todo-export-list">
        {todos === null ? (
          <p className="muted">{t("loading")}</p>
        ) : candidates.length === 0 ? (
          <p className="muted">{t("empty")}</p>
        ) : (
          candidates.map((todo) => (
            <label key={todo.id} className="studio-inline-check todo-export-item">
              <input
                type="checkbox"
                checked={!excluded.has(todo.id)}
                onChange={(event) =>
                  setExcluded(event.target.checked ? value.exclude_ids.filter((id) => id !== todo.id) : [...value.exclude_ids, todo.id])
                }
              />
              <span>
                {todo.task}
                <span className="field-help">
                  {[todo.assigned_participant_name, todo.resolved_due_date ? formatDate(todo.resolved_due_date) : null].filter(Boolean).join(" · ")}
                </span>
              </span>
            </label>
          ))
        )}
      </div>
    </section>
  );
}
