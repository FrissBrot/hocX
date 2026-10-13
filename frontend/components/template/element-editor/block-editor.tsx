"use client";

// Ein Formular für Anlegen UND Bearbeiten eines Blocks. Vorher waren das zwei getrennt
// gepflegte JSX-Blöcke, die auseinanderliefen (Verhalten nur beim Anlegen, andere Hilfetexte,
// andere Steuerelemente). Welche Abschnitte erscheinen, bestimmt die Elementtyp-Registry.
import { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { ChartCycleSelection } from "@/components/protocol/chart-cycle-selection";
import { DataTable } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { RichTextEditor } from "@/components/ui/rich-text-editor";
import { SearchableMultiSelect, SearchableSelect } from "@/components/ui/searchable-select";
import { TagInput } from "@/components/ui/tag-input";
import { elementTypeOptions } from "@/lib/constants/element-types";
import { EVENT_SYNC_FIELD_KEYS, TODO_SYNC_FIELD_KEYS } from "@/lib/constants/event-sync-fields";
import { normalizeEventFilter } from "@/lib/element-types/event-filter";
import { elementType } from "@/lib/element-types/registry";
import type { CycleConfigSummary } from "@/types/api";

import { type BehaviorField, type BlockForm, repeatEventFilter, repeatSourcesFor, setRepeatSource, showsRepeat, type TableRow } from "./block-form";
import { EventFilterEditor } from "./event-filter-editor";
import { EventDisplayChips, rowTypeLabel, type RowInspectorData } from "./row-inspector";
import { BlockTypePreview } from "./type-picker";

export type BlockEditorData = RowInspectorData & {
  accounts: { id: string; name: string; currency_label: string }[];
  cycleConfigs: CycleConfigSummary[];
};

const EVENT_FIELDS = [
  "title", "description", "event_date", "event_end_date", "tag", "participant_count", "organizer_ids", "leadership_ids",
  "participant_ids", "spezial1_ids", "spezial2_ids", "spezial3_ids", "location", "spezial_text1", "spezial_text2", "spezial_text3",
] as const;

const CHART_TYPES = [
  "attendance_over_time", "attendance_by_participant", "finance_by_month", "fines_by_participant", "fines_by_type", "groups_sessions", "groups_avg", "todos",
] as const;

export function SettingsSection({ title, description, actions, children }: { title: string; description?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="settings-section">
      <div className="settings-section-head">
        <div className="settings-section-copy">
          <h3>{title}</h3>
          {description ? <p className="muted">{description}</p> : null}
        </div>
        {actions ? <div className="settings-section-actions">{actions}</div> : null}
      </div>
      <div className="settings-section-body">{children}</div>
    </section>
  );
}

type EventFieldConfig = { field: string; label: string; enabled: boolean };

function eventFieldsOf(form: BlockForm): EventFieldConfig[] {
  const saved = Array.isArray(form.config.event_fields) ? (form.config.event_fields as EventFieldConfig[]) : [];
  return EVENT_FIELDS.map((field) => saved.find((entry) => entry.field === field) ?? { field, label: "", enabled: false });
}

export function BlockEditor({
  mode,
  form,
  onChange,
  data,
  onChooseType,
  onOpenDesigner,
  elementTitle,
  onElementTitleChange,
  showHelp,
}: {
  mode: "create" | "edit";
  form: BlockForm;
  onChange: (next: BlockForm) => void;
  data: BlockEditorData;
  onChooseType: () => void;
  onOpenDesigner: (kind: "form" | "matrix", rowId?: string) => void;
  /** Titel des Elements für die Vorschau. */
  elementTitle: string;
  /** Nur beim Anlegen eines neuen Elements: Elementtitel hier mitpflegen. */
  onElementTitleChange?: (title: string) => void;
  showHelp: boolean;
}) {
  const t = useTranslations("templates.elementEditor");
  const tTypes = useTranslations("templates");
  const info = elementType(form.element_type_id);
  const code = info.code;
  const typeOption = elementTypeOptions(tTypes).find((option) => option.value === String(info.id));
  const repeatSource = String(form.config.repeat_source ?? "none") as "none" | "event" | "todo";
  const allowedRepeat = repeatSourcesFor(form);
  const patch = (next: Partial<BlockForm>) => onChange({ ...form, ...next });
  const setConfig = (next: Record<string, unknown>) => onChange({ ...form, config: { ...form.config, ...next } });
  const rows = (form.config.rows ?? []) as TableRow[];
  const linkedList = data.lists.find((list) => list.id === form.config.linked_list_id) ?? null;
  const repeatFilter = repeatEventFilter(form);
  const eventFields = eventFieldsOf(form);

  const behaviorFields: Array<{ field: BehaviorField; shown: boolean }> = [
    { field: "is_editable", shown: true },
    { field: "export_visible", shown: true },
    { field: "is_visible", shown: true },
    { field: "copy_from_last_protocol", shown: info.carryOver },
    { field: "title_as_subtitle", shown: true },
  ];

  return (
    <div className="element-create-layout">
      <div className="element-create-fields">
        {showHelp ? (
          <div className="compact-info-pop">
            <strong>{t("help.title")}</strong>
            <span className="muted">{t("help.text")}</span>
          </div>
        ) : null}

        <section className="block-editor-hero">
          <div className="block-editor-hero-copy">
            <div className="eyebrow">{mode === "create" ? t("hero.create") : t("hero.edit")}</div>
            <div className="block-editor-hero-top">
              <div className="block-editor-hero-text">
                <h3>{typeOption?.label ?? code}</h3>
                <p className="muted">{typeOption?.description}</p>
              </div>
              <button type="button" className="button-secondary button-ghost block-editor-hero-action" onClick={onChooseType}>
                {t("hero.changeType")}
              </button>
            </div>
            <div className="status-row block-editor-hero-pills">
              {showsRepeat(form) ? <span className="pill">{t(`repeat.option.${repeatSource}`)}</span> : null}
              <span className="pill">{form.is_editable ? t("behavior.is_editable.on") : t("behavior.is_editable.off")}</span>
              {form.copy_from_last_protocol && info.carryOver ? <span className="pill">{t("behavior.copy_from_last_protocol.label")}</span> : null}
              {code === "form" && linkedList ? <span className="pill">{t("table.linkedPill")}</span> : null}
            </div>
          </div>
        </section>

        {onElementTitleChange ? (
          <SettingsSection title={t("element.title")} description={t("element.description")}>
            <label className="field-stack">
              <span className="field-label">{t("element.titleLabel")}</span>
              <input value={elementTitle} onChange={(event) => onElementTitleChange(event.target.value)} placeholder={t("element.titlePlaceholder")} required />
            </label>
          </SettingsSection>
        ) : null}

        <SettingsSection title={t("basics.title")} description={t("basics.description")}>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("basics.name")}</span>
              <input value={form.title} onChange={(event) => patch({ title: event.target.value })} placeholder={t("basics.namePlaceholder")} />
              <span className="field-help">{t("basics.nameHelp")}</span>
            </label>
            <label className="field-stack">
              <span className="field-label">{t("basics.heading")}</span>
              <input value={form.block_title} onChange={(event) => patch({ block_title: event.target.value })} placeholder={t("basics.headingPlaceholder")} />
              <span className="field-help">{t("basics.headingHelp")}</span>
            </label>
          </div>
          <label className="field-stack">
            <span className="field-label">{t("basics.hint")}</span>
            <input value={form.description} onChange={(event) => patch({ description: event.target.value })} placeholder={t("basics.hintPlaceholder")} />
            <span className="field-help">{t("basics.hintHelp")}</span>
          </label>
          {info.content ? (
            // Plain div, kein <label>: der RichTextEditor rendert Toolbar-Buttons vor dem
            // Eingabefeld, ein <label> würde jeden Klick auf den ersten Button umleiten.
            <div className="field-stack">
              <span className="field-label">{code === "static_text" ? t("basics.contentFixed") : t("basics.content")}</span>
              <RichTextEditor value={form.default_content} onChange={(markdown) => patch({ default_content: markdown })} placeholder={t("basics.contentPlaceholder")} />
              <span className="field-help">{t("basics.contentHelp")}</span>
            </div>
          ) : null}
        </SettingsSection>

        {showsRepeat(form) ? (
          <SettingsSection title={t("repeat.title")} description={t("repeat.description")}>
            <div className="rule-option-grid">
              {(["none", ...allowedRepeat] as Array<"none" | "event" | "todo">).concat(
                repeatSource !== "none" && !allowedRepeat.includes(repeatSource as "event" | "todo") ? [repeatSource] : []
              ).map((option) => (
                <button
                  key={option}
                  type="button"
                  className={`rule-option-card${repeatSource === option ? " rule-option-card-active" : ""}`}
                  onClick={() => onChange(setRepeatSource(form, option))}
                >
                  <strong>{t(`repeat.option.${option}`)}</strong>
                  <span className="muted">{t(`repeat.optionHelp.${option}`)}</span>
                </button>
              ))}
            </div>
            {repeatSource !== "none" && !allowedRepeat.includes(repeatSource as "event" | "todo") ? (
              <p className="info-note">{t("repeat.unsupported")}</p>
            ) : null}
            {repeatSource === "event" ? (
              <>
                <EventFilterEditor
                  value={repeatFilter}
                  onChange={(next) => setConfig({ repeat_event_filter: next })}
                  knownEventTags={data.knownEventTags}
                  tagConfig={data.tagConfig}
                  rangeModes={["window", "future", "past", "all"]}
                  showSortLimit
                />
                <label className="checkbox-row">
                  <input type="checkbox" checked={form.config.event_include_unlisted_past === true} onChange={(event) => setConfig({ event_include_unlisted_past: event.target.checked })} />
                  {t("repeat.includeUnlistedPast")}
                </label>
                <div className="info-note">{t("repeat.eventTokens", { tokens: "{title}, {description}, {event_date}, {event_end_date}, {tag}, {id}" })}</div>
              </>
            ) : null}
            {repeatSource === "todo" ? (
              <>
                <div className="three-col">
                  <label className="field-stack">
                    <span className="field-label">{t("repeat.todoBlockTitle")}</span>
                    <input value={String(form.config.todo_block_title_filter ?? "")} onChange={(event) => setConfig({ todo_block_title_filter: event.target.value })} placeholder={t("filter.containsPlaceholder")} />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">{t("repeat.todoText")}</span>
                    <input value={String(form.config.todo_task_filter ?? "")} onChange={(event) => setConfig({ todo_task_filter: event.target.value })} placeholder={t("filter.containsPlaceholder")} />
                  </label>
                  <label className="checkbox-row">
                    <input type="checkbox" checked={form.config.todo_open_only !== false} onChange={(event) => setConfig({ todo_open_only: event.target.checked })} />
                    {t("repeat.todoOpenOnly")}
                  </label>
                </div>
                <div className="info-note">{t("repeat.todoTokens", { tokens: "{title}, {task}, {description}, {due_date}, {participant}, {id}" })}</div>
              </>
            ) : null}
            {code === "text" && repeatSource !== "none" ? (
              <label className="field-stack">
                <span className="field-label">{t(`repeat.syncLabel.${repeatSource}`)}</span>
                <select value={String(form.config.sync_target_field ?? "")} onChange={(event) => setConfig({ sync_target_field: event.target.value || null })}>
                  <option value="">{t("repeat.syncNone")}</option>
                  {(repeatSource === "event" ? EVENT_SYNC_FIELD_KEYS : TODO_SYNC_FIELD_KEYS).map((field) => (
                    <option key={field} value={field}>{t(`syncField.${field}`)}</option>
                  ))}
                </select>
                <span className="field-help">{t(`repeat.syncHelp.${repeatSource}`)}</span>
              </label>
            ) : null}
          </SettingsSection>
        ) : null}

        {code === "todo" ? (
          <SettingsSection title={t("todo.title")} description={t("todo.description")}>
            <label className="field-stack">
              <span className="field-label">{t("todo.dueTagFilter")}</span>
              <TagInput
                value={String(form.config.todo_due_tag_filter ?? "")}
                onChange={(value) => setConfig({ todo_due_tag_filter: value })}
                suggestions={data.knownEventTags}
                tagConfig={data.tagConfig}
                placeholder={t("todo.dueTagFilterPlaceholder")}
              />
              <span className="field-help">{t("todo.dueTagFilterHelp")}</span>
            </label>
          </SettingsSection>
        ) : null}

        {code === "attendance" ? (
          <SettingsSection title={t("attendance.title")} description={t("attendance.description")}>
            <label className="checkbox-row">
              <input type="checkbox" checked={form.config.fines_enabled === true} onChange={(event) => setConfig({ fines_enabled: event.target.checked })} />
              {t("attendance.finesEnabled")}
            </label>
            <span className="field-help">{t("attendance.finesHelp")}</span>
          </SettingsSection>
        ) : null}

        {code === "session_date" ? (
          <SettingsSection title={t("sessionDate.title")} description={t("sessionDate.description")}>
            <EventFilterEditor
              value={normalizeEventFilter(form.config.event_filter)}
              onChange={(next) => setConfig({ event_filter: next })}
              knownEventTags={data.knownEventTags}
              tagConfig={data.tagConfig}
              rangeModes={[]}
              showTitle={false}
              showDescription={false}
              showCycle={false}
              tagLabel={t("sessionDate.tagLabel")}
            />
          </SettingsSection>
        ) : null}

        {code === "event_list" ? (
          <SettingsSection title={t("eventList.title")} description={t("eventList.description")}>
            <EventFilterEditor
              value={normalizeEventFilter(form.config.event_filter, "future")}
              onChange={(next) => setConfig({ event_filter: next })}
              knownEventTags={data.knownEventTags}
              tagConfig={data.tagConfig}
              rangeModes={["future", "past", "all", "window"]}
              showSortLimit
            />
            <div className="element-create-options">
              <label className="element-create-option">
                <input type="checkbox" checked={form.config.event_gray_past !== false} onChange={(event) => setConfig({ event_gray_past: event.target.checked })} />
                <span><strong>{t("eventList.grayPast")}</strong></span>
              </label>
              <label className="element-create-option">
                <input type="checkbox" checked={form.config.event_allow_end_date === true} onChange={(event) => setConfig({ event_allow_end_date: event.target.checked })} />
                <span><strong>{t("eventList.allowEndDate")}</strong></span>
              </label>
            </div>
            <div className="field-stack">
              <span className="field-label">{t("eventList.columns")}</span>
              <EventDisplayChips config={form.config} onChange={setConfig} />
              <span className="field-help">{t("eventList.columnsHelp")}</span>
            </div>
          </SettingsSection>
        ) : null}

        {code === "finance_balance" || code === "finance_transactions" ? (
          <SettingsSection title={t(`finance.${code}`)} description={t("finance.description")}>
            <div className="three-col">
              <label className="field-stack">
                <span className="field-label">{t("finance.account")}</span>
                <SearchableSelect
                  options={data.accounts}
                  getId={(account) => account.id}
                  getLabel={(account) => `${account.name} (${account.currency_label})`}
                  value={(form.config.finance_account_id as string | null) ?? null}
                  onChange={(account) => setConfig({ finance_account_id: account?.id ?? null })}
                  nullLabel={t("finance.chooseAccount")}
                />
              </label>
              {code === "finance_transactions" ? (
                <>
                  <label className="field-stack">
                    <span className="field-label">{t("finance.show")}</span>
                    <select value={String(form.config.finance_filter_type ?? "all")} onChange={(event) => setConfig({ finance_filter_type: event.target.value })}>
                      {["all", "since_last_session", "since_date", "this_year", "last_n"].map((value) => (
                        <option key={value} value={value}>{t(`finance.filter.${value}`)}</option>
                      ))}
                    </select>
                  </label>
                  {form.config.finance_filter_type === "last_n" ? (
                    <label className="field-stack">
                      <span className="field-label">{t("finance.lastN")}</span>
                      <input type="number" min={1} value={String(form.config.finance_last_n ?? 10)} onChange={(event) => setConfig({ finance_last_n: Math.max(1, Number(event.target.value) || 1) })} />
                    </label>
                  ) : null}
                  {form.config.finance_filter_type === "since_date" ? (
                    <label className="field-stack">
                      <span className="field-label">{t("finance.sinceDate")}</span>
                      <DateInput value={String(form.config.finance_since_date ?? "")} onChange={(value) => setConfig({ finance_since_date: value || null })} />
                    </label>
                  ) : null}
                </>
              ) : null}
            </div>
          </SettingsSection>
        ) : null}

        {code === "fine_list" ? (
          <SettingsSection title={t("fineList.title")} description={t("fineList.description")}>
            <p className="info-note">{t("fineList.note")}</p>
          </SettingsSection>
        ) : null}

        {code === "image" ? (
          <SettingsSection title={t("image.title")} description={t("image.description")}>
            <p className="info-note">{t("image.note")}</p>
          </SettingsSection>
        ) : null}

        {code === "form" ? (
          <SettingsSection
            title={t("table.title")}
            description={linkedList ? t("table.linkedDescription") : t("table.description")}
            actions={linkedList ? null : (
              <button type="button" className="button-secondary" onClick={() => onOpenDesigner("form")}>{t("table.configure")}</button>
            )}
          >
            <label className="field-stack">
              <span className="field-label">{t("table.linkedList")}</span>
              <SearchableSelect
                options={data.lists}
                getId={(list) => list.id}
                getLabel={(list) => list.name}
                value={(form.config.linked_list_id as string | null) ?? null}
                onChange={(list) => setConfig({ linked_list_id: list?.id ?? null })}
                nullLabel={t("table.noLinkedList")}
              />
              <span className="field-help">{t("table.linkedListHelp")}</span>
            </label>
            {linkedList ? (
              <div className="card grid">
                <div className="three-col">
                  <label className="field-stack">
                    <span className="field-label">{t("table.groupBy")}</span>
                    <select value={String(form.config.linked_list_group_by ?? "")} onChange={(event) => setConfig({ linked_list_group_by: event.target.value || null })}>
                      <option value="">{t("table.noGrouping")}</option>
                      <option value="column_one">{linkedList.column_one_title}</option>
                      <option value="column_two">{linkedList.column_two_title}</option>
                    </select>
                  </label>
                  <label className="field-stack">
                    <span className="field-label">{t("table.sortBy")}</span>
                    <select
                      value={String(form.config.linked_list_sort_by ?? "")}
                      onChange={(event) => setConfig({ linked_list_sort_by: event.target.value || null, linked_list_sort_direction: event.target.value ? form.config.linked_list_sort_direction ?? "asc" : null })}
                    >
                      <option value="">{t("table.manualOrder")}</option>
                      <option value="column_one">{linkedList.column_one_title}</option>
                      <option value="column_two">{linkedList.column_two_title}</option>
                    </select>
                  </label>
                  <label className="field-stack">
                    <span className="field-label">{t("table.sortDirection")}</span>
                    <select value={String(form.config.linked_list_sort_direction ?? "asc")} disabled={!form.config.linked_list_sort_by} onChange={(event) => setConfig({ linked_list_sort_direction: event.target.value })}>
                      <option value="asc">{t("table.sortAsc")}</option>
                      <option value="desc">{t("table.sortDesc")}</option>
                    </select>
                  </label>
                </div>
                <label className="checkbox-row">
                  <input type="checkbox" checked={form.config.linked_list_highlight_empty === true} onChange={(event) => setConfig({ linked_list_highlight_empty: event.target.checked })} />
                  {t("table.highlightEmpty")}
                </label>
                <p className="muted">{t("table.linkedOptionsHelp")}</p>
              </div>
            ) : (
              <>
                {repeatSource === "event" ? (
                  <div className="element-event-fields">
                    <span className="field-label">{t("table.eventFields")}</span>
                    <SearchableMultiSelect
                      options={[...EVENT_FIELDS]}
                      getId={(field) => field}
                      getLabel={(field) => t(`eventField.${field}`)}
                      values={eventFields.filter((field) => field.enabled).map((field) => field.field)}
                      onChange={(selected) => setConfig({ event_fields: eventFields.map((field) => ({ ...field, enabled: selected.includes(field.field) })) })}
                      placeholder={t("table.eventFieldsPlaceholder")}
                      triggerProps={{ "aria-label": t("table.eventFieldsPlaceholder") }}
                    />
                    <div className="element-event-field-labels">
                      {eventFields.filter((field) => field.enabled).map((field) => (
                        <label key={field.field} className="field-stack">
                          <span className="field-label">{t(`eventField.${field.field}`)}</span>
                          <input
                            value={field.label}
                            placeholder={t(`eventField.${field.field}`)}
                            onChange={(event) => setConfig({ event_fields: eventFields.map((entry) => entry.field === field.field ? { ...entry, label: event.target.value } : entry) })}
                          />
                        </label>
                      ))}
                    </div>
                  </div>
                ) : null}
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
                {rows.length ? (
                  <DataTable columns={[String(form.config.left_column_heading || t("table.rowWord")), String(form.config.value_column_heading || t("table.valueWord"))]}>
                    {rows.map((row, index) => (
                      <tr key={row.id} className="table-row-clickable" onClick={() => onOpenDesigner("form", row.id)}>
                        <td>
                          <strong>{row.label || t("row.numbered", { number: index + 1 })}</strong>
                          <div className="muted">{rowTypeLabel(row.row_type, t, tTypes)}</div>
                        </td>
                        <td>
                          {row.template_value || "—"}
                          {row.locked_in_protocol ? <span className="pill">{t("row.lockedPill")}</span> : null}
                        </td>
                      </tr>
                    ))}
                  </DataTable>
                ) : (
                  <p className="muted">{t("table.noRows")}</p>
                )}
              </>
            )}
          </SettingsSection>
        ) : null}

        {code === "matrix" ? (
          <SettingsSection
            title={t("matrix.sectionTitle")}
            description={t("matrix.sectionDescription")}
            actions={<button type="button" className="button-secondary" onClick={() => onOpenDesigner("matrix")}>{t("matrix.configure")}</button>}
          >
            <div className="status-row">
              {form.config.mode === "auto"
                ? <span className="pill">{t("matrix.summaryAuto", { source: t(`matrix.sourceType.${form.config.auto_source?.type ?? "participants"}`) })}</span>
                : <span className="pill">{t("matrix.summaryColumns", { count: (form.config.columns ?? []).length })}</span>}
              <span className="pill">{t("matrix.summaryRows", { count: rows.length })}</span>
            </div>
            {rows.length ? (
              <div className="table-pill-wrap">
                {rows.map((row) => (
                  <span key={row.id} className="pill">{row.label || t("row.unnamed")} · {rowTypeLabel(row.row_type, t, tTypes)}</span>
                ))}
              </div>
            ) : (
              <p className="muted">{t("matrix.empty")}</p>
            )}
          </SettingsSection>
        ) : null}

        {code === "chart" ? (
          <SettingsSection title={t("chart.title")} description={t("chart.description")}>
            <label className="field-stack">
              <span className="field-label">{t("chart.type")}</span>
              <select value={String(form.config.chart_type ?? "")} onChange={(event) => setConfig({ chart_type: event.target.value || null })}>
                <option value="">{t("chart.choose")}</option>
                {CHART_TYPES.map((type) => <option key={type} value={type}>{t(`chart.types.${type}`)}</option>)}
              </select>
            </label>
            <ChartCycleSelection
              config={{ cycle_config_id: (form.config.cycle_config_id as string | null) ?? null, cycle_offset: Number(form.config.cycle_offset ?? 0) }}
              onChange={(next) => setConfig({ cycle_config_id: next.cycle_config_id ?? null, cycle_offset: next.cycle_offset ?? 0 })}
            />
          </SettingsSection>
        ) : null}

        {code === "entry_exit" ? (
          <SettingsSection title={t("entryExit.title")} description={t("entryExit.description")}>
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">{t("entryExit.firstUse")}</span>
                <select value={String(form.config.entry_exit_first_use_mode ?? "all")} onChange={(event) => setConfig({ entry_exit_first_use_mode: event.target.value })}>
                  <option value="all">{t("entryExit.all")}</option>
                  <option value="since_date">{t("entryExit.sinceDate")}</option>
                </select>
              </label>
              {form.config.entry_exit_first_use_mode === "since_date" ? (
                <label className="field-stack">
                  <span className="field-label">{t("entryExit.startDate")}</span>
                  <DateInput value={String(form.config.entry_exit_first_use_date ?? "")} onChange={(value) => setConfig({ entry_exit_first_use_date: value || null })} />
                </label>
              ) : null}
            </div>
          </SettingsSection>
        ) : null}

        {code === "session_notes" ? <p className="info-note">{t("sessionNotes.note")}</p> : null}
      </div>

      <aside className="element-create-sidebar">
        <section className="element-create-preview">
          <h3>{t("preview.title")}</h3>
          <div className="element-create-paper">
            <h4>{elementTitle.trim() || t("preview.newElement")}</h4>
            {form.block_title || form.title ? <strong>{form.block_title || form.title}</strong> : null}
            {code === "form" && !linkedList ? (
              <DataTable columns={[String(form.config.left_column_heading || t("table.rowWord")), String(form.config.value_column_heading || t("table.valueWord"))]} emptyMessage={t("table.noRows")}>
                {rows.map((row, index) => (
                  <tr key={row.id}>
                    <td>{row.label || t("row.numbered", { number: index + 1 })}</td>
                    <td>{row.template_value || "—"}</td>
                  </tr>
                ))}
              </DataTable>
            ) : info.content && form.default_content ? (
              <p className="element-create-content-preview">{form.default_content}</p>
            ) : (
              <BlockTypePreview elementTypeId={form.element_type_id} />
            )}
            {form.description.trim() ? <p className="field-help">{form.description}</p> : null}
          </div>
        </section>
        <section className="element-create-behavior">
          <h3>{t("behavior.title")}</h3>
          <div className="element-create-options">
            {behaviorFields.filter((entry) => entry.shown).map(({ field }) => (
              <label key={field} className="element-create-option">
                <input type="checkbox" checked={form[field]} onChange={(event) => patch({ [field]: event.target.checked } as Partial<BlockForm>)} />
                <span>
                  <strong>{t(`behavior.${field}.label`)}</strong>
                  <span className="field-help">{t(`behavior.${field}.help`)}</span>
                </span>
              </label>
            ))}
          </div>
          <p className="muted">{t("behavior.templateHint")}</p>
        </section>
        <section className="element-create-cycle-hints">
          <h3>{t("cycleTokens.title")}</h3>
          <div className="element-create-cycle-tokens">
            <code>{"{cycle_name}"}</code>
            <code>{"{cycle_year_start}"}</code>
            <code>{"{cycle_year_end}"}</code>
          </div>
          <p className="muted">{t("cycleTokens.help")}</p>
        </section>
      </aside>
    </div>
  );
}

