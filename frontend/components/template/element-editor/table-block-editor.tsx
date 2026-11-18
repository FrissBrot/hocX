"use client";

// Tabellenblock (Typ 6) im Block-Editor: Zeilen werden direkt im Dialog aufgeklappt und bearbeitet
// (früher in einem eigenen Designer). Bei «Pro Termin» bzw. «Pro Pendenz» stehen die Felder der
// Quelle als eigene Gruppe zuoberst (event_fields bzw. todo_fields), und die Vorschau rechts zeigt
// die Tabelle wie im Protokoll-Editor oder im PDF für einen der aktuell passenden Termine bzw.
// eine Beispiel-Pendenz. Gespeichert wird in form.config (rows, event_fields, todo_fields,
// linked_list_*), siehe block-form.ts.
import { type DragEvent, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslations } from "next-intl";

import { FilterTabs } from "@/components/ui/filter-tabs";
import { usePopoverDismiss, usePopoverPosition } from "@/components/ui/popover";
import { SearchableMultiSelect } from "@/components/ui/searchable-select";
import { Select } from "@/components/ui/select";
import { browserApiFetch } from "@/lib/api/client";
import { applyEventFilter } from "@/lib/element-types/event-filter";
import { useEventFieldConfig } from "@/lib/hooks/use-event-field-config";
import { formatDate, formatDateRange } from "@/lib/utils/format";
import { markdownToPlainText } from "@/lib/utils/markdown-text";
import { formatTimeValue } from "@/lib/utils/time";
import type { EventSummary, ListColumn, StructuredListDefinition, StructuredListEntry, TodoListItem } from "@/types/api";

import { type BlockForm, defaultRow, defaultRowConfig, moveItem, nextRowId, repeatEventFilter, type TableRow } from "./block-form";
import { RowValueFields, type RowInspectorData, useListValueDescriber } from "./row-inspector";

export const EVENT_FIELDS = [
  "title", "description", "program", "event_date", "event_end_date", "start_time", "end_time", "tag", "participant_count", "organizer_ids",
  "leadership_ids", "participant_ids", "spezial1_ids", "spezial2_ids", "spezial3_ids", "location", "spezial_text1", "spezial_text2",
  "spezial_text3", "spezial_time1", "spezial_time2",
] as const;

const TIME_FIELDS = new Set(["start_time", "end_time", "spezial_time1", "spezial_time2"]);
const MARKDOWN_FIELDS = new Set(["description", "program", "spezial_text1", "spezial_text2", "spezial_text3"]);

type EventField = (typeof EVENT_FIELDS)[number];
type EventFieldConfig = { field: string; label: string; enabled: boolean };

const FIELD_GROUPS: Array<{ key: string; fields: readonly EventField[] }> = [
  { key: "event", fields: ["title", "description", "program", "event_date", "event_end_date", "start_time", "end_time", "tag", "participant_count", "location"] },
  { key: "people", fields: ["organizer_ids", "leadership_ids", "participant_ids", "spezial1_ids", "spezial2_ids", "spezial3_ids"] },
  { key: "texts", fields: ["spezial_text1", "spezial_text2", "spezial_text3", "spezial_time1", "spezial_time2"] },
];

/** «Pro Pendenz»: Felder der Pendenz, gleiche Reihenfolge wie im Backend (services/linked_todo.py). */
export const TODO_FIELDS = ["task", "description", "participant", "due_date", "status", "origin"] as const;

/** Termin bzw. Pendenz, für die ein Block entsteht (Vorschau). */
export type SourceItem = { kind: "event"; event: EventSummary } | { kind: "todo"; todo: TodoListItem };

export function sourceTitle(item: SourceItem | null): string {
  return !item ? "" : item.kind === "event" ? item.event.title : item.todo.task;
}

/** Zeilentypen einer Tabelle (Matrix hat zusätzlich «Mehrere Termine» und eingebettete Blöcke). */
const TABLE_ROW_TYPES = ["text", "participant", "participants", "event", "list_entry"] as const;

export const EVENT_TOKENS = ["{title}", "{description}", "{event_date}", "{event_end_date}", "{tag}", "{id}"];

type TFunc = (key: string, values?: Record<string, string | number>) => string;

function fieldsOf(form: BlockForm, key: "event_fields" | "todo_fields", all: readonly string[]): EventFieldConfig[] {
  const saved = Array.isArray(form.config[key]) ? (form.config[key] as EventFieldConfig[]) : [];
  return all.map((field) => saved.find((entry) => entry.field === field) ?? { field, label: "", enabled: false });
}

export function eventFieldsOf(form: BlockForm): EventFieldConfig[] {
  return fieldsOf(form, "event_fields", EVENT_FIELDS);
}

export function todoFieldsOf(form: BlockForm): EventFieldConfig[] {
  return fieldsOf(form, "todo_fields", TODO_FIELDS);
}

function todoOrigin(todo: TodoListItem): string {
  return [todo.protocol_number, todo.block_title].filter(Boolean).join(" · ");
}

/** Platzhalter eines Termins ersetzen wie beim Erstellen des Protokolls. */
export function resolveEventTokens(text: string, event: EventSummary | null): string {
  if (!event) return text;
  return text
    .replace(/\{title\}/g, event.title)
    .replace(/\{description\}/g, markdownToPlainText(event.description))
    .replace(/\{event_date\}/g, formatDate(event.event_date))
    .replace(/\{event_end_date\}/g, event.event_end_date ? formatDate(event.event_end_date) : "")
    .replace(/\{tag\}/g, event.tag ?? "")
    .replace(/\{id\}/g, event.id);
}

