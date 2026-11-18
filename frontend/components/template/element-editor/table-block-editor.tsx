"use client";

// Tabellenblock (Typ 6) im Block-Editor: Zeilen werden direkt im Dialog aufgeklappt und bearbeitet
// (früher in einem eigenen Designer), Terminfelder stehen als eigene Gruppe zuoberst, und die
// Vorschau rechts zeigt die Tabelle wie im Protokoll-Editor oder im PDF, bei «Pro Termin» für
// einen der aktuell passenden Termine. Gespeichert wird unverändert in form.config (rows,
// event_fields, linked_list_*), siehe block-form.ts.
import { type DragEvent, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslations } from "next-intl";

import { FilterTabs } from "@/components/ui/filter-tabs";
import { usePopoverDismiss, usePopoverPosition } from "@/components/ui/popover";
import { Select } from "@/components/ui/select";
import { applyEventFilter } from "@/lib/element-types/event-filter";
import { useEventFieldConfig } from "@/lib/hooks/use-event-field-config";
import { formatDate, formatDateRange } from "@/lib/utils/format";
import type { EventSummary, StructuredListDefinition, StructuredListEntry } from "@/types/api";

import { type BlockForm, defaultRow, defaultRowConfig, moveItem, nextRowId, repeatEventFilter, type TableRow } from "./block-form";
import { RowValueFields, type RowInspectorData, useListValueDescriber } from "./row-inspector";

export const EVENT_FIELDS = [
  "title", "description", "event_date", "event_end_date", "tag", "participant_count", "organizer_ids", "leadership_ids",
  "participant_ids", "spezial1_ids", "spezial2_ids", "spezial3_ids", "location", "spezial_text1", "spezial_text2", "spezial_text3",
] as const;

type EventField = (typeof EVENT_FIELDS)[number];
type EventFieldConfig = { field: string; label: string; enabled: boolean };

const FIELD_GROUPS: Array<{ key: "event" | "people" | "texts"; fields: EventField[] }> = [
  { key: "event", fields: ["title", "description", "event_date", "event_end_date", "tag", "participant_count", "location"] },
  { key: "people", fields: ["organizer_ids", "leadership_ids", "participant_ids", "spezial1_ids", "spezial2_ids", "spezial3_ids"] },
  { key: "texts", fields: ["spezial_text1", "spezial_text2", "spezial_text3"] },
];

/** Zeilentypen einer Tabelle (Matrix hat zusätzlich «Mehrere Termine» und eingebettete Blöcke). */
const TABLE_ROW_TYPES = ["text", "participant", "participants", "event", "list_entry"] as const;

export const EVENT_TOKENS = ["{title}", "{description}", "{event_date}", "{event_end_date}", "{tag}", "{id}"];

type TFunc = (key: string, values?: Record<string, string | number>) => string;

export function eventFieldsOf(form: BlockForm): EventFieldConfig[] {
  const saved = Array.isArray(form.config.event_fields) ? (form.config.event_fields as EventFieldConfig[]) : [];
  return EVENT_FIELDS.map((field) => saved.find((entry) => entry.field === field) ?? { field, label: "", enabled: false });
}

/** Platzhalter eines Termins ersetzen wie beim Erstellen des Protokolls. */
export function resolveEventTokens(text: string, event: EventSummary | null): string {
  if (!event) return text;
  return text
    .replace(/\{title\}/g, event.title)
    .replace(/\{description\}/g, event.description ?? "")
    .replace(/\{event_date\}/g, formatDate(event.event_date))
    .replace(/\{event_end_date\}/g, event.event_end_date ? formatDate(event.event_end_date) : "")
    .replace(/\{tag\}/g, event.tag ?? "")
    .replace(/\{id\}/g, event.id);
}

