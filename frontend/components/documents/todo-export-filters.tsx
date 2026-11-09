"use client";

// Export-Dialog, Schritt 1 für Pendenzen: Status, Fälligkeit (auch überfällig), Tag, Person,
// Protokoll und einzelne Pendenzen von Hand an- oder abwählen. Die Auswahl wird als
// Seitenkontext an den Server geschickt (todoExportParams), der dieselben Filter anwendet
// (lib/documents/todo-export-filter.ts).
import { useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { DateInput } from "@/components/ui/date-input";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { browserApiFetch } from "@/lib/api/client";
import {
  endOfMonth,
  isOverdue,
  matchesTodoFilter,
  sortTodos,
  TodoDueMode,
  TodoExportFilter,
  TodoFilterDates,
  TodoStatusFilter,
} from "@/lib/documents/todo-export-filter";
import { formatShortMonthDate } from "@/lib/utils/format";
import { TodoListItem } from "@/types/api";

const PAGE_SIZE = 500;

/** Alle Pendenzen des Mandanten (wie GET /api/todos, seitenweise). null = lädt, "error" = nicht
 * ladbar (dann blockiert der Dialog den Export nicht, der Server filtert trotzdem). */
export function useExportTodos(enabled: boolean): TodoListItem[] | null | "error" {
  const [todos, setTodos] = useState<TodoListItem[] | null | "error">(null);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    (async () => {
      const all: TodoListItem[] = [];
      for (let skip = 0; ; skip += PAGE_SIZE) {
        const page = (await browserApiFetch<TodoListItem[]>(`/api/todos?skip=${skip}&limit=${PAGE_SIZE}`)) ?? [];
        all.push(...page);
        if (page.length < PAGE_SIZE) break;
      }
      return all;
    })()
      .then((loaded) => active && setTodos(loaded))
      .catch(() => active && setTodos("error"));
    return () => {
      active = false;
    };
  }, [enabled]);
  return todos;
}

type Option = { id: string; label: string };

type Props = {
  todos: TodoListItem[] | null | "error";
  dates: TodoFilterDates;
  value: TodoExportFilter;
  onChange: (next: TodoExportFilter) => void;
};