/** Platzhalter einer Termin- oder Pendenzquelle ersetzen (wie protocol_service beim Erstellen). */
export function resolveSourceTokens(text: string, item: SourceItem | null): string {
  if (!item) return text;
  if (item.kind === "event") return resolveEventTokens(text, item.event);
  const todo = item.todo;
  return text
    .replace(/\{(?:title|task)\}/g, todo.task)
    .replace(/\{description\}/g, todo.reference_link ?? "")
    .replace(/\{due_date\}/g, todo.due_date ? formatDate(todo.due_date) : "")
    .replace(/\{participant\}/g, todo.assigned_participant_name ?? "")
    .replace(/\{id\}/g, todo.id);
}

function todayIso() {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

let todoCache: Promise<TodoListItem[]> | null = null;

/** Pendenzen des Mandanten als Beispiele für die Vorschau «Pro Pendenz» (einmal je Seite geladen). */
function useTenantTodos(enabled: boolean): TodoListItem[] {
  const [todos, setTodos] = useState<TodoListItem[]>([]);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    todoCache ??= browserApiFetch<TodoListItem[]>("/api/todos?limit=500").catch(() => {
      todoCache = null;
      return [];
    });
    void todoCache.then((loaded) => {
      if (active) setTodos(loaded);
    });
    return () => {
      active = false;
    };
  }, [enabled]);
  return todos;
}

/**
 * Quellen, für die heute ein Block entstünde: passende Termine bei «Pro Termin» (Zyklus wird in der
 * Vorlage nicht ausgewertet), bei «Pro Pendenz» Pendenzen nach denselben Filtern. Welche Pendenzen
 * es im Protokoll sind, hängt vom vorherigen Protokoll ab - hier sind es Beispiele des Mandanten.
 */
export function useMatchingSources(form: BlockForm, events: EventSummary[]): SourceItem[] {
  const repeat = String(form.config.repeat_source ?? "none");
  const filter = repeatEventFilter(form);
  const key = JSON.stringify(filter);
  const todos = useTenantTodos(repeat === "todo");
  const openOnly = form.config.todo_open_only !== false;
  const taskFilter = String(form.config.todo_task_filter ?? "").trim().toLowerCase();
  const blockFilter = String(form.config.todo_block_title_filter ?? "").trim().toLowerCase();
  return useMemo(() => {
    if (repeat === "event") {
      return applyEventFilter(events.filter((event) => !event.is_cancelled), filter, { protocolDate: todayIso() }).map((event) => ({ kind: "event" as const, event }));
    }
    if (repeat !== "todo") return [];
    return todos
      .filter((todo) => !openOnly || !["done", "cancelled"].includes(String(todo.todo_status_code)))
      .filter((todo) => !taskFilter || todo.task.toLowerCase().includes(taskFilter))
      .filter((todo) => !blockFilter || String(todo.block_title ?? "").toLowerCase().includes(blockFilter))
      .slice(0, 12)
      .map((todo) => ({ kind: "todo" as const, todo }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repeat, key, events, todos, openOnly, taskFilter, blockFilter]);
}

function useValueTexts(data: RowInspectorData) {
  const t = useTranslations("templates.elementEditor");
  const describe = useListValueDescriber(data.participants, data.events);
  const names = (ids: string[] | null | undefined) =>
    data.participants.filter((participant) => (ids ?? []).includes(participant.id)).map((participant) => participant.display_name).join(", ");

  function eventFieldValue(event: EventSummary | null, field: string): string {
    if (!event) return "";
    const raw = (event as unknown as Record<string, unknown>)[field];
    if (field.endsWith("_ids")) return names(raw as string[] | null);
    if (field === "event_date" || field === "event_end_date") return raw ? formatDate(String(raw)) : "";
    if (TIME_FIELDS.has(field)) return formatTimeValue(raw as string | null);
    // Markdown der Termintexte als Klartext; formatiert erscheint er im Protokoll und im PDF
    if (MARKDOWN_FIELDS.has(field)) return markdownToPlainText(raw as string | null);
    return raw === null || raw === undefined ? "" : String(raw);
  }

  function todoFieldValue(todo: TodoListItem, field: string): string {
    if (field === "task") return todo.task;
    if (field === "description") return todo.reference_link ?? "";
    if (field === "participant") return todo.assigned_participant_name ?? "";
    if (field === "due_date") return todo.due_date ? formatDate(todo.due_date) : todo.resolved_due_label ?? todo.due_marker ?? "";
    if (field === "status") return todo.todo_status_code ? t(`todoStatus.${todo.todo_status_code}`) : "";
    if (field === "origin") return todoOrigin(todo);
    return "";
  }

  /** Wert eines Quellfelds (Termin oder Pendenz) für Beispiel und Vorschau. */
  function sourceFieldValue(item: SourceItem | null, field: string): string {
    if (!item) return "";
    return item.kind === "event" ? eventFieldValue(item.event, field) : todoFieldValue(item.todo, field);
  }

  function listParts(row: TableRow): { list: StructuredListDefinition | null; fixed: string; other: string } {
    const listId = typeof row.row_config.linked_list_id === "string" ? row.row_config.linked_list_id : null;
    const list = data.lists.find((entry) => entry.id === listId) ?? null;
    const entryId = row.row_config.linked_list_entry_id;
    const entry = listId ? (data.listEntries[listId] ?? []).find((item) => item.id === entryId) : undefined;
    if (!list || !entry) return { list, fixed: "", other: "" };
    // Feste Spalte (Beschriftung) und Wert-Spalte: Spalten-Keys der Zeile, sonst Rolle «Bezeichnung»
    const columns = orderedListColumns(list);
    const fixedColumn = columns.find((column) => column.id === row.row_config.list_fixed_column)
      ?? columns.find((column) => column.id === list.label_column_id) ?? columns[0];
    const otherColumn = columns.find((column) => column.id === row.row_config.list_value_column && column.id !== fixedColumn?.id)
      ?? columns.find((column) => column.id !== fixedColumn?.id);
    const valueOf = (column: ListColumn | undefined) => (column ? describe(entry.values?.[column.id], column.value_type) : "");
    return { list, fixed: valueOf(fixedColumn), other: valueOf(otherColumn) };
  }

  /** Bezeichnung und Vorbelegung einer eigenen Zeile, wie sie im Protokoll erscheint. */
  function rowPreview(row: TableRow, item: SourceItem | null): { label: string; value: string } {
    if (row.row_type === "list_entry") {
      const parts = listParts(row);
      return { label: row.label || parts.fixed, value: parts.other };
    }
    let value = "";
    if (row.row_type === "text") value = resolveSourceTokens(row.template_value, item);
    if (row.row_type === "participant") value = data.participants.find((participant) => participant.id === row.template_participant_id)?.display_name ?? "";
    if (row.row_type === "participants") value = names(row.template_participant_ids);
    if (row.row_type === "event") {
      const chosen = data.events.find((entry) => entry.id === row.template_event_id);
      value = chosen ? `${formatDateRange(chosen.event_date, chosen.event_end_date)} · ${chosen.title}` : "";
    }
    return { label: row.label, value };
  }

  return { sourceFieldValue, rowPreview, describe };
}

function LinkIcon({ size = 13 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
      <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" />
      <path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" />
    </svg>
  );
}

function RowsIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
      <path d="M4 7h16M4 12h16M4 17h10" />
    </svg>
  );
}

function LockIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
      <rect x="5" y="11" width="14" height="10" rx="2" />
      <path d="M8 11V8a4 4 0 0 1 8 0v3" />
    </svg>
  );
}

function Chevron() {
  return (
    <svg className="table-block-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}

/** Menü «+ Feld aus Termin»: Felder gruppiert an- und abwählen, jeder Klick gilt sofort. */
function SourceFieldMenu({
  kind,
  fields,
  labelOf,
  isAlias,
  hidden,
  onToggle,
}: {
  kind: "event" | "todo";
  fields: EventFieldConfig[];
  labelOf: (field: string) => string;
  isAlias: (field: string) => boolean;
  hidden: (field: string) => boolean;
  onToggle: (field: string, enabled: boolean) => void;
}) {
  const t = useTranslations("templates.elementEditor");
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const style = usePopoverPosition(open, triggerRef, "end", 6, { minWidth: 300, estimatedHeight: 420 });
  usePopoverDismiss(open, () => setOpen(false), [triggerRef, panelRef]);
  const enabled = (field: string) => fields.some((entry) => entry.field === field && entry.enabled);

  return (
    <>
      <button ref={triggerRef} type="button" className="button-secondary table-block-add-field" aria-expanded={open} onClick={() => setOpen((current) => !current)}>
        {kind === "todo" ? t("tableBlock.addTodoField") : t("tableBlock.addEventField")}
      </button>
      {open && typeof document !== "undefined"
        ? createPortal(
            <div ref={panelRef} className="mini-menu-popover-portal table-block-field-menu" style={style} role="menu">
              {(kind === "todo" ? [{ key: "todo", fields: TODO_FIELDS as readonly string[] }] : (FIELD_GROUPS as Array<{ key: string; fields: readonly string[] }>)).map((group) => (
                <div key={group.key} className="mini-menu-section">
                  <div className="mini-menu-section-title">{t(`tableBlock.fieldGroup.${group.key}`)}</div>
                  {group.fields
                    .filter((field) => !hidden(field) || enabled(field))
                    .map((field) => {
                      const on = enabled(field);
                      return (
                        <button
                          key={field}
                          type="button"
                          role="menuitemcheckbox"
                          aria-checked={on}
                          className={`mini-menu-option table-block-field-option${on ? " mini-menu-option-active" : ""}`}
                          onClick={() => onToggle(field, !on)}
                        >
                          <span className={`table-block-check${on ? " table-block-check-on" : ""}`} aria-hidden="true">
                            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5"><path d="M5 12l5 5 9-10" /></svg>
                          </span>
                          <span className="table-block-field-option-label">{labelOf(field)}</span>
                          {isAlias(field) ? <span className="mini-menu-option-subtle">{t("tableBlock.aliasOf", { name: t(`eventField.${field}`) })}</span> : null}
                        </button>
                      );
                    })}
                </div>
              ))}
              <p className="field-help table-block-field-menu-note">{kind === "todo" ? t("tableBlock.todoMenuNote") : t("tableBlock.aliasNote")}</p>
            </div>,
            document.body
          )
        : null}
    </>
  );
}

export function TableBlockSection({
  form,
  onChange,
  data,
  openKey,
  onOpenKey,
  previewItem,
}: {
  form: BlockForm;
  onChange: (next: BlockForm) => void;
  data: RowInspectorData;
  /** Aufgeklappte Zeile: "e:<feld>" (Terminfeld) oder "r:<id>" (eigene Zeile). */
  openKey: string | null;
  onOpenKey: (key: string | null) => void;
  /** Termin bzw. Pendenz der Vorschau, für Beispielwerte und aufgelöste Platzhalter. */
  previewItem: SourceItem | null;
}) {
  const t = useTranslations("templates.elementEditor");
  const eventFieldConfig = useEventFieldConfig();
  const { sourceFieldValue, rowPreview } = useValueTexts(data);
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const setConfig = (next: Record<string, unknown>) => onChange({ ...form, config: { ...form.config, ...next } });
  const rows = (form.config.rows ?? []) as TableRow[];
  const setRows = (next: TableRow[]) => setConfig({ rows: next });
  const linkedListId = (form.config.linked_list_id as string | null) ?? null;
  const linkedList = data.lists.find((list) => list.id === linkedListId) ?? null;
  // Zuletzt gewählte Liste merken, damit «Eigene Zeilen» ↔ «Globale Liste» nichts verliert.
  const lastList = useRef<string | null>(linkedListId);
  useEffect(() => {
    if (linkedListId) lastList.current = linkedListId;
  }, [linkedListId]);
  // Quelle der Zeilen zuoberst: nur bei «Pro Termin» bzw. «Pro Pendenz»
  const sourceKind = form.config.repeat_source === "event" ? "event" : form.config.repeat_source === "todo" ? "todo" : null;
  const isTodo = sourceKind === "todo";
  const fieldsKey = isTodo ? "todo_fields" : "event_fields";
  const fields = isTodo ? todoFieldsOf(form) : eventFieldsOf(form);
  const enabledFields = fields.filter((field) => field.enabled);
  const fieldName = (field: string) => (isTodo ? t(`todoField.${field}`) : eventFieldConfig.label(field, t(`eventField.${field}`)));
  const isAlias = (field: string) => !isTodo && fieldName(field) !== t(`eventField.${field}`);

  // Listeneinträge für Zeilen «Zeile aus Liste» laden, damit Kopf und Vorschau Werte zeigen.
  useEffect(() => {
    for (const row of rows) {
      const listId = row.row_type === "list_entry" && typeof row.row_config.linked_list_id === "string" ? row.row_config.linked_list_id : null;
      if (listId && !data.listEntries[listId]) data.ensureListEntries(listId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, data.listEntries]);

  const toggleOpen = (key: string) => onOpenKey(openKey === key ? null : key);
  const setField = (field: string, next: Partial<EventFieldConfig>) =>
    setConfig({ [fieldsKey]: fields.map((entry) => (entry.field === field ? { ...entry, ...next } : entry)) });
  const updateRow = (next: TableRow) => setRows(rows.map((row) => (row.id === next.id ? next : row)));
  const moveRow = (index: number, offset: number) => setRows(moveItem(rows, index, index + offset));
  const addRow = () => {
    const row = defaultRow(nextRowId(rows));
    setRows([...rows, row]);
    onOpenKey(`r:${row.id}`);
  };
  const dropOn = (event: DragEvent, targetId: string) => {
    event.preventDefault();
    if (draggedId && draggedId !== targetId) {
      setRows(moveItem(rows, rows.findIndex((row) => row.id === draggedId), rows.findIndex((row) => row.id === targetId)));
    }
    setDraggedId(null);
  };
  const chooseSource = (source: "manual" | "list") => {
    if (source === "manual") setConfig({ linked_list_id: null });
    else setConfig({ linked_list_id: lastList.current ?? data.lists[0]?.id ?? null });
  };
  const source = linkedListId ? "list" : "manual";

  return (
    <section className="settings-section table-block">
      <div className="settings-section-head">
        <div className="settings-section-copy">
          <h3>{t("table.title")}</h3>
          <p className="muted">{source === "list" ? t("table.linkedDescription") : t("tableBlock.description")}</p>
        </div>
        <div className="settings-section-actions">
          <FilterTabs
            value={source}
            onChange={chooseSource}
            options={[
              { value: "manual", label: t("tableBlock.source.manual") },
              { value: "list", label: t("tableBlock.source.list") },
            ]}
          />
        </div>
      </div>

      {source === "manual" ? (
        <div className="settings-section-body table-block-body">
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("table.leftHeading")}</span>
              <input value={String(form.config.left_column_heading ?? "")} onChange={(event) => setConfig({ left_column_heading: event.target.value })} placeholder={t("table.noHeading")} />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("table.rightHeading")}</span>
              <input value={String(form.config.value_column_heading ?? "")} onChange={(event) => setConfig({ value_column_heading: event.target.value })} placeholder={t("table.noHeading")} />
            </label>
          </div>

          {sourceKind ? (
          <div className="table-block-group">
            <div className="table-block-group-head">
              <div className="table-block-group-title">
                <span className="table-block-group-icon table-block-group-icon-event"><LinkIcon /></span>
                <strong>{isTodo ? t("tableBlock.todoRows") : t("tableBlock.eventRows")}</strong>
                <span className="muted">{t("tableBlock.eventRowsCount", { count: enabledFields.length })}</span>
              </div>
              <SourceFieldMenu
                kind={sourceKind}
                fields={fields}
                labelOf={fieldName}
                isAlias={isAlias}
                hidden={isTodo ? () => false : eventFieldConfig.hidden}
                onToggle={(field, enabled) => {
                  setField(field, { enabled });
                  if (enabled) onOpenKey(`e:${field}`);
                }}
              />
            </div>

            {enabledFields.length === 0 ? (
              <div className="table-block-note table-block-note-event">{isTodo ? t("tableBlock.todoRowsEmpty") : t("tableBlock.eventRowsEmpty")}</div>
            ) : (
              enabledFields.map((field) => {
                const key = `e:${field.field}`;
                const open = openKey === key;
                const value = sourceFieldValue(previewItem, field.field);
                const name = fieldName(field.field);
                return (
                  <div key={key} className={`table-block-row table-block-row-event${open ? " table-block-row-open" : ""}`}>
                    <button type="button" className="table-block-row-head" aria-expanded={open} onClick={() => toggleOpen(key)}>
                      <span className="table-block-row-lead table-block-row-lead-event"><LinkIcon size={15} /></span>
                      <span className="table-block-row-text">
                        <span className="table-block-row-label">{field.label || name}</span>
                        <span className="table-block-row-sub">{isTodo ? t("tableBlock.fromTodo", { field: name }) : t("tableBlock.fromEvent", { field: name })}</span>
                      </span>
                      <span className={`table-block-row-sample${value ? "" : " table-block-row-sample-empty"}`}>
                        {previewItem ? value || t("tableBlock.emptyAtEvent", { title: sourceTitle(previewItem) }) : "—"}
                      </span>
                      <Chevron />
                    </button>
                    {open ? (
                      <div className="table-block-row-body">
                        <label className="field-stack table-block-narrow">
                          <span className="field-label">{t("tableBlock.eventFieldLabel")}</span>
                          <input value={field.label} placeholder={name} onChange={(event) => setField(field.field, { label: event.target.value })} />
                          <span className="field-help">{t("tableBlock.emptyUses", { name })}</span>
                        </label>
                        <p className="field-help">
                          {field.field.endsWith("_ids") ? `${t("tableBlock.eventFieldPeopleNote")} ` : ""}
                          {isTodo ? t("tableBlock.todoFieldNote") : t("tableBlock.eventFieldNote")}
                        </p>
                        <div className="table-block-row-actions table-block-row-actions-end">
                          <button type="button" className="button-ghost button-danger" onClick={() => { setField(field.field, { enabled: false }); onOpenKey(null); }}>
                            {t("tableBlock.removeField")}
                          </button>
                        </div>
                      </div>
                    ) : null}
                  </div>
                );
              })
            )}
          </div>
          ) : null}

          <div className="table-block-group">
            <div className="table-block-group-head">
              <div className="table-block-group-title">
                <span className="table-block-group-icon"><RowsIcon /></span>
                <strong>{t("tableBlock.ownRows")}</strong>
                <span className="muted">{t("designer.countTable", { rows: rows.length })}</span>
              </div>
              <span className="field-help">{t("tableBlock.dragHint")}</span>
            </div>

            {rows.map((row, index) => {
              const key = `r:${row.id}`;
              const open = openKey === key;
              const preview = rowPreview(row, previewItem);
              const isList = row.row_type === "list_entry";
              const label = isList ? (row.label || (preview.label ? t("tableBlock.fromList", { label: preview.label }) : t("rowType.list_entry"))) : row.label || t("row.unnamed");
              const typeName = t(`rowType.${row.row_type}`);
              return (
                <div
                  key={key}
                  draggable
                  onDragStart={(event) => { event.dataTransfer.effectAllowed = "move"; setDraggedId(row.id); }}
                  onDragOver={(event) => event.preventDefault()}
                  onDrop={(event) => dropOn(event, row.id)}
                  onDragEnd={() => setDraggedId(null)}
                  className={`table-block-row${open ? " table-block-row-open" : ""}${draggedId === row.id ? " table-block-row-dragging" : ""}`}
                >
                  <button type="button" className="table-block-row-head" aria-expanded={open} onClick={() => toggleOpen(key)}>
                    <span className="table-block-row-lead table-block-row-number">{index + 1}</span>
                    <span className="table-block-row-text">
                      <span className="table-block-row-label">{label}</span>
                      <span className="table-block-row-sub">{row.locked_in_protocol ? t("row.typeLocked", { type: typeName }) : typeName}</span>
                    </span>
                    <span className={`table-block-row-sample${preview.value ? "" : " table-block-row-sample-empty"}`}>
                      {preview.value || (row.row_type === "text" ? t("tableBlock.fillInProtocol") : t("row.noDefault"))}
                    </span>
                    <Chevron />
                  </button>
                  {open ? (
                    <div className="table-block-row-body">
                      <label className="field-stack table-block-narrow">
                        <span className="field-label">{isList ? t("row.aliasLabel") : t("row.label")}</span>
                        <input
                          value={row.label}
                          onChange={(event) => updateRow({ ...row, label: event.target.value })}
                          placeholder={isList ? t("row.aliasPlaceholder") : t("row.labelPlaceholder")}
                        />
                      </label>
                      <div className="field-stack">
                        <span className="field-label">{t("row.type")}</span>
                        <div className="matrix-designer-chips" role="radiogroup" aria-label={t("row.type")}>
                          {TABLE_ROW_TYPES.map((type) => (
                            <button
                              key={type}
                              type="button"
                              role="radio"
                              aria-checked={row.row_type === type}
                              className={`matrix-designer-chip${row.row_type === type ? " matrix-designer-chip-active" : ""}`}
                              onClick={() => { if (row.row_type !== type) updateRow({ ...row, row_type: type, row_config: defaultRowConfig(type) }); }}
                            >
                              {t(`rowType.${type}`)}
                            </button>
                          ))}
                        </div>
                        <span className="field-help">{t(`tableBlock.rowTypeHelp.${row.row_type}`)}</span>
                      </div>
                      <div className="table-block-row-values">
                        <RowValueFields row={row} data={data} onChange={updateRow} />
                        {row.row_type === "text" && previewItem && row.template_value.includes("{") ? (
                          <span className="field-help">{t("tableBlock.resolvedAt", { title: sourceTitle(previewItem), value: resolveSourceTokens(row.template_value, previewItem) })}</span>
                        ) : null}
                      </div>
                      <div className="table-block-row-actions">
                        <label className="matrix-designer-switch-row">
                          <input
                            type="checkbox"
                            className="mini-menu-switch-input"
                            checked={row.locked_in_protocol}
                            onChange={(event) => updateRow({ ...row, locked_in_protocol: event.target.checked })}
                          />
                          <span className="mini-menu-switch" aria-hidden="true" />
                          <span>{t("row.locked")}</span>
                        </label>
                        <div className="table-block-row-buttons">
                          <button type="button" className="button-icon-soft" aria-label={t("tableBlock.moveUp")} disabled={index === 0} onClick={() => moveRow(index, -1)}>↑</button>
                          <button type="button" className="button-icon-soft" aria-label={t("tableBlock.moveDown")} disabled={index === rows.length - 1} onClick={() => moveRow(index, 1)}>↓</button>
                          <button type="button" className="button-ghost button-danger" onClick={() => { setRows(rows.filter((entry) => entry.id !== row.id)); onOpenKey(null); }}>
                            {t("remove")}
                          </button>
                        </div>
                      </div>
                    </div>
                  ) : null}
                </div>
              );
            })}

            <button type="button" className="table-block-add-row" onClick={addRow}>{t("designer.addRowLong")}</button>
          </div>
        </div>
      ) : (
        <div className="settings-section-body table-block-body">
          {data.lists.length ? (
            <div className="rule-option-grid">
              {data.lists.map((list) => (
                <button
                  key={list.id}
                  type="button"
                  className={`rule-option-card${list.id === linkedListId ? " rule-option-card-active" : ""}`}
                  aria-pressed={list.id === linkedListId}
                  onClick={() => setConfig({ linked_list_id: list.id })}
                >
                  <strong>{list.name}</strong>
                  <span className="muted">{orderedListColumns(list).map((column) => column.title).join(" · ")}</span>
                </button>
              ))}
            </div>
          ) : (
            <p className="muted">{t("tableBlock.noLists")}</p>
          )}
          {linkedList ? <LinkedListOptions form={form} list={linkedList} setConfig={setConfig} /> : null}
        </div>
      )}
    </section>
  );
}

function orderedListColumns(list: StructuredListDefinition): ListColumn[] {
  return [...list.columns].sort((left, right) => left.sort_index - right.sort_index);
}

function LinkedListOptions({ form, list, setConfig }: { form: BlockForm; list: StructuredListDefinition; setConfig: (next: Record<string, unknown>) => void }) {
  const t = useTranslations("templates.elementEditor");
  const columns = orderedListColumns(list);
  const columnOptions = columns.map((column) => <option key={column.id} value={column.id}>{column.title}</option>);
  const visible = Array.isArray(form.config.linked_list_visible_columns) ? (form.config.linked_list_visible_columns as string[]) : [];
  return (
    <div className="card grid">
      {columns.length > 2 ? (
        <label className="field-stack">
          <span className="field-label">{t("table.visibleColumns")}</span>
          <SearchableMultiSelect
            options={columns}
            getId={(column) => column.id}
            getLabel={(column) => column.title}
            values={visible.filter((key) => columns.some((column) => column.id === key))}
            onChange={(ids) => setConfig({ linked_list_visible_columns: ids.length ? ids : null })}
            emptySelectionLabel={t("table.allColumns")}
          />
        </label>
      ) : null}
      <div className="three-col">
        <label className="field-stack">
          <span className="field-label">{t("table.groupBy")}</span>
          <Select value={String(form.config.linked_list_group_by ?? "")} onChange={(event) => setConfig({ linked_list_group_by: event.target.value || null })}>
            <option value="">{t("table.noGrouping")}</option>
            {columnOptions}
          </Select>
        </label>
        <label className="field-stack">
          <span className="field-label">{t("table.sortBy")}</span>
          <Select
            value={String(form.config.linked_list_sort_by ?? "")}
            onChange={(event) => setConfig({ linked_list_sort_by: event.target.value || null, linked_list_sort_direction: event.target.value ? form.config.linked_list_sort_direction ?? "asc" : null })}
          >
            <option value="">{t("table.manualOrder")}</option>
            {columnOptions}
          </Select>
        </label>
        <label className="field-stack">
          <span className="field-label">{t("table.sortDirection")}</span>
          <Select value={String(form.config.linked_list_sort_direction ?? "asc")} disabled={!form.config.linked_list_sort_by} onChange={(event) => setConfig({ linked_list_sort_direction: event.target.value })}>
            <option value="asc">{t("table.sortAsc")}</option>
            <option value="desc">{t("table.sortDesc")}</option>
          </Select>
        </label>
      </div>
      <div className="two-col">
        <label className="field-stack">
          <span className="field-label">{t("table.filterColumn")}</span>
          <Select value={String(form.config.linked_list_filter_column ?? "")} onChange={(event) => setConfig({ linked_list_filter_column: event.target.value || null })}>
            <option value="">{t("table.noFilter")}</option>
            {columnOptions}
          </Select>
        </label>
        {form.config.linked_list_filter_column ? (
          <label className="field-stack">
            <span className="field-label">{t("table.filterText")}</span>
            <input value={String(form.config.linked_list_filter_text ?? "")} onChange={(event) => setConfig({ linked_list_filter_text: event.target.value })} placeholder={t("filter.containsPlaceholder")} />
          </label>
        ) : null}
      </div>
      <label className="checkbox-row">
        <input type="checkbox" checked={form.config.linked_list_highlight_empty === true} onChange={(event) => setConfig({ linked_list_highlight_empty: event.target.checked })} />
        {t("table.highlightEmpty")}
      </label>
      <p className="muted">{t("tableBlock.linkedOptionsHelp")}</p>
    </div>
  );
}

type PreviewRow = { key: string; label: string; value: string; fromEvent: boolean; locked: boolean; rowType: string };

/** Vorschau rechts: Tabelle wie im Protokoll-Editor oder im PDF, bei «Pro Termin»/«Pro Pendenz» für eine Quelle. */
export function TableBlockPreview({
  form,
  data,
  elementTitle,
  matching,
  previewIndex,
  onPreviewIndex,
  openKey,
  onOpenKey,
}: {
  form: BlockForm;
  data: RowInspectorData;
  elementTitle: string;
  matching: SourceItem[];
  previewIndex: number;
  onPreviewIndex: (index: number) => void;
  openKey: string | null;
  onOpenKey: (key: string) => void;
}) {
  const t = useTranslations("templates.elementEditor");
  const eventFieldConfig = useEventFieldConfig();
  const { sourceFieldValue, rowPreview, describe } = useValueTexts(data);
  const [mode, setMode] = useState<"editor" | "pdf">("editor");
  const pdf = mode === "pdf";
  const sourceKind = form.config.repeat_source === "event" ? "event" : form.config.repeat_source === "todo" ? "todo" : null;
  const isTodo = sourceKind === "todo";
  const item = sourceKind ? matching[Math.min(previewIndex, Math.max(0, matching.length - 1))] ?? null : null;
  // Bei «Pro Pendenz» sind die Pendenzen nur Beispiele - ohne Beispiel bleibt die Tabelle sichtbar
  const noMatch = sourceKind === "event" && matching.length === 0;
  const linkedList = data.lists.find((list) => list.id === form.config.linked_list_id) ?? null;
  const rows = (form.config.rows ?? []) as TableRow[];
  const leftHeading = String(form.config.left_column_heading ?? "");
  const rightHeading = String(form.config.value_column_heading ?? "");
  const heading = resolveSourceTokens(form.block_title || form.title, item);

  useEffect(() => {
    if (linkedList && !data.listEntries[linkedList.id]) data.ensureListEntries(linkedList.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linkedList?.id, data.listEntries]);

  let previewRows: PreviewRow[] = [];
  if (sourceKind) {
    for (const field of (isTodo ? todoFieldsOf(form) : eventFieldsOf(form)).filter((entry) => entry.enabled)) {
      previewRows.push({
        key: `e:${field.field}`,
        label: field.label || (isTodo ? t(`todoField.${field.field}`) : eventFieldConfig.label(field.field, t(`eventField.${field.field}`))),
        value: sourceFieldValue(item, field.field),
        fromEvent: true,
        locked: false,
        rowType: "event_field",
      });
    }
  }
  rows.forEach((row, index) => {
    const preview = rowPreview(row, item);
    previewRows.push({
      key: `r:${row.id}`,
      label: preview.label || t("row.numbered", { number: index + 1 }),
      value: preview.value,
      fromEvent: false,
      locked: row.locked_in_protocol || !form.is_editable,
      rowType: row.row_type,
    });
  });
  const hiddenCount = pdf ? previewRows.filter((row) => !row.value.trim()).length : 0;
  if (pdf) previewRows = previewRows.filter((row) => row.value.trim());
  const showHead = pdf ? Boolean(leftHeading || rightHeading) : true;

  const notes: string[] = [];
  if (linkedList) notes.push(t("tableBlock.preview.listNote", { name: linkedList.name }));
  else if (pdf) notes.push(hiddenCount ? t("tableBlock.preview.hiddenRows", { count: hiddenCount }) : t("tableBlock.preview.allFilled"));
  else {
    if (previewRows.some((row) => row.fromEvent)) notes.push(isTodo ? t("tableBlock.preview.linkNoteTodo") : t("tableBlock.preview.linkNote"));
    notes.push(t("tableBlock.preview.clickNote"));
  }

  return (
    <section className="element-create-preview table-block-preview">
      <div className="table-block-preview-head">
        <h3>{t("preview.title")}</h3>
        <FilterTabs
          value={mode}
          onChange={setMode}
          options={[
            { value: "editor", label: t("tableBlock.preview.editor") },
            { value: "pdf", label: t("tableBlock.preview.pdf") },
          ]}
        />
      </div>

      {sourceKind && matching.length ? (
        <div className="table-block-preview-events">
          <span className="field-help">
            {matching.length > 1 ? (isTodo ? t("tableBlock.preview.perTodo") : t("tableBlock.preview.perEvent")) : t("tableBlock.preview.oneEvent")}
          </span>
          <div className="table-block-event-chips">
            {matching.map((entry, index) => (
              <button
                key={entry.kind === "event" ? entry.event.id : entry.todo.id}
                type="button"
                aria-pressed={entry === item}
                className={`table-block-event-chip${entry === item ? " table-block-event-chip-active" : ""}`}
                onClick={() => onPreviewIndex(index)}
              >
                <span className="table-block-event-chip-date">
                  {entry.kind === "event"
                    ? formatDateRange(entry.event.event_date, entry.event.event_end_date)
                    : t("tableBlock.preview.todoChip", {
                        due: entry.todo.due_date ? t("tableBlock.preview.todoDue", { date: formatDate(entry.todo.due_date) }) : t("tableBlock.preview.todoNoDue"),
                        status: entry.todo.todo_status_code ? t(`todoStatus.${entry.todo.todo_status_code}`) : "",
                      })}
                </span>
                <span className="table-block-event-chip-title">{sourceTitle(entry)}</span>
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div className="element-create-paper table-block-paper">
        <h4>{elementTitle.trim() || t("preview.newElement")}</h4>
        {heading.trim() && !noMatch ? (
          <strong className={form.title_as_subtitle ? "table-block-paper-subtitle" : undefined}>{heading}</strong>
        ) : null}
        {!pdf && form.description.trim() && !noMatch ? <p className="field-help table-block-paper-hint">{form.description}</p> : null}

        {noMatch ? (
          <div className="table-block-no-match">{t("tableBlock.preview.noMatch")}</div>
        ) : linkedList ? (
          <LinkedListPreview form={form} list={linkedList} entries={data.listEntries[linkedList.id] ?? []} describe={describe} />
        ) : (
          <div className={`table-block-table${pdf ? " table-block-table-pdf" : ""}`} role="table">
            {showHead ? (
              <div className="table-block-table-row table-block-table-head" role="row">
                <span role="columnheader" className={leftHeading ? undefined : "table-block-table-head-empty"}>{leftHeading || (pdf ? "" : t("table.rowWord"))}</span>
                <span role="columnheader" className={rightHeading ? undefined : "table-block-table-head-empty"}>{rightHeading || (pdf ? "" : t("table.valueWord"))}</span>
              </div>
            ) : null}
            {previewRows.map((row) => (
              <div
                key={row.key}
                role="row"
                tabIndex={pdf ? undefined : 0}
                className={`table-block-table-row${!pdf && openKey === row.key ? " table-block-table-row-active" : ""}${pdf ? "" : " table-block-table-row-clickable"}`}
                onClick={pdf ? undefined : () => onOpenKey(row.key)}
                onKeyDown={pdf ? undefined : (keyEvent) => { if (keyEvent.key === "Enter" || keyEvent.key === " ") { keyEvent.preventDefault(); onOpenKey(row.key); } }}
              >
                <span role="cell" className="table-block-table-label">
                  {!pdf && row.fromEvent ? <span className="table-block-link"><LinkIcon size={12} /></span> : null}
                  <span>{row.label}</span>
                </span>
                <span role="cell" className="table-block-table-value-cell">
                  <span
                    className={`table-block-table-value${pdf ? "" : row.fromEvent ? " table-block-cell-event" : row.locked ? "" : " table-block-cell-field"}${row.value ? "" : " table-block-table-value-empty"}${!pdf && row.locked ? " table-block-cell-locked" : ""}`}
                  >
                    <span>{row.value || (pdf ? "" : row.fromEvent ? (isTodo ? t("tableBlock.preview.emptyAtTodo") : t("tableBlock.preview.emptyAtEvent")) : t(`tableBlock.preview.placeholder.${row.rowType}`))}</span>
                    {!pdf && row.locked ? <span className="table-block-lock"><LockIcon /></span> : null}
                  </span>
                </span>
              </div>
            ))}
            {previewRows.length === 0 ? <div className="table-block-table-empty">{t("table.noRows")}</div> : null}
          </div>
        )}
      </div>
      {notes.length ? (
        <div className="table-block-preview-notes">
          {notes.map((note) => <span key={note}>{note}</span>)}
        </div>
      ) : null}
    </section>
  );
}

function LinkedListPreview({
  form,
  list,
  entries,
  describe,
}: {
  form: BlockForm;
  list: StructuredListDefinition;
  entries: StructuredListEntry[];
  describe: (value: Record<string, unknown> | null | undefined, valueType: string) => string;
}) {
  const t = useTranslations("templates.elementEditor");
  const highlight = form.config.linked_list_highlight_empty === true;
  // Sichtbare Spalten des Blocks (sonst alle); Gruppieren/Sortieren/Filtern über Spalten-Keys
  const allColumns = orderedListColumns(list);
  const chosen = Array.isArray(form.config.linked_list_visible_columns)
    ? (form.config.linked_list_visible_columns as string[]).map((key) => allColumns.find((column) => column.id === key)).filter((column): column is ListColumn => Boolean(column))
    : [];
  const shown = chosen.length ? chosen : allColumns;
  const columnIndex = (value: unknown) => shown.findIndex((column) => column.id === value);
  let values = entries.map((entry) => shown.map((column) => describe(entry.values?.[column.id], column.value_type)));
  const filterColumn = columnIndex(form.config.linked_list_filter_column);
  const filterText = String(form.config.linked_list_filter_text ?? "").trim().toLowerCase();
  if (filterColumn >= 0 && filterText) values = values.filter((entry) => entry[filterColumn].toLowerCase().includes(filterText));
  const sortColumn = columnIndex(form.config.linked_list_sort_by);
  if (sortColumn >= 0) {
    const direction = form.config.linked_list_sort_direction === "desc" ? -1 : 1;
    values = [...values].sort((left, right) => left[sortColumn].localeCompare(right[sortColumn]) * direction);
  }
  const groupColumn = columnIndex(form.config.linked_list_group_by);
  const groups: Array<{ name: string | null; rows: string[][] }> = [];
  if (groupColumn >= 0) {
    for (const entry of values) {
      const name = entry[groupColumn] || t("tableBlock.preview.noValue");
      const group = groups.find((item) => item.name === name);
      if (group) group.rows.push(entry);
      else groups.push({ name, rows: [entry] });
    }
  } else {
    groups.push({ name: null, rows: values });
  }

  return (
    <div className="table-block-table table-block-table-list" role="table">
      <div className="table-block-table-row table-block-table-head" role="row" style={{ gridTemplateColumns: `repeat(${shown.length}, minmax(0, 1fr))` }}>
        {shown.map((column) => <span key={column.id} role="columnheader">{column.title}</span>)}
      </div>
      {groups.map((group, groupIndex) => (
        <div key={group.name ?? groupIndex} role="rowgroup">
          {group.name !== null ? <div className="table-block-table-group">{group.name}</div> : null}
          {group.rows.map((entry, index) => (
            <div key={index} className="table-block-table-row" role="row" style={{ gridTemplateColumns: `repeat(${shown.length}, minmax(0, 1fr))` }}>
              {entry.map((cell, cellIndex) => (
                <span key={shown[cellIndex].id} role="cell" className={!cell && highlight ? "table-block-table-missing" : undefined}>
                  {cell || (highlight ? t("tableBlock.preview.missing") : cellIndex === 0 ? "—" : "")}
                </span>
              ))}
            </div>
          ))}
        </div>
      ))}
      {values.length === 0 ? <div className="table-block-table-empty">{t("table.noRows")}</div> : null}
    </div>
  );
}