function todayIso() {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** Termine, für die bei «Pro Termin» heute ein Block entstünde (Zyklus wird in der Vorlage nicht ausgewertet). */
export function useMatchingEvents(form: BlockForm, events: EventSummary[]): EventSummary[] {
  const repeat = String(form.config.repeat_source ?? "none");
  const filter = repeatEventFilter(form);
  const key = JSON.stringify(filter);
  return useMemo(
    () => (repeat === "event" ? applyEventFilter(events.filter((event) => !event.is_cancelled), filter, { protocolDate: todayIso() }) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [repeat, key, events]
  );
}

function useValueTexts(data: RowInspectorData) {
  const describe = useListValueDescriber(data.participants, data.events);
  const names = (ids: string[] | null | undefined) =>
    data.participants.filter((participant) => (ids ?? []).includes(participant.id)).map((participant) => participant.display_name).join(", ");

  function eventFieldValue(event: EventSummary | null, field: string): string {
    if (!event) return "";
    const raw = (event as unknown as Record<string, unknown>)[field];
    if (field.endsWith("_ids")) return names(raw as string[] | null);
    if (field === "event_date" || field === "event_end_date") return raw ? formatDate(String(raw)) : "";
    return raw === null || raw === undefined ? "" : String(raw);
  }

  function listParts(row: TableRow): { list: StructuredListDefinition | null; fixed: string; other: string } {
    const listId = typeof row.row_config.linked_list_id === "string" ? row.row_config.linked_list_id : null;
    const list = data.lists.find((entry) => entry.id === listId) ?? null;
    const entryId = row.row_config.linked_list_entry_id;
    const entry = listId ? (data.listEntries[listId] ?? []).find((item) => item.id === entryId) : undefined;
    if (!list || !entry) return { list, fixed: "", other: "" };
    const one = describe(entry.column_one_value, list.column_one_value_type);
    const two = describe(entry.column_two_value, list.column_two_value_type);
    return row.row_config.list_fixed_column === "column_two" ? { list, fixed: two, other: one } : { list, fixed: one, other: two };
  }

  /** Bezeichnung und Vorbelegung einer eigenen Zeile, wie sie im Protokoll erscheint. */
  function rowPreview(row: TableRow, event: EventSummary | null): { label: string; value: string } {
    if (row.row_type === "list_entry") {
      const parts = listParts(row);
      return { label: row.label || parts.fixed, value: parts.other };
    }
    let value = "";
    if (row.row_type === "text") value = resolveEventTokens(row.template_value, event);
    if (row.row_type === "participant") value = data.participants.find((participant) => participant.id === row.template_participant_id)?.display_name ?? "";
    if (row.row_type === "participants") value = names(row.template_participant_ids);
    if (row.row_type === "event") {
      const chosen = data.events.find((entry) => entry.id === row.template_event_id);
      value = chosen ? `${formatDateRange(chosen.event_date, chosen.event_end_date)} · ${chosen.title}` : "";
    }
    return { label: row.label, value };
  }

  return { eventFieldValue, rowPreview, describe };
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
function EventFieldMenu({
  fields,
  labelOf,
  isAlias,
  hidden,
  onToggle,
}: {
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
        {t("tableBlock.addEventField")}
      </button>
      {open && typeof document !== "undefined"
        ? createPortal(
            <div ref={panelRef} className="mini-menu-popover-portal table-block-field-menu" style={style} role="menu">
              {FIELD_GROUPS.map((group) => (
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
              <p className="field-help table-block-field-menu-note">{t("tableBlock.aliasNote")}</p>
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
  previewEvent,
  onChooseEventRepeat,
}: {
  form: BlockForm;
  onChange: (next: BlockForm) => void;
  data: RowInspectorData;
  /** Aufgeklappte Zeile: "e:<feld>" (Terminfeld) oder "r:<id>" (eigene Zeile). */
  openKey: string | null;
  onOpenKey: (key: string | null) => void;
  /** Termin der Vorschau, für Beispielwerte und aufgelöste Platzhalter. */
  previewEvent: EventSummary | null;
  /** Nur gesetzt, wenn der Typ «Pro Termin» erlaubt. */
  onChooseEventRepeat?: () => void;
}) {
  const t = useTranslations("templates.elementEditor");
  const eventFieldConfig = useEventFieldConfig();
  const { eventFieldValue, rowPreview } = useValueTexts(data);
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const setConfig = (next: Record<string, unknown>) => onChange({ ...form, config: { ...form.config, ...next } });
  const rows = (form.config.rows ?? []) as TableRow[];
  const setRows = (next: TableRow[]) => setConfig({ rows: next });
  const linkedListId = (form.config.linked_list_id as string | null) ?? null;
  const linkedList = data.lists.find((list) => list.id === linkedListId) ?? null;
  // Zuletzt gewählte Liste merken, damit «Eigene Zeilen» ↔ «Globale Liste» nichts verliert.
  const lastList = useRef<string | null>(linkedListId);
  if (linkedListId) lastList.current = linkedListId;
  const isEvent = form.config.repeat_source === "event";
  const fields = eventFieldsOf(form);
  const enabledFields = fields.filter((field) => field.enabled);
  const fieldName = (field: string) => eventFieldConfig.label(field, t(`eventField.${field}`));
  const isAlias = (field: string) => fieldName(field) !== t(`eventField.${field}`);

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
    setConfig({ event_fields: fields.map((entry) => (entry.field === field ? { ...entry, ...next } : entry)) });
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

          <div className="table-block-group">
            <div className="table-block-group-head">
              <div className="table-block-group-title">
                <span className="table-block-group-icon table-block-group-icon-event"><LinkIcon /></span>
                <strong>{t("tableBlock.eventRows")}</strong>
                {isEvent ? <span className="muted">{t("tableBlock.eventRowsCount", { count: enabledFields.length })}</span> : null}
              </div>
              {isEvent ? (
                <EventFieldMenu
                  fields={fields}
                  labelOf={fieldName}
                  isAlias={isAlias}
                  hidden={eventFieldConfig.hidden}
                  onToggle={(field, enabled) => {
                    setField(field, { enabled });
                    if (enabled) onOpenKey(`e:${field}`);
                  }}
                />
              ) : null}
            </div>

            {!isEvent ? (
              <div className="table-block-note">
                <span>{t("tableBlock.eventRowsOnlyPerEvent")}</span>
                {onChooseEventRepeat ? (
                  <button type="button" className="button-ghost" onClick={onChooseEventRepeat}>{t("tableBlock.choosePerEvent")}</button>
                ) : null}
              </div>
            ) : enabledFields.length === 0 ? (
              <div className="table-block-note table-block-note-event">{t("tableBlock.eventRowsEmpty")}</div>
            ) : (
              enabledFields.map((field) => {
                const key = `e:${field.field}`;
                const open = openKey === key;
                const value = eventFieldValue(previewEvent, field.field);
                const name = fieldName(field.field);
                return (
                  <div key={key} className={`table-block-row table-block-row-event${open ? " table-block-row-open" : ""}`}>
                    <button type="button" className="table-block-row-head" aria-expanded={open} onClick={() => toggleOpen(key)}>
                      <span className="table-block-row-lead table-block-row-lead-event"><LinkIcon size={15} /></span>
                      <span className="table-block-row-text">
                        <span className="table-block-row-label">{field.label || name}</span>
                        <span className="table-block-row-sub">{t("tableBlock.fromEvent", { field: name })}</span>
                      </span>
                      <span className={`table-block-row-sample${value ? "" : " table-block-row-sample-empty"}`}>
                        {previewEvent ? value || t("tableBlock.emptyAtEvent", { title: previewEvent.title }) : "—"}
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
                          {t("tableBlock.eventFieldNote")}
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
              const preview = rowPreview(row, previewEvent);
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
                        {row.row_type === "text" && previewEvent && row.template_value.includes("{") ? (
                          <span className="field-help">{t("tableBlock.resolvedAt", { title: previewEvent.title, value: resolveEventTokens(row.template_value, previewEvent) })}</span>
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
                  <span className="muted">{`${list.column_one_title} · ${list.column_two_title}`}</span>
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

function LinkedListOptions({ form, list, setConfig }: { form: BlockForm; list: StructuredListDefinition; setConfig: (next: Record<string, unknown>) => void }) {
  const t = useTranslations("templates.elementEditor");
  return (
    <div className="card grid">
      <div className="three-col">
        <label className="field-stack">
          <span className="field-label">{t("table.groupBy")}</span>
          <Select value={String(form.config.linked_list_group_by ?? "")} onChange={(event) => setConfig({ linked_list_group_by: event.target.value || null })}>
            <option value="">{t("table.noGrouping")}</option>
            <option value="column_one">{list.column_one_title}</option>
            <option value="column_two">{list.column_two_title}</option>
          </Select>
        </label>
        <label className="field-stack">
          <span className="field-label">{t("table.sortBy")}</span>
          <Select
            value={String(form.config.linked_list_sort_by ?? "")}
            onChange={(event) => setConfig({ linked_list_sort_by: event.target.value || null, linked_list_sort_direction: event.target.value ? form.config.linked_list_sort_direction ?? "asc" : null })}
          >
            <option value="">{t("table.manualOrder")}</option>
            <option value="column_one">{list.column_one_title}</option>
            <option value="column_two">{list.column_two_title}</option>
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
            <option value="column_one">{list.column_one_title}</option>
            <option value="column_two">{list.column_two_title}</option>
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

/** Vorschau rechts: Tabelle wie im Protokoll-Editor oder im PDF, bei «Pro Termin» für einen Termin. */
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
  matching: EventSummary[];
  previewIndex: number;
  onPreviewIndex: (index: number) => void;
  openKey: string | null;
  onOpenKey: (key: string) => void;
}) {
  const t = useTranslations("templates.elementEditor");
  const eventFieldConfig = useEventFieldConfig();
  const { eventFieldValue, rowPreview, describe } = useValueTexts(data);
  const [mode, setMode] = useState<"editor" | "pdf">("editor");
  const pdf = mode === "pdf";
  const isEvent = form.config.repeat_source === "event";
  const event = isEvent ? matching[Math.min(previewIndex, Math.max(0, matching.length - 1))] ?? null : null;
  const noMatch = isEvent && matching.length === 0;
  const linkedList = data.lists.find((list) => list.id === form.config.linked_list_id) ?? null;
  const rows = (form.config.rows ?? []) as TableRow[];
  const leftHeading = String(form.config.left_column_heading ?? "");
  const rightHeading = String(form.config.value_column_heading ?? "");
  const heading = resolveEventTokens(form.block_title || form.title, event);

  useEffect(() => {
    if (linkedList && !data.listEntries[linkedList.id]) data.ensureListEntries(linkedList.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linkedList?.id, data.listEntries]);

  let previewRows: PreviewRow[] = [];
  if (isEvent) {
    for (const field of eventFieldsOf(form).filter((entry) => entry.enabled)) {
      previewRows.push({
        key: `e:${field.field}`,
        label: field.label || eventFieldConfig.label(field.field, t(`eventField.${field.field}`)),
        value: eventFieldValue(event, field.field),
        fromEvent: true,
        locked: false,
        rowType: "event_field",
      });
    }
  }
  rows.forEach((row, index) => {
    const preview = rowPreview(row, event);
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
    if (previewRows.some((row) => row.fromEvent)) notes.push(t("tableBlock.preview.linkNote"));
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

      {isEvent && matching.length ? (
        <div className="table-block-preview-events">
          <span className="field-help">{matching.length > 1 ? t("tableBlock.preview.perEvent") : t("tableBlock.preview.oneEvent")}</span>
          <div className="table-block-event-chips">
            {matching.map((entry, index) => (
              <button
                key={entry.id}
                type="button"
                aria-pressed={entry === event}
                className={`table-block-event-chip${entry === event ? " table-block-event-chip-active" : ""}`}
                onClick={() => onPreviewIndex(index)}
              >
                <span className="table-block-event-chip-date">{formatDateRange(entry.event_date, entry.event_end_date)}</span>
                <span className="table-block-event-chip-title">{entry.title}</span>
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
                    <span>{row.value || (pdf ? "" : row.fromEvent ? t("tableBlock.preview.emptyAtEvent") : t(`tableBlock.preview.placeholder.${row.rowType}`))}</span>
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
  const columnIndex = (value: unknown) => (value === "column_one" ? 0 : value === "column_two" ? 1 : -1);
  let values = entries.map((entry) => [describe(entry.column_one_value, list.column_one_value_type), describe(entry.column_two_value, list.column_two_value_type)]);
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
      <div className="table-block-table-row table-block-table-head" role="row">
        <span role="columnheader">{list.column_one_title}</span>
        <span role="columnheader">{list.column_two_title}</span>
      </div>
      {groups.map((group, groupIndex) => (
        <div key={group.name ?? groupIndex} role="rowgroup">
          {group.name !== null ? <div className="table-block-table-group">{group.name}</div> : null}
          {group.rows.map((entry, index) => (
            <div key={index} className="table-block-table-row" role="row">
              <span role="cell" className={!entry[0] && highlight ? "table-block-table-missing" : undefined}>{entry[0] || (highlight ? t("tableBlock.preview.missing") : "—")}</span>
              <span role="cell" className={!entry[1] && highlight ? "table-block-table-missing" : undefined}>{entry[1] || (highlight ? t("tableBlock.preview.missing") : "")}</span>
            </div>
          ))}
        </div>
      ))}
      {values.length === 0 ? <div className="table-block-table-empty">{t("table.noRows")}</div> : null}
    </div>
  );
}