export function TodoExportFilters({ todos, dates, value, onChange }: Props) {
  const t = useTranslations("documentStudio.export.todoFilter");
  const locale = useLocale();
  const all = useMemo(() => (Array.isArray(todos) ? todos : []), [todos]);
  const set = (patch: Partial<TodoExportFilter>) => onChange({ ...value, ...patch });
  // Zähler eines Chips: alle übrigen Filter wie gewählt, dieser Filter mit dem Wert des Chips
  const count = (patch: Partial<TodoExportFilter>) => all.filter((todo) => matchesTodoFilter(todo, { ...value, ...patch }, dates)).length;

  const candidates = useMemo(() => sortTodos(all.filter((todo) => matchesTodoFilter(todo, value, dates))), [all, value, dates]);
  const excluded = new Set(value.exclude_ids);
  const selectedCount = candidates.filter((todo) => !excluded.has(todo.id)).length;

  const tags = useMemo(() => [...new Set(all.flatMap((todo) => todo.tags ?? []))].sort((a, b) => a.localeCompare(b)), [all]);
  const people = useMemo<Option[]>(() => {
    const byId = new Map<string, string>();
    for (const todo of all) if (todo.assigned_participant_id && todo.assigned_participant_name) byId.set(todo.assigned_participant_id, todo.assigned_participant_name);
    return [...byId].map(([id, label]) => ({ id, label })).sort((a, b) => a.label.localeCompare(b.label));
  }, [all]);
  const protocols = useMemo<Option[]>(() => {
    const byId = new Map<string, { label: string; date: string }>();
    for (const todo of all) {
      if (!todo.protocol_id) continue;
      const label = [todo.protocol_number, todo.protocol_title].filter(Boolean).join(" · ") || t("protocolUntitled");
      byId.set(todo.protocol_id, { label, date: todo.protocol_date ?? "" });
    }
    return [...byId].sort((a, b) => b[1].date.localeCompare(a[1].date)).map(([id, item]) => ({ id, label: item.label }));
  }, [all, t]);

  const statusOptions: { value: TodoStatusFilter; label: string; count: number }[] = (["open", "in_progress", "done", "all"] as const).map((status) => ({
    value: status,
    label: t(`status.${status}`),
    count: count({ status }),
  }));
  const shortDate = (iso: string) => formatShortMonthDate(iso, locale);
  const dueOptions: { value: TodoDueMode; label: string; count?: number }[] = [
    { value: "all", label: t("due.all") },
    { value: "overdue", label: t("due.overdue"), count: count({ due: "overdue" }) },
    ...(dates.nextSession ? [{ value: "next_session" as const, label: t("due.nextSession", { date: shortDate(dates.nextSession) }) }] : []),
    { value: "month", label: t("due.month", { date: shortDate(endOfMonth(dates.today)) }) },
    { value: "custom", label: value.due === "custom" && value.due_date ? shortDate(value.due_date) : t("due.custom") },
  ];
  const tagOptions = [
    { value: "", label: t("allTags"), count: count({ tag: "" }) },
    ...tags
      .map((tag) => ({ value: tag, label: tag, count: count({ tag }) }))
      .filter((option) => option.count > 0 || option.value === value.tag),
  ];

  function setExcluded(ids: string[]) {
    set({ exclude_ids: ids });
  }

  function dueLabel(todo: TodoListItem) {
    if (!todo.resolved_due_date) return t("item.noDue");
    return isOverdue(todo, dates.today)
      ? t("item.overdueSince", { date: shortDate(todo.resolved_due_date) })
      : t("item.due", { date: shortDate(todo.resolved_due_date) });
  }

  return (
    <section className="export-step" aria-labelledby="export-step-todos">
      <div className="export-step-head">
        <span className="export-step-number" aria-hidden="true">
          1
        </span>
        <h3 id="export-step-todos" className="export-step-title">
          {t("title")}
        </h3>
        <span className="export-step-meta">{t("selection", { selected: selectedCount, total: candidates.length })}</span>
      </div>

      <div className="export-filter" role="group" aria-labelledby="export-filter-status">
        <span className="field-label" id="export-filter-status">{t("statusLabel")}</span>
        <FilterTabs variant="chips" options={statusOptions} value={value.status} onChange={(status) => set({ status })} />
      </div>

      <div className="export-filter" role="group" aria-labelledby="export-filter-due">
        <span className="field-label" id="export-filter-due">{t("dueLabel")}</span>
        <FilterTabs
          variant="chips"
          options={dueOptions}
          value={value.due}
          onChange={(due) => set({ due, due_date: due === "custom" ? value.due_date || endOfMonth(dates.today) : value.due_date })}
        />
        {value.due === "custom" && (
          <label className="field-stack export-filter-date">
            <span className="field-label">{t("dueUntil")}</span>
            <DateInput value={value.due_date} onChange={(next) => set({ due_date: next })} />
          </label>
        )}
        {value.due !== "all" && value.due !== "overdue" && (
          <label className="studio-inline-check">
            <input type="checkbox" checked={value.include_undated} onChange={(event) => set({ include_undated: event.target.checked })} />
            <span>{t("includeUndated")}</span>
          </label>
        )}
      </div>

      {tags.length > 0 && (
        <div className="export-filter" role="group" aria-labelledby="export-filter-tag">
          <span className="field-label" id="export-filter-tag">{t("tag")}</span>
          <FilterTabs variant="chips" options={tagOptions} value={value.tag} onChange={(tag) => set({ tag })} />
        </div>
      )}

      <div className="two-col">
        <label className="field-stack">
          <span className="field-label">{t("person")}</span>
          <SearchableSelect
            options={people}
            getId={(option) => option.id}
            getLabel={(option) => option.label}
            value={value.participant_id || null}
            onChange={(option) => set({ participant_id: option?.id ?? "" })}
            nullLabel={t("allPeople")}
            placeholder={t("allPeople")}
          />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("protocol")}</span>
          <SearchableSelect
            options={protocols}
            getId={(option) => option.id}
            getLabel={(option) => option.label}
            value={value.protocol_id || null}
            onChange={(option) => set({ protocol_id: option?.id ?? "" })}
            nullLabel={t("allProtocols")}
            placeholder={t("allProtocols")}
          />
        </label>
      </div>

      <div className="export-todo-list">
        <div className="export-todo-list-head">
          <span className="field-label">{t("pick")}</span>
          <button type="button" className="button-secondary button-ghost" onClick={() => setExcluded(value.exclude_ids.filter((id) => !candidates.some((todo) => todo.id === id)))}>
            {t("all")}
          </button>
          <button type="button" className="button-secondary button-ghost" onClick={() => setExcluded([...new Set([...value.exclude_ids, ...candidates.map((todo) => todo.id)])])}>
            {t("none")}
          </button>
        </div>
        {todos === null ? (
          <p className="muted">{t("loading")}</p>
        ) : todos === "error" ? (
          <p className="muted export-todo-empty">{t("loadFailed")}</p>
        ) : candidates.length === 0 ? (
          <p className="muted export-todo-empty">{t("empty")}</p>
        ) : (
          candidates.map((todo) => {
            const checked = !excluded.has(todo.id);
            return (
              <label key={todo.id} className={checked ? "export-todo-item" : "export-todo-item export-todo-item-off"}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(event) =>
                    setExcluded(event.target.checked ? value.exclude_ids.filter((id) => id !== todo.id) : [...value.exclude_ids, todo.id])
                  }
                />
                <span className="export-todo-text">
                  <span className="export-todo-task">{todo.task}</span>
                  <span className="export-todo-meta">
                    {todo.assigned_participant_name ? `${todo.assigned_participant_name} · ` : ""}
                    <span className={isOverdue(todo, dates.today) ? "export-todo-overdue" : undefined}>{dueLabel(todo)}</span>
                  </span>
                </span>
                {(todo.tags ?? []).slice(0, 2).map((tag) => (
                  <span key={tag} className="export-todo-tag">
                    {tag}
                  </span>
                ))}
              </label>
            );
          })
        )}
      </div>
    </section>
  );
}
