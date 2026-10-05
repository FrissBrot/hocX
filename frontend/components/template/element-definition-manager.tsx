"use client";

import { useParticipantSelectable } from "@/contexts/participant-date-context";

import { FormEvent, Fragment, ReactNode, useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { DataTable } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { FilterTabOption, FilterTabs } from "@/components/ui/filter-tabs";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { ActionIcon } from "@/components/ui/action-icons";
import { RichTextEditor } from "@/components/ui/rich-text-editor";
import { SearchableMultiSelect, SearchableSelect } from "@/components/ui/searchable-select";
import { SearchInput } from "@/components/ui/search-input";
import { TagInput } from "@/components/ui/tag-input";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { useTagConfig } from "@/lib/hooks/use-tag-config";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateRange } from "@/lib/utils/format";
import { elementTypeOptions as buildElementTypeOptions, elementTypeLabels as buildElementTypeLabels } from "@/lib/constants/element-types";
import { EVENT_SYNC_FIELDS, TODO_SYNC_FIELDS } from "@/lib/constants/event-sync-fields";
import { ElementDefinition, ElementDefinitionBlock, EventSummary, ParticipantSummary, StructuredListDefinition, StructuredListEntry } from "@/types/api";
import { ChartCycleSelection } from "@/components/protocol/chart-cycle-selection";
import { asObject } from "@/components/protocol/protocol-editor-shared";

type ElementDefinitionManagerProps = {
  initialDefinitions: ElementDefinition[];
  knownEventTags: string[];
  availableParticipants?: ParticipantSummary[];
  availableEvents?: EventSummary[];
  availableLists?: StructuredListDefinition[];
  availableAccounts?: { id: string; name: string; currency_label: string }[];
  tenantId: string | null;
  autoOpenCreate?: boolean;
};

type DefinitionFormState = {
  title: string;
  description: string;
};

type BlockFormState = {
  id: string;
  title: string;
  description: string;
  block_title: string;
  default_content: string;
  copy_from_last_protocol: boolean;
  title_as_subtitle: boolean;
  element_type_id: string;
  repeat_source: "none" | "event" | "todo";
  sync_target_field: string;
  event_tag_filter: string;
  event_title_filter: string;
  event_description_filter: string;
  event_window_start_days: string;
  event_window_end_days: string;
  event_date_mode: "relative_window" | "all_future";
  event_include_unlisted_past: boolean;
  event_only_from_protocol_date: boolean;
  event_only_before_protocol_date: boolean;
  event_only_current_cycle: boolean;
  event_gray_past: boolean;
  event_allow_end_date: boolean;
  event_show_date: boolean;
  event_show_tag: boolean;
  event_show_tag_colors: boolean;
  event_show_title: boolean;
  event_show_description: boolean;
  event_show_participant_count: boolean;
  event_show_cancelled: boolean;
  allow_column_management: boolean;
  matrix_mode: "manual" | "auto";
  auto_source_type: "" | "participants" | "events" | "list";
  auto_source_list_id: string;
  auto_source_event_tag: string;
  todo_block_title_filter: string;
  todo_task_filter: string;
  todo_open_only: boolean;
  todo_due_tag_filter: string;
  finance_account_id: string;
  finance_filter_type: "all" | "since_last_session" | "this_year" | "last_n";
  finance_last_n: string;
  finance_since_date: string;
  fine_account_id: string;
  fine_amount_late: string;
  fine_amount_absent: string;
  chart_type: string;
  chart_cycle_key: string;
  chart_cycle_config_id: string;
  chart_cycle_offset: number;
  entry_exit_first_use_mode: "all" | "since_date";
  entry_exit_first_use_date: string;
  left_column_heading: string;
  value_column_heading: string;
  linked_list_id: string;
  linked_list_group_by: "" | "column_one" | "column_two";
  linked_list_sort_by: "" | "column_one" | "column_two";
  linked_list_sort_direction: "asc" | "desc";
  is_editable: boolean;
  export_visible: boolean;
  is_visible: boolean;
  sort_index: string;
  event_fields: EventFieldConfig[];
  table_fields: Array<{
    id: string;
    label: string;
    row_type: string; // "text"|"participant"|"participants"|"event"|"events" or embedded element_type_id as string
    locked_in_protocol: boolean;
    row_config: Record<string, unknown>;
    auto_source_field: string;
    // Template default values (for non-embedded row types)
    template_value?: string;
    template_participant_id?: string;
    template_participant_ids?: string[];
    template_event_id?: string;
  }>;
  matrix_columns: Array<{
    id: string;
    title: string;
    event_tag_filter?: string;
    title_placeholder?: string;
  }>;
};

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

function eventDateModeOptions(t: TFunc): FilterTabOption<"relative_window" | "all_future">[] {
  return [
    { value: "relative_window", label: t("eventWindowMode.window") },
    { value: "all_future", label: t("eventWindowMode.allFuture") },
  ];
}

function DayOffsetStepper({ value, onChange, ariaLabel, min = 0 }: { value: number; onChange: (value: number) => void; ariaLabel: string; min?: number }) {
  const t = useTranslations("templates.elementDefinitions");
  return (
    <span className="event-window-stepper">
      <button type="button" className="button-icon-soft" aria-label={t("stepperDecrease", { label: ariaLabel })} onClick={() => onChange(Math.max(min, value - 1))}>−</button>
      <span className="event-window-stepper-value">{value}</span>
      <button type="button" className="button-icon-soft" aria-label={t("stepperIncrease", { label: ariaLabel })} onClick={() => onChange(value + 1)}>+</button>
    </span>
  );
}

const EVENT_FIELD_DEFS = [
  { field: "title", type: "text" },
  { field: "description", type: "text" },
  { field: "event_date", type: "date" },
  { field: "event_end_date", type: "date" },
  { field: "tag", type: "text" },
  { field: "participant_count", type: "number" },
  { field: "organizer_ids", type: "participants" },
  { field: "leadership_ids", type: "participants" },
  { field: "participant_ids", type: "participants" },
  { field: "spezial1_ids", type: "participants" },
  { field: "spezial2_ids", type: "participants" },
  { field: "spezial3_ids", type: "participants" },
  { field: "location", type: "text" },
  { field: "spezial_text1", type: "text" },
  { field: "spezial_text2", type: "text" },
  { field: "spezial_text3", type: "text" },
] as const;

function allEventFields(t: TFunc) {
  return EVENT_FIELD_DEFS.map((def) => ({ ...def, defaultLabel: t(`eventFields.${def.field}`) }));
}

type EventFieldConfig = { field: string; label: string; enabled: boolean };

function selectedEventFields(form: BlockFormState): EventFieldConfig[] {
  return form.element_type_id === "6" && form.repeat_source === "event" && !form.linked_list_id
    ? form.event_fields.filter((field) => field.enabled)
    : [];
}

function eventFieldPreviewRows(form: BlockFormState, t: TFunc) {
  const fields = allEventFields(t);
  return selectedEventFields(form).map((field) => {
    const definition = fields.find((entry) => entry.field === field.field);
    return (
      <tr key={`event-field-${field.field}`}>
        <td><strong>{field.label.trim() || definition?.defaultLabel || field.field}</strong></td>
        <td className="muted">{t("eventFieldFromEvent", { label: definition?.defaultLabel ?? field.field })}</td>
      </tr>
    );
  });
}

function EventFieldSelector({ fields, onChange }: { fields: EventFieldConfig[]; onChange: (fields: EventFieldConfig[]) => void }) {
  const t = useTranslations("templates.elementDefinitions");
  const allFields = allEventFields(t);
  return (
    <div className="element-event-fields">
      <span className="field-label">{t("eventFieldsLabel")}</span>
      <SearchableMultiSelect
        options={allFields}
        getId={(field) => field.field as string}
        getLabel={(field) => field.defaultLabel}
        values={fields.filter((field) => field.enabled).map((field) => field.field)}
        onChange={(selected) => onChange(fields.map((field) => ({ ...field, enabled: selected.includes(field.field) })))}
        placeholder={t("eventFieldsPlaceholder")}
        triggerProps={{ "aria-label": t("eventFieldsPlaceholder") }}
      />
      <div className="element-event-field-labels">
        {fields.filter((field) => field.enabled).map((field) => {
          const definition = allFields.find((entry) => entry.field === field.field);
          return (
            <label key={field.field} className="field-stack">
              <span className="field-label">{definition?.defaultLabel ?? field.field}</span>
              <input
                aria-label={t("eventFieldRowLabel", { label: definition?.defaultLabel ?? field.field })}
                value={field.label}
                placeholder={definition?.defaultLabel}
                onChange={(event) => onChange(fields.map((entry) => entry.field === field.field ? { ...entry, label: event.target.value } : entry))}
              />
            </label>
          );
        })}
      </div>
    </div>
  );
}

function defaultEventFields(): EventFieldConfig[] {
  return EVENT_FIELD_DEFS.map((f) => ({ field: f.field, label: "", enabled: false }));
}

function mergeEventFields(saved: EventFieldConfig[]): EventFieldConfig[] {
  return EVENT_FIELD_DEFS.map((def) => {
    const existing = saved.find((s) => s.field === def.field);
    return existing ?? { field: def.field, label: "", enabled: false };
  });
}

const initialDefinitionForm: DefinitionFormState = {
  title: "",
  description: "",
};

const initialBlockForm: BlockFormState = {
  id: "1",
  title: "",
  description: "",
  block_title: "",
  default_content: "",
  copy_from_last_protocol: false,
  title_as_subtitle: true,
  element_type_id: "1",
  repeat_source: "none",
  sync_target_field: "",
  event_tag_filter: "",
  event_title_filter: "",
  event_description_filter: "",
  event_window_start_days: "0",
  event_window_end_days: "14",
  event_date_mode: "relative_window",
  event_include_unlisted_past: false,
  event_only_from_protocol_date: true,
  event_only_before_protocol_date: false,
  event_only_current_cycle: false,
  event_gray_past: true,
  event_allow_end_date: false,
  event_show_date: true,
  event_show_tag: true,
  event_show_tag_colors: false,
  event_show_title: true,
  event_show_description: true,
  event_show_participant_count: false,
  event_show_cancelled: false,
  allow_column_management: true,
  matrix_mode: "manual" as "manual" | "auto",
  auto_source_type: "" as "" | "participants" | "events" | "list",
  auto_source_list_id: "",
  auto_source_event_tag: "",
  todo_block_title_filter: "",
  todo_task_filter: "",
  todo_open_only: true,
  todo_due_tag_filter: "",
  finance_account_id: "",
  finance_filter_type: "all" as "all" | "since_last_session" | "this_year" | "last_n",
  finance_last_n: "10",
  finance_since_date: "",
  fine_account_id: "",
  fine_amount_late: "",
  fine_amount_absent: "",
  chart_type: "",
  chart_cycle_key: "all",
  chart_cycle_config_id: "",
  chart_cycle_offset: 0,
  entry_exit_first_use_mode: "all" as "all" | "since_date",
  entry_exit_first_use_date: "",
  left_column_heading: "",
  value_column_heading: "",
  linked_list_id: "",
  linked_list_group_by: "",
  linked_list_sort_by: "",
  linked_list_sort_direction: "asc",
  is_editable: true,
  export_visible: true,
  is_visible: true,
  sort_index: "10",
  event_fields: defaultEventFields(),
  table_fields: [],
  matrix_columns: [],
};

function defaultFieldRow(id = "1") {
  return {
    id,
    label: "",
    row_type: "text",
    locked_in_protocol: false,
    row_config: {} as Record<string, unknown>,
    auto_source_field: "",
    template_value: "",
    template_participant_id: "",
    template_participant_ids: [] as string[],
    template_event_id: "",
  };
}

function defaultMatrixColumn(id = "matrix-column-1") {
  return {
    id,
    title: "",
    event_tag_filter: "",
  };
}

// matrixEmbeddedBlockOptions ids reuse the same element types (and translations) as
// buildElementTypeOptions - see matrixEmbeddedBlockOptionsList() below.
const MATRIX_EMBEDDED_BLOCK_IDS = ["1", "6", "2", "3", "7", "9", "10"] as const;

function matrixEmbeddedBlockOptionsList(tTypes: TFunc): { value: string; label: string }[] {
  const labels = buildElementTypeLabels(tTypes);
  return MATRIX_EMBEDDED_BLOCK_IDS.map((value) => ({ value, label: labels[Number(value)] }));
}

function optionLabel(options: { value: string; label: string }[], value: number | string, t: TFunc) {
  return options.find((option) => option.value === String(value))?.label ?? t("unknownOption", { value });
}

function optionDescription(options: { value: string; label: string; description?: string }[], value: number | string) {
  return options.find((option) => option.value === String(value))?.description ?? "";
}

function renderTypeForElementType(elementTypeId: string | number) {
  const mapping: Record<string, string> = {
    "1": "2",
    "2": "3",
    "3": "4",
    "5": "6",
    "6": "5",
    "7": "5",
    "8": "2",
    "9": "5",
    "10": "6",
    "11": "5",
    "16": "5",
    "17": "6",
  };
  return mapping[String(elementTypeId)] ?? "2";
}

function blockKindForElementType(elementTypeId: string | number) {
  const mapping: Record<string, string> = {
    "1": "text",
    "2": "todo",
    "3": "image",
    "5": "static_text",
    "6": "form",
    "7": "event_list",
    "8": "bullet_list",
    "9": "attendance",
    "10": "session_date",
    "11": "matrix",
    "12": "finance_balance",
    "13": "finance_transactions",
    "15": "chart",
    "16": "entry_exit",
    "17": "session_notes",
  };
  return mapping[String(elementTypeId)] ?? "text";
}

function definitionFormFromDefinition(definition: ElementDefinition): DefinitionFormState {
  return {
    title: definition.title,
    description: definition.description ?? "",
  };
}

function inferAllowsMultipleValues(elementTypeId: string | number) {
  return String(elementTypeId) === "2" || String(elementTypeId) === "3";
}

function valueTypeChoices(elementTypeId: string, t: TFunc) {
  const choices: Array<{ value: "text" | "participant" | "participants" | "event" | "events" | "list_entry"; label: string }> = [
    { value: "text", label: t("valueType.text") },
    { value: "participant", label: t("valueType.participant") },
    { value: "participants", label: t("valueType.participants") },
    { value: "event", label: t("valueType.event") },
  ];
  if (elementTypeId === "11") {
    choices.push({ value: "events", label: t("valueType.eventsAuto") });
  }
  if (elementTypeId === "6") {
    choices.push({ value: "list_entry", label: t("valueType.listEntry") });
  }
  return choices;
}

function valueTypeLabel(valueType: "text" | "participant" | "participants" | "event" | "events" | "list_entry", t: TFunc) {
  switch (valueType) {
    case "participant":
      return t("valueType.participant");
    case "participants":
      return t("valueType.participants");
    case "event":
      return t("valueType.event");
    case "events":
      return t("valueType.events");
    case "list_entry":
      return t("valueType.listEntry");
    default:
      return t("valueType.text");
  }
}

function matrixEmbeddedBlockLabel(elementTypeId: string | number | null | undefined, tTypes: TFunc, t: TFunc) {
  return matrixEmbeddedBlockOptionsList(tTypes).find((option) => option.value === String(elementTypeId ?? ""))?.label ?? t("valueType.value");
}

function normalizeTemplateIdList(value: unknown) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((entry) => String(entry ?? "").trim())
    .filter((entry) => entry.length > 0);
}

function matrixEmbeddedBlockConfiguration(elementTypeId: string | number | null | undefined, value: unknown) {
  const current = value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
  if (String(elementTypeId) === "7") {
    return {
      event_tag_filter: "",
      event_only_from_protocol_date: true,
      event_only_before_protocol_date: false,
      event_only_current_cycle: false,
      event_gray_past: true,
      event_allow_end_date: false,
      event_use_column_tag_filter: false,
      event_show_date: true,
      event_show_tag: true,
      event_show_title: true,
      event_show_description: true,
      event_show_participant_count: false,
      event_show_cancelled: false,
      ...current,
    };
  }
  return current;
}

function matrixRowWithEmbeddedType<T extends { embedded_element_type_id?: string; embedded_configuration_json?: Record<string, unknown> }>(
  row: T,
  nextElementTypeId: string
) {
  return {
    ...row,
    embedded_element_type_id: nextElementTypeId,
    embedded_configuration_json: nextElementTypeId ? matrixEmbeddedBlockConfiguration(nextElementTypeId, row.embedded_configuration_json) : {},
  } as T;
}

function nextSortIndex(blocks: ElementDefinitionBlock[]) {
  return String((blocks.length + 1) * 10);
}

function resequenceBlocks(blocks: ElementDefinitionBlock[]) {
  return blocks.map((block, index) => ({
    ...block,
    sort_index: (index + 1) * 10,
    render_order: (index + 1) * 10,
  }));
}

function blockFormFromBlock(block: ElementDefinitionBlock): BlockFormState {
  return {
    id: String(block.id),
    title: block.title,
    description: block.description ?? "",
    block_title: block.block_title ?? "",
    default_content: block.default_content ?? "",
    copy_from_last_protocol: block.copy_from_last_protocol ?? false,
    title_as_subtitle: Boolean(block.configuration_json?.title_as_subtitle ?? true),
    element_type_id: String(block.element_type_id),
    repeat_source: (String(block.configuration_json?.repeat_source ?? "none") as "none" | "event" | "todo"),
    sync_target_field: String(block.configuration_json?.sync_target_field ?? ""),
    event_tag_filter: String(block.configuration_json?.event_tag_filter ?? ""),
    event_title_filter: String(block.configuration_json?.event_title_filter ?? ""),
    event_description_filter: String(block.configuration_json?.event_description_filter ?? ""),
    event_window_start_days: String(block.configuration_json?.event_window_start_days ?? "0"),
    event_window_end_days: String(block.configuration_json?.event_window_end_days ?? "14"),
    event_date_mode: (String(block.configuration_json?.event_date_mode ?? "relative_window") as "relative_window" | "all_future"),
    event_include_unlisted_past: Boolean(block.configuration_json?.event_include_unlisted_past ?? false),
    event_only_from_protocol_date: Boolean(block.configuration_json?.event_only_from_protocol_date ?? true),
    event_only_before_protocol_date: Boolean(block.configuration_json?.event_only_before_protocol_date ?? false),
    event_only_current_cycle: Boolean(block.configuration_json?.event_only_current_cycle ?? false),
    event_gray_past: Boolean(block.configuration_json?.event_gray_past ?? true),
    event_allow_end_date: Boolean(block.configuration_json?.event_allow_end_date ?? false),
    event_show_date: Boolean(block.configuration_json?.event_show_date ?? true),
    event_show_tag: Boolean(block.configuration_json?.event_show_tag ?? true),
    event_show_tag_colors: Boolean(block.configuration_json?.event_show_tag_colors ?? false),
    event_show_title: Boolean(block.configuration_json?.event_show_title ?? true),
    event_show_description: Boolean(block.configuration_json?.event_show_description ?? true),
    event_show_participant_count: Boolean(block.configuration_json?.event_show_participant_count ?? false),
    event_show_cancelled: Boolean(block.configuration_json?.event_show_cancelled ?? false),
    allow_column_management: Boolean(
      block.configuration_json?.allow_column_management ?? block.configuration_json?.matrix_allow_column_management ?? true
    ),
    matrix_mode: ((block.configuration_json?.mode ?? "manual") === "auto" ? "auto" : "manual") as "manual" | "auto",
    auto_source_type: (() => {
      const autoSrc = block.configuration_json?.auto_source;
      if (autoSrc && typeof autoSrc === "object" && asObject(autoSrc).type) return asObject(autoSrc).type as "" | "participants" | "events" | "list";
      return (String(block.configuration_json?.matrix_column_source ?? "") as "" | "participants" | "events" | "list");
    })(),
    auto_source_list_id: (() => {
      const autoSrc = block.configuration_json?.auto_source;
      if (autoSrc && typeof autoSrc === "object" && asObject(autoSrc).list_id != null) return String(asObject(autoSrc).list_id);
      return block.configuration_json?.matrix_column_source_list_id != null ? String(block.configuration_json.matrix_column_source_list_id) : "";
    })(),
    auto_source_event_tag: (() => {
      const autoSrc = block.configuration_json?.auto_source;
      if (autoSrc && typeof autoSrc === "object") return String(asObject(autoSrc).event_tag_filter ?? "");
      return String(block.configuration_json?.matrix_column_source_event_tag ?? "");
    })(),
    todo_block_title_filter: String(block.configuration_json?.todo_block_title_filter ?? ""),
    todo_task_filter: String(block.configuration_json?.todo_task_filter ?? ""),
    todo_open_only: Boolean(block.configuration_json?.todo_open_only ?? true),
    todo_due_tag_filter: String(block.configuration_json?.todo_due_tag_filter ?? ""),
    finance_account_id: block.configuration_json?.finance_account_id != null ? String(block.configuration_json.finance_account_id) : "",
    finance_filter_type: (String(block.configuration_json?.finance_filter_type ?? "all")) as "all" | "since_last_session" | "this_year" | "last_n",
    finance_last_n: String(block.configuration_json?.finance_last_n ?? "10"),
    finance_since_date: String(block.configuration_json?.finance_since_date ?? ""),
    fine_account_id: block.configuration_json?.fine_account_id != null ? String(block.configuration_json.fine_account_id) : "",
    fine_amount_late: block.configuration_json?.fine_amount_late != null ? String(block.configuration_json.fine_amount_late) : "",
    fine_amount_absent: block.configuration_json?.fine_amount_absent != null ? String(block.configuration_json.fine_amount_absent) : "",
    chart_type: String(block.configuration_json?.chart_type ?? ""),
    chart_cycle_key: String(block.configuration_json?.cycle_key ?? "all"),
    chart_cycle_config_id: String(block.configuration_json?.cycle_config_id ?? ""),
    chart_cycle_offset: Number(block.configuration_json?.cycle_offset ?? 0),
    entry_exit_first_use_mode: (String(block.configuration_json?.entry_exit_first_use_mode ?? "all") as "all" | "since_date"),
    entry_exit_first_use_date: String(block.configuration_json?.entry_exit_first_use_date ?? ""),
    left_column_heading: String(block.configuration_json?.left_column_heading ?? ""),
    value_column_heading: String(block.configuration_json?.value_column_heading ?? ""),
    linked_list_id: block.configuration_json?.linked_list_id != null ? String(block.configuration_json?.linked_list_id) : "",
    linked_list_group_by:
      block.configuration_json?.linked_list_group_by === "column_one" || block.configuration_json?.linked_list_group_by === "column_two"
        ? block.configuration_json.linked_list_group_by
        : "",
    linked_list_sort_by:
      block.configuration_json?.linked_list_sort_by === "column_one" || block.configuration_json?.linked_list_sort_by === "column_two"
        ? block.configuration_json.linked_list_sort_by
        : "",
    linked_list_sort_direction: block.configuration_json?.linked_list_sort_direction === "desc" ? "desc" : "asc",
    event_fields: mergeEventFields(
      Array.isArray(block.configuration_json?.event_fields)
        ? (block.configuration_json.event_fields as EventFieldConfig[])
        : []
    ),
    is_editable: block.is_editable,
    export_visible: block.export_visible,
    is_visible: block.is_visible,
    sort_index: String(block.sort_index),
    table_fields: (() => {
      // Support both new "rows" and old "field_rows" schema
      const rawRows = Array.isArray(block.configuration_json?.rows)
        ? (block.configuration_json.rows as Array<Record<string, unknown>>)
        : Array.isArray(block.configuration_json?.field_rows)
        ? (block.configuration_json.field_rows as Array<Record<string, unknown>>)
        : [];
      return rawRows.map((row, index) => {
        // Determine row_type from new or old schema
        let rowType = String(row.row_type ?? "");
        if (!rowType) {
          rowType = row.embedded_element_type_id ? String(row.embedded_element_type_id) : String(row.value_type ?? "text");
        }
        // Determine locked_in_protocol from new or old schema
        const locked = "locked_in_protocol" in row ? Boolean(row.locked_in_protocol) : !Boolean(row.protocol_editable ?? true);
        // row_config: new schema or build from old fields
        let rowConfig: Record<string, unknown> = {};
        if (row.row_config && typeof row.row_config === "object" && !Array.isArray(row.row_config)) {
          rowConfig = { ...(row.row_config as Record<string, unknown>) };
        } else {
          const embeddedCfg = matrixEmbeddedBlockConfiguration(String(row.embedded_element_type_id ?? ""), row.embedded_configuration_json);
          rowConfig = { ...embeddedCfg };
          for (const k of ["event_tag_filter", "event_title_filter", "use_column_title_as_tag", "hide_past_events"]) {
            if (k in row) rowConfig[k] = row[k];
          }
        }
        // auto_source_field from new or old schema
        const autoSourceField = String(
          row.auto_source_field ?? row.source_field_participant ?? row.source_field_event ?? row.source_field_list ?? ""
        );
        return {
          id: String(row.id ?? index + 1),
          label: String(row.label ?? ""),
          row_type: rowType,
          locked_in_protocol: locked,
          row_config: rowConfig,
          auto_source_field: autoSourceField,
          template_value: String(row.template_value ?? ""),
          template_participant_id: row.template_participant_id != null ? String(row.template_participant_id) : "",
          template_participant_ids: normalizeTemplateIdList(row.template_participant_ids),
          template_event_id: row.template_event_id != null ? String(row.template_event_id) : "",
        };
      });
    })(),
    matrix_columns: (() => {
      // Support both new "columns" and old "matrix_columns" schema
      const rawCols = Array.isArray(block.configuration_json?.columns)
        ? (block.configuration_json.columns as Array<Record<string, unknown>>)
        : Array.isArray(block.configuration_json?.matrix_columns)
        ? (block.configuration_json.matrix_columns as Array<Record<string, unknown>>)
        : [];
      return rawCols.map((column, index) => ({
        id: String(column.id ?? `matrix-column-${index + 1}`),
        title: String(column.title ?? ""),
        event_tag_filter: String(column.event_tag_filter ?? ""),
      }));
    })(),
  };
}

function blockPayload(form: BlockFormState): ElementDefinitionBlock {
  return {
    id: Number(form.id),
    title: form.title,
    description: form.description || null,
    block_title: form.block_title || null,
    default_content: form.default_content || null,
    copy_from_last_protocol: form.copy_from_last_protocol,
    element_type_id: Number(form.element_type_id),
    render_type_id: Number(renderTypeForElementType(form.element_type_id)),
    is_editable: form.is_editable,
    allows_multiple_values: inferAllowsMultipleValues(form.element_type_id),
    export_visible: form.export_visible,
    is_visible: form.is_visible,
    sort_index: Number(form.sort_index),
    render_order: Number(form.sort_index),
    latex_template: null,
    configuration_json: {
      block_kind: blockKindForElementType(form.element_type_id),
      block_type_code: blockKindForElementType(form.element_type_id),
      title_as_subtitle: form.title_as_subtitle,
      repeat_source: form.repeat_source,
      sync_target_field: form.sync_target_field || null,
      event_tag_filter: form.event_tag_filter || null,
      event_title_filter: form.event_title_filter || null,
      event_description_filter: form.event_description_filter || null,
      event_window_start_days: Number(form.event_window_start_days || "0"),
      event_window_end_days: Number(form.event_window_end_days || "14"),
      event_date_mode: form.event_date_mode,
      event_include_unlisted_past: form.event_include_unlisted_past,
      event_only_from_protocol_date: form.event_only_from_protocol_date,
      event_only_before_protocol_date: form.event_only_before_protocol_date,
      event_only_current_cycle: form.event_only_current_cycle,
      event_gray_past: form.event_gray_past,
      event_allow_end_date: form.event_allow_end_date,
      event_show_date: form.event_show_date,
      event_show_tag: form.event_show_tag,
      event_show_tag_colors: form.event_show_tag_colors,
      event_show_title: form.event_show_title,
      event_show_description: form.event_show_description,
      event_show_participant_count: form.event_show_participant_count,
      event_show_cancelled: form.event_show_cancelled,
      mode: form.matrix_mode,
      allow_column_management: form.allow_column_management,
      auto_source: form.auto_source_type ? {
        type: form.auto_source_type,
        list_id: form.auto_source_type === "list" && form.auto_source_list_id ? form.auto_source_list_id : null,
        event_tag_filter: form.auto_source_type === "events" ? (form.auto_source_event_tag || null) : null,
      } : null,
      todo_block_title_filter: form.todo_block_title_filter || null,
      todo_task_filter: form.todo_task_filter || null,
      todo_open_only: form.todo_open_only,
      todo_due_tag_filter: form.todo_due_tag_filter || null,
      finance_account_id: form.finance_account_id || null,
      finance_filter_type: form.finance_filter_type,
      finance_last_n: form.finance_filter_type === "last_n" ? Number(form.finance_last_n) : null,
      finance_since_date: form.finance_filter_type === "since_last_session" ? (form.finance_since_date || null) : null,
      fine_account_id: form.fine_account_id || null,
      fine_amount_late: form.fine_amount_late ? parseFloat(form.fine_amount_late) : null,
      fine_amount_absent: form.fine_amount_absent ? parseFloat(form.fine_amount_absent) : null,
      chart_type: form.chart_type || null,
      cycle_key: form.chart_cycle_key || "all",
      cycle_config_id: form.chart_cycle_config_id || null,
      cycle_offset: form.chart_cycle_offset,
      entry_exit_first_use_mode: form.entry_exit_first_use_mode,
      entry_exit_first_use_date: form.entry_exit_first_use_mode === "since_date" ? (form.entry_exit_first_use_date || null) : null,
      left_column_heading: form.left_column_heading || null,
      value_column_heading: form.value_column_heading || null,
      linked_list_id:
        form.element_type_id === "6" && form.linked_list_id ? form.linked_list_id : null,
      linked_list_group_by:
        form.element_type_id === "6" && form.linked_list_id && form.linked_list_group_by ? form.linked_list_group_by : null,
      linked_list_sort_by:
        form.element_type_id === "6" && form.linked_list_id && form.linked_list_sort_by ? form.linked_list_sort_by : null,
      linked_list_sort_direction:
        form.element_type_id === "6" && form.linked_list_id && form.linked_list_sort_by ? form.linked_list_sort_direction : null,
      event_fields:
        form.element_type_id === "6" && form.repeat_source === "event" && !form.linked_list_id
          ? selectedEventFields(form)
          : null,
      rows:
        (String(form.element_type_id) === "11" || (String(form.element_type_id) === "6" && !form.linked_list_id))
          ? form.table_fields.map((field, index) => ({
              id: field.id || String(index + 1),
              label: field.label,
              row_type: field.row_type || "text",
              locked_in_protocol: Boolean(field.locked_in_protocol),
              row_config: field.row_config || {},
              auto_source_field: field.auto_source_field || null,
              template_value: field.template_value || "",
              template_participant_id: field.template_participant_id ? field.template_participant_id : null,
              template_participant_ids: (field.template_participant_ids ?? []).filter(Boolean),
              template_event_id: field.template_event_id ? field.template_event_id : null,
              sort_index: (index + 1) * 10,
            }))
          : [],
      columns:
        form.element_type_id === "11"
          ? form.matrix_columns.map((column, index) => ({
              id: column.id || `matrix-column-${index + 1}`,
              title: column.title,
              event_tag_filter: column.event_tag_filter || null,
              sort_index: (index + 1) * 10,
            }))
          : [],
    }
  };
}

function nextBlockId(blocks: ElementDefinitionBlock[]) {
  return String(Math.max(0, ...blocks.map((block) => block.id)) + 1);
}

function nextTableFieldId(fields: BlockFormState["table_fields"]) {
  return String(Math.max(0, ...fields.map((field) => Number(field.id) || 0)) + 1);
}

function nextMatrixColumnConfigId(columns: BlockFormState["matrix_columns"]) {
  const maxValue = columns.reduce((highest, column) => {
    const match = String(column.id ?? "").match(/^matrix-column-(\d+)$/);
    const candidate = match ? Number(match[1]) : 0;
    return Math.max(highest, candidate);
  }, 0);
  return `matrix-column-${maxValue + 1}`;
}

function blockDisplayName(block: { title?: string | null; block_title?: string | null }, t: TFunc) {
  const title = String(block.title ?? "").trim();
  const subtitle = String(block.block_title ?? "").trim();
  if (title) {
    return title;
  }
  if (subtitle) {
    return t("blockDisplayNameUnderSubtitle", { subtitle });
  }
  return t("blockDisplayNameUnderTitle");
}

function linkedListColumnOptions(definition: StructuredListDefinition | null) {
  if (!definition) {
    return [];
  }
  return [
    { value: "column_one" as const, label: definition.column_one_title },
    { value: "column_two" as const, label: definition.column_two_title },
  ];
}

function repeatSourceLabel(value: BlockFormState["repeat_source"], t: TFunc) {
  switch (value) {
    case "event":
      return t("repeatSource.event");
    case "todo":
      return t("repeatSource.todo");
    default:
      return t("repeatSource.none");
  }
}

function SettingsSection({
  title,
  description,
  actions,
  children,
  tone = "default",
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  tone?: "default" | "soft";
}) {
  return (
    <section className={`settings-section${tone === "soft" ? " settings-section-soft" : ""}`}>
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

function BlockEditorSummary({
  form,
  mode,
  onChooseType,
}: {
  form: BlockFormState;
  mode: "create" | "edit";
  onChooseType: () => void;
}) {
  const t = useTranslations("templates.elementDefinitions");
  const tTypes = useTranslations("templates");
  const elementTypeOptions = buildElementTypeOptions(tTypes);
  const currentTypeLabel = optionLabel(elementTypeOptions, form.element_type_id, t);
  const currentTypeDescription = optionDescription(elementTypeOptions, form.element_type_id);
  const hasLinkedList = form.element_type_id === "6" && Boolean(form.linked_list_id);

  return (
    <section className="block-editor-hero">
      <div className="block-editor-hero-copy">
        <div className="eyebrow">{mode === "create" ? t("newBlock") : t("editBlockTitle")}</div>
        <div className="block-editor-hero-top">
          <div className="block-editor-hero-text">
            <h3>{currentTypeLabel}</h3>
            <p className="muted">{currentTypeDescription || t("chooseTypeHint")}</p>
          </div>
          <button type="button" className="button-ghost button-secondary block-editor-hero-action" onClick={onChooseType}>
            {t("changeBlockType")}
          </button>
        </div>
        <div className="status-row block-editor-hero-pills">
          <span className="pill">{t("pillType", { label: currentTypeLabel })}</span>
          <span className="pill">{t("pillRepeat", { label: repeatSourceLabel(form.repeat_source, t) })}</span>
          <span className="pill">{form.is_editable ? t("editableInProtocol") : t("fixedInProtocol")}</span>
          {hasLinkedList ? <span className="pill">{t("linkedToGlobalList")}</span> : null}
          {form.copy_from_last_protocol ? <span className="pill">{t("copiedFromLastSession")}</span> : null}
        </div>
      </div>
    </section>
  );
}

function ElementEditorSummary({
  title,
  description,
  mode,
}: {
  title: string;
  description?: string;
  mode: "create" | "edit";
}) {
  const t = useTranslations("templates.elementDefinitions");
  const resolvedTitle = title.trim() || (mode === "create" ? t("newElement") : t("elementWithoutTitle"));

  return (
    <section className="block-editor-hero">
      <div className="block-editor-hero-copy">
        <div className="eyebrow">{mode === "create" ? t("newElement") : t("editElementTitle")}</div>
        <div className="block-editor-hero-top">
          <div className="block-editor-hero-text">
            <h3>{resolvedTitle}</h3>
            <p className="muted">
              {description?.trim() || t("elementEditorFallbackDescription")}
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

// Gruppierung der Blocktyp-Auswahl. Titel/Beschreibung liegen in
// templates.elementDefinitions.typeCategories.<key>. Typen, die hier (noch) fehlen,
// landen automatisch in der letzten Kategorie, damit ein neuer Blocktyp nie unsichtbar wird.
const elementTypeCategories: Array<{ key: "basics" | "finance" | "organisation"; types: string[] }> = [
  { key: "basics", types: ["1", "2", "3", "6", "11"] },
  { key: "finance", types: ["12", "13", "14"] },
  { key: "organisation", types: ["9", "10", "7", "15", "16", "17"] },
];

export function ElementDefinitionManager({
  initialDefinitions,
  knownEventTags,
  availableParticipants,
  availableEvents,
  availableLists,
  availableAccounts = [],
  tenantId,
  autoOpenCreate = false,
}: ElementDefinitionManagerProps) {
  const isParticipantSelectable = useParticipantSelectable();
  const t = useTranslations("templates.elementDefinitions");
  const tTypes = useTranslations("templates");
  const locale = useLocale();
  const elementTypeOptions = buildElementTypeOptions(tTypes);
  const matrixEmbeddedBlockOptions = matrixEmbeddedBlockOptionsList(tTypes);
  const { tagConfig, updateTagColor, renameTag } = useTagConfig();
  const showToast = useToast();
  const confirm = useConfirm();
  const [definitions, setDefinitions] = useState(initialDefinitions);
  const [duplicatingDefinitionId, setDuplicatingDefinitionId] = useState<string | null>(null);
  const [selectedDefinitionId, setSelectedDefinitionId] = useState<string | null>(initialDefinitions[0]?.id ?? null);
  const [definitionForm, setDefinitionForm] = useState<DefinitionFormState>(
    initialDefinitions[0] ? definitionFormFromDefinition(initialDefinitions[0]) : initialDefinitionForm
  );
  const [createDefinitionForm, setCreateDefinitionForm] = useState(initialDefinitionForm);
  const [createBlockForm, setCreateBlockForm] = useState<BlockFormState>({
    ...initialBlockForm,
    id: nextBlockId(initialDefinitions[0]?.blocks ?? []),
    sort_index: nextSortIndex(initialDefinitions[0]?.blocks ?? [])
  });
  const [selectedBlockId, setSelectedBlockId] = useState<number | null>(initialDefinitions[0]?.blocks[0]?.id ?? null);
  const [blockForm, setBlockForm] = useState<BlockFormState>(
    initialDefinitions[0]?.blocks[0] ? blockFormFromBlock(initialDefinitions[0].blocks[0]) : initialBlockForm
  );
  const [showDetailModal, setShowDetailModal] = useState(false);
  const [showCreateBlockModal, setShowCreateBlockModal] = useState(false);
  const [creatingNewDefinition, setCreatingNewDefinition] = useState(false);
  const [showEditBlockModal, setShowEditBlockModal] = useState(false);
  const [typePickerMode, setTypePickerMode] = useState<"create" | "edit" | null>(null);
  const [showCreateBlockHelp, setShowCreateBlockHelp] = useState(false);
  const [showEditBlockHelp, setShowEditBlockHelp] = useState(false);
  const [matrixDesignerMode, setMatrixDesignerMode] = useState<"create" | "edit" | null>(null);
  const [selectedMatrixRowId, setSelectedMatrixRowId] = useState<string | null>(null);
  const [selectedMatrixColumnId, setSelectedMatrixColumnId] = useState<string | null>(null);
  const [tableDesignerMode, setTableDesignerMode] = useState<"create" | "edit" | null>(null);
  const [selectedTableRowId, setSelectedTableRowId] = useState<string | null>(null);
  const [draggedTableRowId, setDraggedTableRowId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [draggedBlockId, setDraggedBlockId] = useState<number | null>(null);
  const [matrixPreviewColumns, setMatrixPreviewColumns] = useState<Array<{ id: string; title: string }> | null>(null);
  const [matrixPreviewLoading, setMatrixPreviewLoading] = useState(false);
  const [listEntryOptionsByListId, setListEntryOptionsByListId] = useState<Record<string, StructuredListEntry[]>>({});
  const participantOptions = Array.isArray(availableParticipants) ? availableParticipants : [];
  const eventOptions = Array.isArray(availableEvents) ? availableEvents : [];
  const listOptions = Array.isArray(availableLists) ? availableLists : [];

  // Erlaubt den Sprung von anderen Seiten (z. B. der Vorlagenbearbeitung) direkt in die
  // Neuanlage eines Elements, ohne dass hier extra Zustand pro Aufrufer verdrahtet werden muss.
  useEffect(() => {
    if (!autoOpenCreate) {
      return;
    }
    setCreateDefinitionForm(initialDefinitionForm);
    setCreateBlockForm({ ...initialBlockForm, id: "1", sort_index: "10" });
    setCreatingNewDefinition(true);
    setShowCreateBlockModal(true);
    setTypePickerMode("create");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoOpenCreate]);

  const filteredDefinitions = useMemo(
    () =>
      definitions.filter((definition) => {
        const haystack = `${definition.title} ${definition.description ?? ""}`.toLowerCase();
        return !search || haystack.includes(search.toLowerCase());
      }),
    [definitions, search]
  );

  const selectedDefinition = useMemo(
    () => definitions.find((definition) => definition.id === selectedDefinitionId) ?? null,
    [definitions, selectedDefinitionId]
  );
  const selectedBlock = useMemo(
    () => selectedDefinition?.blocks.find((block) => block.id === selectedBlockId) ?? null,
    [selectedDefinition, selectedBlockId]
  );
  const sortedAvailableEvents = useMemo(
    () => [...eventOptions].sort((left, right) => left.event_date.localeCompare(right.event_date)),
    [eventOptions]
  );
  const matrixDesignerForm = matrixDesignerMode === "create" ? createBlockForm : matrixDesignerMode === "edit" ? blockForm : null;
  const matrixDesignerRows = matrixDesignerForm?.table_fields ?? [];
  const matrixDesignerColumns = matrixDesignerForm?.matrix_columns ?? [];

  // Clear preview when source settings change
  const matrixSourceKey = matrixDesignerForm
    ? `${matrixDesignerForm.auto_source_type}:${matrixDesignerForm.auto_source_list_id}:${matrixDesignerForm.auto_source_event_tag}`
    : "";
  useEffect(() => {
    setMatrixPreviewColumns(null);
  }, [matrixSourceKey]);

  // Pre-load entries for lists already referenced by "Zeile aus Liste" rows, so the
  // entry-picker shows the currently selected entry when re-opening a saved block.
  const referencedListEntryListIds = [...createBlockForm.table_fields, ...blockForm.table_fields]
    .filter((field) => field.row_type === "list_entry")
    .map((field) => (field.row_config as Record<string, unknown> | undefined)?.linked_list_id)
    .filter((id): id is string => typeof id === "string" && id.length > 0);
  const referencedListEntryListIdsKey = [...new Set(referencedListEntryListIds)].sort().join(",");
  useEffect(() => {
    for (const listId of referencedListEntryListIdsKey.split(",").filter(Boolean)) {
      void ensureListEntriesLoaded(listId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [referencedListEntryListIdsKey]);

  async function loadMatrixPreview() {
    if (!matrixDesignerForm) return;
    const source = matrixDesignerForm.auto_source_type;
    setMatrixPreviewLoading(true);
    try {
      if (source === "participants") {
        setMatrixPreviewColumns(
          participantOptions.filter(isParticipantSelectable).map((p) => ({ id: `prev-p-${p.id}`, title: p.display_name }))
        );
      } else if (source === "events") {
        const tagFilter = matrixDesignerForm.auto_source_event_tag.trim().toLowerCase();
        const filtered = tagFilter
          ? sortedAvailableEvents.filter((e) => String(e.tag ?? "").toLowerCase() === tagFilter)
          : sortedAvailableEvents;
        setMatrixPreviewColumns(filtered.map((e) => ({ id: `prev-e-${e.id}`, title: e.title })));
      } else if (source === "list") {
        const listDefId = matrixDesignerForm.auto_source_list_id || null;
        if (!listDefId) {
          setMatrixPreviewColumns([]);
        } else {
          const entries = await browserApiFetch<StructuredListEntry[]>(`/api/lists/${listDefId}/entries`);
          setMatrixPreviewColumns(
            (entries ?? []).map((entry) => ({
              id: `prev-l-${entry.id}`,
              title:
                String(asObject(entry.column_one_value).text_value ?? "").trim() ||
                String(asObject(entry.column_two_value).text_value ?? "").trim() ||
                t("entryFallback", { id: entry.id }),
            }))
          );
        }
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("previewLoadFailed"), "error");
    } finally {
      setMatrixPreviewLoading(false);
    }
  }
  const selectedMatrixRow =
    matrixDesignerRows.find((row) => row.id === selectedMatrixRowId) ?? matrixDesignerRows[0] ?? null;
  // row_config contains the embedded block config (or event filter config)
  const selectedMatrixEmbeddedConfig = selectedMatrixRow
    ? (typeof selectedMatrixRow.row_config === "object" && selectedMatrixRow.row_config
        ? selectedMatrixRow.row_config as Record<string, unknown>
        : matrixEmbeddedBlockConfiguration(
            String(asObject(selectedMatrixRow).embedded_element_type_id ?? ""),
            asObject(selectedMatrixRow).embedded_configuration_json
          ))
    : {};
  const selectedMatrixColumn =
    matrixDesignerColumns.find((column) => column.id === selectedMatrixColumnId) ?? matrixDesignerColumns[0] ?? null;
  const tableDesignerForm = tableDesignerMode === "create" ? createBlockForm : tableDesignerMode === "edit" ? blockForm : null;
  const tableDesignerRows = tableDesignerForm?.table_fields ?? [];
  const selectedTableRow =
    tableDesignerRows.find((row) => row.id === selectedTableRowId) ?? tableDesignerRows[0] ?? null;
  const createLinkedList = useMemo(
    () => listOptions.find((entry) => entry.id === createBlockForm.linked_list_id) ?? null,
    [createBlockForm.linked_list_id, listOptions]
  );
  const editLinkedList = useMemo(
    () => listOptions.find((entry) => entry.id === blockForm.linked_list_id) ?? null,
    [blockForm.linked_list_id, listOptions]
  );

  function updateMatrixDesignerForm(updater: (current: BlockFormState) => BlockFormState) {
    if (matrixDesignerMode === "create") {
      setCreateBlockForm(updater);
      return;
    }
    if (matrixDesignerMode === "edit") {
      setBlockForm(updater);
    }
  }

  async function ensureListEntriesLoaded(listId: string) {
    if (!listId || listEntryOptionsByListId[listId]) {
      return;
    }
    try {
      const entries = await browserApiFetch<StructuredListEntry[]>(`/api/lists/${listId}/entries`);
      setListEntryOptionsByListId((current) => ({ ...current, [listId]: entries ?? [] }));
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("listEntriesLoadFailed"), "error");
    }
  }

  function describeListValue(value: Record<string, unknown> | null | undefined, valueType: string): string {
    if (!value) {
      return "";
    }
    if (valueType === "participant") {
      const id = typeof value.participant_id === "string" ? value.participant_id : null;
      return participantOptions.find((participant) => participant.id === id)?.display_name ?? "";
    }
    if (valueType === "participants") {
      const ids = Array.isArray(value.participant_ids) ? (value.participant_ids as unknown[]).filter((id): id is string => typeof id === "string") : [];
      return participantOptions
        .filter((participant) => ids.includes(participant.id))
        .map((participant) => participant.display_name)
        .join(", ");
    }
    if (valueType === "event") {
      const id = typeof value.event_id === "string" ? value.event_id : null;
      const eventRow = sortedAvailableEvents.find((entry) => entry.id === id);
      return eventRow ? `${formatDateRange(eventRow.event_date, eventRow.event_end_date)} · ${eventRow.title}` : "";
    }
    return String(value.text_value ?? "").trim();
  }

  function describeListEntry(entry: StructuredListEntry, definition: StructuredListDefinition): string {
    const colOne = describeListValue(entry.column_one_value as Record<string, unknown>, definition.column_one_value_type);
    const colTwo = describeListValue(entry.column_two_value as Record<string, unknown>, definition.column_two_value_type);
    return [colOne, colTwo].filter(Boolean).join(" – ") || t("emptyEntry");
  }

  function tableRowPreviewValue(field: BlockFormState["table_fields"][number]): string {
    if (field.row_type === "participant") {
      const participant = participantOptions.find((entry) => entry.id === field.template_participant_id);
      return participant?.display_name ?? "—";
    }
    if (field.row_type === "participants") {
      const ids = field.template_participant_ids ?? [];
      const names = participantOptions.filter((entry) => ids.includes(entry.id)).map((entry) => entry.display_name);
      return names.length ? names.join(", ") : "—";
    }
    if (field.row_type === "event") {
      const eventRow = sortedAvailableEvents.find((entry) => entry.id === field.template_event_id);
      return eventRow ? `${formatDateRange(eventRow.event_date, eventRow.event_end_date)} · ${eventRow.title}` : "—";
    }
    if (field.row_type === "list_entry") {
      const rowConfig = (field.row_config && typeof field.row_config === "object" ? field.row_config : {}) as Record<string, unknown>;
      const listId = typeof rowConfig.linked_list_id === "string" ? rowConfig.linked_list_id : null;
      const entryId = typeof rowConfig.linked_list_entry_id === "string" ? rowConfig.linked_list_entry_id : null;
      const listDefinition = listOptions.find((entry) => entry.id === listId);
      const listEntry = listId ? (listEntryOptionsByListId[listId] ?? []).find((entry) => entry.id === entryId) : undefined;
      if (!listDefinition || !listEntry) {
        return t("noEntrySelected");
      }
      return `${listDefinition.name}: ${describeListEntry(listEntry, listDefinition)}`;
    }
    return field.template_value?.trim() || "—";
  }

  function updateSelectedMatrixRowConfig(patch: Record<string, unknown>) {
    if (!selectedMatrixRow) {
      return;
    }
    updateMatrixDesignerForm((current) => ({
      ...current,
      table_fields: current.table_fields.map((entry) =>
        entry.id === selectedMatrixRow.id
          ? {
              ...entry,
              row_config: {
                ...(typeof entry.row_config === "object" && entry.row_config ? entry.row_config : {}),
                ...patch,
              },
            }
          : entry
      ),
    }));
  }

  function renderTypedInitialValueEditor(
    field: BlockFormState["table_fields"][number],
    applyPatch: (patch: Partial<BlockFormState["table_fields"][number]>) => void,
    fieldLabel = "Initialwert / Platzhalter"
  ) {
    if (field.row_type === "participant") {
      return (
        <label className="field-stack">
          <span className="field-label">{t("initialParticipant")}</span>
          <SearchableSelect
            options={participantOptions}
            isOptionSelectable={isParticipantSelectable}
            getId={(participant) => participant.id}
            getLabel={(participant) => participant.display_name}
            value={field.template_participant_id || null}
            onChange={(participant) => applyPatch({ template_participant_id: participant ? participant.id : "" })}
            nullLabel={t("noDefaultValue")}
          />
        </label>
      );
    }

    if (field.row_type === "participants") {
      return (
        <label className="field-stack">
          <span className="field-label">{t("initialParticipants")}</span>
          <SearchableMultiSelect
            options={participantOptions}
            isOptionSelectable={isParticipantSelectable}
            getId={(participant) => participant.id}
            getLabel={(participant) => participant.display_name}
            values={field.template_participant_ids ?? []}
            onChange={(ids) => applyPatch({ template_participant_ids: ids })}
            emptySelectionLabel={t("noDefaultValue")}
          />
        </label>
      );
    }

    if (field.row_type === "event") {
      return (
        <label className="field-stack">
          <span className="field-label">{t("initialEvent")}</span>
          <SearchableSelect
            options={sortedAvailableEvents}
            getId={(eventRow) => eventRow.id}
            getLabel={(eventRow) => `${formatDateRange(eventRow.event_date, eventRow.event_end_date)} · ${eventRow.title}`}
            value={field.template_event_id || null}
            onChange={(eventRow) => applyPatch({ template_event_id: eventRow ? eventRow.id : "" })}
            nullLabel={t("noDefaultValue")}
          />
        </label>
      );
    }

    if (field.row_type === "events") {
      return <p className="muted">{t("autoEventRowsHint")}</p>;
    }

    if (field.row_type === "list_entry") {
      const rowConfig = (field.row_config && typeof field.row_config === "object" ? field.row_config : {}) as Record<string, unknown>;
      const selectedListId = typeof rowConfig.linked_list_id === "string" ? rowConfig.linked_list_id : null;
      const selectedListDefinition = listOptions.find((entry) => entry.id === selectedListId) ?? null;
      const entryOptions = selectedListId ? listEntryOptionsByListId[selectedListId] ?? [] : [];
      const fixedColumn = rowConfig.list_fixed_column === "column_two" ? "column_two" : "column_one";
      return (
        <div className="field-stack">
          <label className="field-stack">
            <span className="field-label">{t("linkedListFieldLabel")}</span>
            <SearchableSelect
              options={listOptions}
              getId={(listDefinition) => listDefinition.id}
              getLabel={(listDefinition) => listDefinition.name}
              value={selectedListId}
              onChange={(listDefinition) => {
                const nextListId = listDefinition ? listDefinition.id : null;
                if (nextListId) {
                  void ensureListEntriesLoaded(nextListId);
                }
                applyPatch({ row_config: { ...rowConfig, linked_list_id: nextListId, linked_list_entry_id: null } });
              }}
              nullLabel={t("chooseListPlaceholder")}
            />
          </label>
          {selectedListId ? (
            <>
              <label className="field-stack">
                <span className="field-label">{t("listEntryFieldLabel")}</span>
                <SearchableSelect
                  options={entryOptions}
                  getId={(entry) => entry.id}
                  getLabel={(entry) => (selectedListDefinition ? describeListEntry(entry, selectedListDefinition) : `Eintrag ${entry.id}`)}
                  value={typeof rowConfig.linked_list_entry_id === "string" ? rowConfig.linked_list_entry_id : null}
                  onChange={(entry) =>
                    applyPatch({
                      row_config: { ...rowConfig, linked_list_entry_id: entry ? entry.id : null },
                    })
                  }
                  nullLabel={t("chooseEntryPlaceholder")}
                />
              </label>
              <label className="field-stack">
                <span className="field-label">{t("fixedColumnLabel")}</span>
                <select
                  value={fixedColumn}
                  onChange={(event) => applyPatch({ row_config: { ...rowConfig, list_fixed_column: event.target.value } })}
                >
                  <option value="column_one">{selectedListDefinition?.column_one_title || "Spalte 1"} ist fix</option>
                  <option value="column_two">{selectedListDefinition?.column_two_title || "Spalte 2"} ist fix</option>
                </select>
              </label>
              <label className="checkbox-line">
                <input
                  type="checkbox"
                  checked={rowConfig.value_source === "historical"}
                  onChange={(event) =>
                    applyPatch({
                      row_config: { ...rowConfig, value_source: event.target.checked ? "historical" : "live" },
                    })
                  }
                />
                Historische Daten verwenden
              </label>
              <p className="muted" style={{ fontSize: "var(--text-sm)" }}>
                Zeigt den Wert aus dem Snapshot des Zyklus, in den das jeweilige Protokoll fällt (statt immer den aktuellen Listenwert).
                Existiert für diesen Zyklus noch kein Snapshot, wird der aktuelle Wert verwendet.
              </p>
            </>
          ) : null}
        </div>
      );
    }

    return (
      <label className="field-stack">
        <span className="field-label">{fieldLabel}</span>
        <input
          value={field.template_value ?? ""}
          onChange={(event) => applyPatch({ template_value: event.target.value })}
          placeholder={t("valuePlaceholderGeneric")}
        />
      </label>
    );
  }

  function ensureMatrixDesignerDefaults(mode: "create" | "edit") {
    const current = mode === "create" ? createBlockForm : blockForm;
    const ensuredRows = current.table_fields.length ? current.table_fields : [defaultFieldRow(nextTableFieldId(current.table_fields))];
    const isManual = current.matrix_mode !== "auto";
    const ensuredColumns = isManual && !current.matrix_columns.length
      ? [defaultMatrixColumn(nextMatrixColumnConfigId(current.matrix_columns))]
      : current.matrix_columns;
    if (mode === "create") {
      setCreateBlockForm((existing) => ({
        ...existing,
        table_fields: existing.table_fields.length ? existing.table_fields : ensuredRows,
        matrix_columns: isManual && !existing.matrix_columns.length ? ensuredColumns : existing.matrix_columns,
      }));
    } else {
      setBlockForm((existing) => ({
        ...existing,
        table_fields: existing.table_fields.length ? existing.table_fields : ensuredRows,
        matrix_columns: isManual && !existing.matrix_columns.length ? ensuredColumns : existing.matrix_columns,
      }));
    }
    setSelectedMatrixRowId(ensuredRows[0]?.id ?? null);
    setSelectedMatrixColumnId(ensuredColumns[0]?.id ?? null);
  }

  function openMatrixDesigner(mode: "create" | "edit") {
    ensureMatrixDesignerDefaults(mode);
    setMatrixDesignerMode(mode);
  }

  function selectDefinition(definition: ElementDefinition) {
    setSelectedDefinitionId(definition.id);
    setDefinitionForm(definitionFormFromDefinition(definition));
    const firstBlock = definition.blocks[0] ?? null;
    setSelectedBlockId(firstBlock?.id ?? null);
    setBlockForm(firstBlock ? blockFormFromBlock(firstBlock) : { ...initialBlockForm, id: nextBlockId(definition.blocks), sort_index: nextSortIndex(definition.blocks) });
    setCreateBlockForm({ ...initialBlockForm, id: nextBlockId(definition.blocks), sort_index: nextSortIndex(definition.blocks) });
    setShowDetailModal(true);
  }

  function replaceDefinition(updated: ElementDefinition) {
    setDefinitions((current) =>
      current.map((definition) => (definition.id === updated.id ? updated : definition))
    );
  }

  async function createDefinitionWithBlock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const created = await browserApiFetch<ElementDefinition>("/api/element-definitions", {
        method: "POST",
        body: JSON.stringify({
          tenant_id: tenantId,
          title: createDefinitionForm.title,
          description: createDefinitionForm.description || null,
          is_active: true,
          blocks: [blockPayload({ ...createBlockForm, sort_index: "10" })]
        })
      });
      setDefinitions((current) => [created, ...current]);
      setCreateDefinitionForm(initialDefinitionForm);
      setShowCreateBlockModal(false);
      setCreatingNewDefinition(false);
      selectDefinition(created);
      showToast(t("elementCreatedToast", { title: created.title }), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("elementCreateFailed"), "error");
    }
  }

  async function duplicateDefinition(definition: ElementDefinition) {
    if (duplicatingDefinitionId) return;
    setDuplicatingDefinitionId(definition.id);
    try {
      const created = await browserApiFetch<ElementDefinition>("/api/element-definitions", {
        method: "POST",
        body: JSON.stringify({
          title: `${definition.title} (Kopie)`,
          description: definition.description,
          is_active: definition.is_active,
          blocks: definition.blocks,
        }),
      });
      setDefinitions((current) => [created, ...current]);
      selectDefinition(created);
      showToast(t("elementDuplicatedToast", { title: created.title }), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("elementDuplicateFailed"), "error");
    } finally {
      setDuplicatingDefinitionId(null);
    }
  }

  async function saveDefinition(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedDefinition) return;
    try {
      const updated = await browserApiFetch<ElementDefinition>(`/api/element-definitions/${selectedDefinition.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: definitionForm.title,
          description: definitionForm.description || null,
          blocks: selectedDefinition.blocks
        })
      });
      replaceDefinition(updated);
      showToast(t("elementSavedToast", { title: updated.title }), "success");
      setShowDetailModal(false);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("elementSaveFailed"), "error");
    }
  }

  async function deleteDefinition(definitionId: string) {
    const ok = await confirm({
      message: t("deleteElementConfirm"),
      tone: "danger",
      confirmLabel: t("delete")
    });
    if (!ok) return;
    try {
      const deletedTitle = definitions.find((definition) => definition.id === definitionId)?.title ?? t("unnamed");
      await browserApiFetch(`/api/element-definitions/${definitionId}`, { method: "DELETE" });
      const nextDefinitions = definitions.filter((definition) => definition.id !== definitionId);
      setDefinitions(nextDefinitions);
      if (nextDefinitions[0]) {
        selectDefinition(nextDefinitions[0]);
      } else {
        setSelectedDefinitionId(null);
        setSelectedBlockId(null);
        setDefinitionForm(initialDefinitionForm);
        setBlockForm(initialBlockForm);
      }
      showToast(t("elementDeletedToast", { title: deletedTitle }), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("elementDeleteFailed"), "error");
    }
  }

  async function saveBlocks(nextBlocks: ElementDefinitionBlock[], message: string) {
    if (!selectedDefinition) return null;
    try {
      const updated = await browserApiFetch<ElementDefinition>(`/api/element-definitions/${selectedDefinition.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          blocks: nextBlocks
        })
      });
      replaceDefinition(updated);
      showToast(message, "success");
      const selected = updated.blocks.find((block) => block.id === selectedBlockId) ?? updated.blocks[0] ?? null;
      setSelectedBlockId(selected?.id ?? null);
      setBlockForm(selected ? blockFormFromBlock(selected) : { ...initialBlockForm, id: nextBlockId(updated.blocks), sort_index: nextSortIndex(updated.blocks) });
      setCreateBlockForm({ ...initialBlockForm, id: nextBlockId(updated.blocks), sort_index: nextSortIndex(updated.blocks) });
      return updated;
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("blockUpdateFailed"), "error");
      return null;
    }
  }

  async function persistEditedBlock(message: string) {
    if (!selectedDefinition || !selectedBlock) {
      return false;
    }
    const updatedBlock = blockPayload(blockForm);
    const nextBlocks = resequenceBlocks(
      selectedDefinition.blocks
        .map((block) => (block.id === selectedBlock.id ? updatedBlock : block))
        .sort((left, right) => left.sort_index - right.sort_index)
    );
    const updated = await saveBlocks(nextBlocks, message);
    return Boolean(updated);
  }

  // Closing (X / backdrop click) only closes the designer - it no longer silently
  // saves. Edits made here live in the same blockForm/createBlockForm state as every other
  // field in the surrounding "Block bearbeiten"/"Block anlegen" form, so nothing is lost:
  // they're picked up by that form's own explicit "Speichern"/"anlegen" submit exactly like a
  // title or description edit would be. Use "Übernehmen" below to save immediately instead.
  function closeMatrixDesigner() {
    setMatrixDesignerMode(null);
  }

  async function saveMatrixDesigner() {
    if (matrixDesignerMode === "edit") {
      const saved = await persistEditedBlock(t("matrixSavedToast"));
      if (!saved) {
        return;
      }
    }
    setMatrixDesignerMode(null);
  }

  function ensureTableDesignerDefaults(mode: "create" | "edit") {
    const current = mode === "create" ? createBlockForm : blockForm;
    const ensuredRows = current.table_fields.length ? current.table_fields : [defaultFieldRow(nextTableFieldId(current.table_fields))];
    if (mode === "create") {
      setCreateBlockForm((existing) => ({
        ...existing,
        table_fields: existing.table_fields.length ? existing.table_fields : ensuredRows,
      }));
    } else {
      setBlockForm((existing) => ({
        ...existing,
        table_fields: existing.table_fields.length ? existing.table_fields : ensuredRows,
      }));
    }
    setSelectedTableRowId(ensuredRows[0]?.id ?? null);
  }

  function openTableDesigner(mode: "create" | "edit", rowId?: string) {
    ensureTableDesignerDefaults(mode);
    if (rowId) {
      setSelectedTableRowId(rowId);
    }
    setTableDesignerMode(mode);
  }

  function updateTableDesignerForm(updater: (current: BlockFormState) => BlockFormState) {
    if (tableDesignerMode === "create") {
      setCreateBlockForm(updater);
      return;
    }
    if (tableDesignerMode === "edit") {
      setBlockForm(updater);
    }
  }

  function addTableDesignerRow() {
    updateTableDesignerForm((current) => {
      const nextId = nextTableFieldId(current.table_fields);
      setSelectedTableRowId(nextId);
      return { ...current, table_fields: [...current.table_fields, defaultFieldRow(nextId)] };
    });
  }

  function removeTableDesignerRow(rowId: string) {
    updateTableDesignerForm((current) => {
      const nextRows = current.table_fields.filter((entry) => entry.id !== rowId);
      if (selectedTableRowId === rowId) {
        setSelectedTableRowId(nextRows[0]?.id ?? null);
      }
      return { ...current, table_fields: nextRows };
    });
  }

  function reorderTableDesignerRows(sourceId: string, targetId: string) {
    if (sourceId === targetId) {
      return;
    }
    updateTableDesignerForm((current) => {
      const rows = [...current.table_fields];
      const sourceIndex = rows.findIndex((entry) => entry.id === sourceId);
      const targetIndex = rows.findIndex((entry) => entry.id === targetId);
      if (sourceIndex === -1 || targetIndex === -1) {
        return current;
      }
      const [moved] = rows.splice(sourceIndex, 1);
      rows.splice(targetIndex, 0, moved);
      return { ...current, table_fields: rows };
    });
  }

  // See closeMatrixDesigner above for why closing no longer auto-saves.
  function closeTableDesigner() {
    setTableDesignerMode(null);
  }

  async function saveTableDesigner() {
    if (tableDesignerMode === "edit") {
      const saved = await persistEditedBlock(t("tableSavedToast"));
      if (!saved) {
        return;
      }
    }
    setTableDesignerMode(null);
  }

  async function createBlock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedDefinition) return;
    const nextBlocks = resequenceBlocks(
      [...selectedDefinition.blocks, blockPayload({ ...createBlockForm, sort_index: nextSortIndex(selectedDefinition.blocks) })].sort(
        (left, right) => left.sort_index - right.sort_index
      )
    );
    const saved = await saveBlocks(nextBlocks, t("blockAddedToast"));
    if (saved) setShowCreateBlockModal(false);
  }

  async function updateBlock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const saved = await persistEditedBlock(t("blockSavedToast"));
    if (saved) {
      setShowEditBlockModal(false);
    }
  }

  async function deleteBlock(blockId: number) {
    if (!selectedDefinition) return;
    const ok = await confirm({
      message: t("deleteBlockConfirm"),
      tone: "danger",
      confirmLabel: t("delete")
    });
    if (!ok) return;
    const nextBlocks = resequenceBlocks(selectedDefinition.blocks.filter((block) => block.id !== blockId));
    await saveBlocks(nextBlocks, t("blockDeletedToast"));
  }

  async function reorderBlocks(sourceId: number, targetId: number) {
    if (!selectedDefinition || sourceId === targetId) return;
    const ordered = [...selectedDefinition.blocks].sort((left, right) => left.sort_index - right.sort_index);
    const sourceIndex = ordered.findIndex((block) => block.id === sourceId);
    const targetIndex = ordered.findIndex((block) => block.id === targetId);
    if (sourceIndex === -1 || targetIndex === -1) {
      return;
    }
    const [moved] = ordered.splice(sourceIndex, 1);
    ordered.splice(targetIndex, 0, moved);
    await saveBlocks(resequenceBlocks(ordered), t("blockOrderSavedToast"));
  }

function applyBlockType(elementTypeId: string, mode: "create" | "edit") {
  const nextEditable = !["5", "7", "9", "16"].includes(elementTypeId);
  if (mode === "create") {
    setCreateBlockForm((current) => ({
      ...current,
      element_type_id: elementTypeId,
      is_editable: nextEditable,
      table_fields:
          ["6", "11"].includes(elementTypeId) && current.table_fields.length === 0
            ? [defaultFieldRow("1")]
            : current.table_fields,
        matrix_columns:
          elementTypeId === "11" && current.matrix_columns.length === 0
            ? [defaultMatrixColumn("matrix-column-1")]
            : current.matrix_columns,
      }));
  } else {
    setBlockForm((current) => ({
      ...current,
      element_type_id: elementTypeId,
      is_editable: nextEditable,
      table_fields:
          ["6", "11"].includes(elementTypeId) && current.table_fields.length === 0
            ? [defaultFieldRow("1")]
            : current.table_fields,
        matrix_columns:
          elementTypeId === "11" && current.matrix_columns.length === 0
            ? [defaultMatrixColumn("matrix-column-1")]
            : current.matrix_columns,
      }));
  }
    setTypePickerMode(null);
  }

  function renderBlockTypePreview(elementTypeId: string) {
    // Todo: Checkboxen vor Aufgabentext
    if (elementTypeId === "2") {
      return (
        <div className="block-type-preview">
          <div className="block-type-preview-row">
            <div className="block-type-preview-checkbox block-type-preview-checkbox-checked" />
            <div className="block-type-preview-line block-type-preview-line-short" />
          </div>
          <div className="block-type-preview-row">
            <div className="block-type-preview-checkbox" />
            <div className="block-type-preview-line" />
          </div>
          <div className="block-type-preview-row">
            <div className="block-type-preview-checkbox block-type-preview-checkbox-checked" />
            <div className="block-type-preview-line block-type-preview-line-short" />
          </div>
        </div>
      );
    }
    // Bild: Bildfläche mit Bildunterschrift
    if (elementTypeId === "3") {
      return (
        <div className="block-type-preview">
          <div className="block-type-preview-image" />
          <div className="block-type-preview-line block-type-preview-line-short" />
        </div>
      );
    }
    // Tabelle: zweispaltiges Raster aus Label- und Wertzellen
    if (elementTypeId === "6") {
      return (
        <div className="block-type-preview">
          <div className="block-type-preview-grid block-type-preview-grid-cols-2">
            <div className="block-type-preview-cell" />
            <div className="block-type-preview-cell block-type-preview-cell-accent" />
            <div className="block-type-preview-cell" />
            <div className="block-type-preview-cell block-type-preview-cell-accent" />
            <div className="block-type-preview-cell" />
            <div className="block-type-preview-cell block-type-preview-cell-accent" />
          </div>
        </div>
      );
    }
    // Terminliste: Datums-Tags mit Termintitel
    if (elementTypeId === "7") {
      return (
        <div className="block-type-preview">
          <div className="block-type-preview-row">
            <div className="block-type-preview-tag" />
            <div className="block-type-preview-line" />
          </div>
          <div className="block-type-preview-row">
            <div className="block-type-preview-tag" />
            <div className="block-type-preview-line block-type-preview-line-short" />
          </div>
          <div className="block-type-preview-row">
            <div className="block-type-preview-tag" />
            <div className="block-type-preview-line" />
          </div>
        </div>
      );
    }
    // Anwesenheit: Status-Punkte vor Teilnehmernamen
    if (elementTypeId === "9") {
      return (
        <div className="block-type-preview">
          <div className="block-type-preview-row">
            <div className="block-type-preview-dot" />
            <div className="block-type-preview-line block-type-preview-line-short" />
          </div>
          <div className="block-type-preview-row">
            <div className="block-type-preview-dot" />
            <div className="block-type-preview-line" />
          </div>
          <div className="block-type-preview-row">
            <div className="block-type-preview-dot block-type-preview-dot-muted" />
            <div className="block-type-preview-line block-type-preview-line-short" />
          </div>
          <div className="block-type-preview-row">
            <div className="block-type-preview-dot" />
            <div className="block-type-preview-line" />
          </div>
        </div>
      );
    }
    // Ein-/Austritte: Namenszeilen mit Pfeil-Icon (rein/raus)
    if (elementTypeId === "16") {
      return (
        <div className="block-type-preview">
          <div className="block-type-preview-row">
            <div className="block-type-preview-dot" />
            <div className="block-type-preview-line block-type-preview-line-short" />
          </div>
          <div className="block-type-preview-row">
            <div className="block-type-preview-dot block-type-preview-dot-muted" />
            <div className="block-type-preview-line" />
          </div>
        </div>
      );
    }
    // Sitzungsdatum: Kalenderkachel mit hervorgehobenem Tag
    if (elementTypeId === "10") {
      return (
        <div className="block-type-preview-calendar">
          <div className="block-type-preview-calendar-head" />
          <div className="block-type-preview-calendar-body">
            {Array.from({ length: 8 }).map((_, index) => (
              <div
                key={index}
                className={`block-type-preview-calendar-cell${index === 5 ? " block-type-preview-calendar-cell-active" : ""}`}
              />
            ))}
          </div>
        </div>
      );
    }
    // Matrix: Kopfzeile plus mehrspaltiges Datenraster
    if (elementTypeId === "11") {
      return (
        <div className="block-type-preview">
          <div className="block-type-preview-grid block-type-preview-grid-cols-3">
            <div className="block-type-preview-cell block-type-preview-cell-accent" />
            <div className="block-type-preview-cell block-type-preview-cell-accent" />
            <div className="block-type-preview-cell block-type-preview-cell-accent" />
            <div className="block-type-preview-cell" />
            <div className="block-type-preview-cell" />
            <div className="block-type-preview-cell" />
            <div className="block-type-preview-cell" />
            <div className="block-type-preview-cell" />
            <div className="block-type-preview-cell" />
          </div>
        </div>
      );
    }
    // Kontostand: grosser Saldo-Balken mit Kontolabel
    if (elementTypeId === "12") {
      return (
        <div className="block-type-preview">
          <div className="block-type-preview-line block-type-preview-line-short" />
          <div className="block-type-preview-amount" />
          <div className="block-type-preview-line block-type-preview-line-short" />
        </div>
      );
    }
    // Transaktionen: Beschreibung links, Betrag rechtsbündig
    if (elementTypeId === "13") {
      return (
        <div className="block-type-preview">
          <div className="block-type-preview-row-between">
            <div className="block-type-preview-line" />
            <div className="block-type-preview-tag" />
          </div>
          <div className="block-type-preview-row-between">
            <div className="block-type-preview-line block-type-preview-line-short" />
            <div className="block-type-preview-tag" />
          </div>
          <div className="block-type-preview-row-between">
            <div className="block-type-preview-line" />
            <div className="block-type-preview-tag" />
          </div>
        </div>
      );
    }
    // Bussenliste: wie Transaktionen, aber mit Warn-Farbe für den Betrag
    if (elementTypeId === "14") {
      return (
        <div className="block-type-preview">
          <div className="block-type-preview-row-between">
            <div className="block-type-preview-line" />
            <div className="block-type-preview-tag block-type-preview-tag-warn" />
          </div>
          <div className="block-type-preview-row-between">
            <div className="block-type-preview-line block-type-preview-line-short" />
            <div className="block-type-preview-tag block-type-preview-tag-warn" />
          </div>
          <div className="block-type-preview-row-between">
            <div className="block-type-preview-line" />
            <div className="block-type-preview-tag block-type-preview-tag-warn" />
          </div>
        </div>
      );
    }
    // Diagramm: Balkendiagramm
    if (elementTypeId === "15") {
      return (
        <div className="block-type-preview">
          <div className="block-type-preview-bars">
            <div className="block-type-preview-bar" style={{ height: "45%" }} />
            <div className="block-type-preview-bar" style={{ height: "78%" }} />
            <div className="block-type-preview-bar" style={{ height: "32%" }} />
            <div className="block-type-preview-bar" style={{ height: "90%" }} />
            <div className="block-type-preview-bar" style={{ height: "58%" }} />
          </div>
        </div>
      );
    }
    // Sitzungsnotizen: Notiz-Label mit freien Textzeilen
    if (elementTypeId === "17") {
      return (
        <div className="block-type-preview">
          <div className="block-type-preview-chip-row">
            <div className="block-type-preview-chip" />
          </div>
          <div className="block-type-preview-line" />
          <div className="block-type-preview-line block-type-preview-line-short" />
          <div className="block-type-preview-line" />
        </div>
      );
    }
    // Text (und Fallback für nicht in der Auswahl gelistete Typen): klassisches Fliesstext-Skelett
    return (
      <div className="block-type-preview">
        <div className="block-type-preview-title" />
        <div className="block-type-preview-line" />
        <div className="block-type-preview-line" />
        <div className="block-type-preview-line block-type-preview-line-short" />
      </div>
    );
  }

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("pageTitle")}</h1>
          <p className="muted">{t("pageIntro1")}</p>
          <p className="muted">{t("pageIntro2")}</p>
        </div>
        <button
          type="button"
          className="button-primary"
          onClick={() => {
            setCreateDefinitionForm(initialDefinitionForm);
            setCreateBlockForm({ ...initialBlockForm, id: "1", sort_index: "10" });
            setCreatingNewDefinition(true);
            setShowCreateBlockModal(true);
            setTypePickerMode("create");
          }}
        >
          + Neues Element
        </button>
      </div>

      <div className="list-filter-row">
        <div />
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder={t("searchPlaceholder")} />
        </div>
      </div>

      <DataTable className="data-table-lg" columns={[t("colElement"), t("colBlocks"), t("colActions")]}>
        {filteredDefinitions.map((definition) => (
          <tr key={definition.id} className={`table-row-clickable${selectedDefinitionId === definition.id ? " table-row-active" : ""}`} onClick={() => selectDefinition(definition)}>
            <td>
              <strong>{definition.title}</strong>
            </td>
            <td>{t("blockCount", { count: definition.blocks.length })}</td>
            <td>
              <div className="table-actions">
                <button
                  type="button"
                  className="button-secondary button-ghost"
                  disabled={duplicatingDefinitionId !== null}
                  onClick={(event) => {
                    event.stopPropagation();
                    void duplicateDefinition(definition);
                  }}
                >
                  {duplicatingDefinitionId === definition.id ? t("duplicating") : t("duplicate")}
                </button>
                <button type="button" className="button-secondary button-danger" onClick={(event) => {
                  event.stopPropagation();
                  void deleteDefinition(definition.id);
                }}>{t("delete")}</button>
              </div>
            </td>
          </tr>
        ))}
      </DataTable>

      <Modal
        open={showDetailModal && !!selectedDefinition}
        onClose={() => {
        setShowDetailModal(false);
          setShowCreateBlockModal(false);
          setShowEditBlockModal(false);
          setMatrixDesignerMode(null);
        }}
        title={selectedDefinition ? t("editElementNamed", { name: selectedDefinition.title }) : t("editElementTitle")}
        description={t("editModalDescription")}
        size="wide"
        hideCloseButton
        headerActions={
          <>
            <button type="button" className="button-ghost modal-close" onClick={() => setShowDetailModal(false)}>
              Abbrechen
            </button>
            <button data-modal-save type="submit" form="element-definition-form" className="button-secondary">
              Speichern
            </button>
          </>
        }
      >
        {selectedDefinition ? (
          <div className="section-stack">
            <ModalSaveForm id="element-definition-form" className="grid section-stack" onSubmit={saveDefinition}>
              <ElementEditorSummary
                title={definitionForm.title}
                description={definitionForm.description}
                mode="edit"
              />
              <SettingsSection
                title={t("elementBasicsTitle")}
                description={t("elementBasicsDescription")}
              >
                <div className="two-col">
                  <label className="field-stack">
                    <span className="field-label">{t("elementTitleLabel")}</span>
                    <input value={definitionForm.title} onChange={(event) => setDefinitionForm((current) => ({ ...current, title: event.target.value }))} />
                    <span className="field-help">
                      Verfuegbare Zyklus-Platzhalter: {"{cycle_name}"}, {"{cycle_year_start}"}, {"{cycle_year_end}"} — werden beim Erstellen des Protokolls anhand des Zyklus der Vorlage ersetzt.
                    </span>
                  </label>
                </div>
              </SettingsSection>
            </ModalSaveForm>

            <SettingsSection
              title={`Blöcke in ${selectedDefinition.title}`}
              description={t("blocksSectionDescription")}
              actions={
                <button
                  type="button"
                  className="button-secondary"
                  onClick={() => {
                    setCreatingNewDefinition(false);
                    setShowCreateBlockModal(true);
                  }}
                >
                  Neuer Block
                </button>
              }
            >
              <DataTable columns={[t("colBlock"), t("colType"), t("colSubtitle"), t("colOrder"), t("colActions")]}>
              {selectedDefinition.blocks
                .slice()
                .sort((left, right) => left.sort_index - right.sort_index)
                .map((block) => (
                  <tr
                    key={block.id}
                    draggable
                    className={`${selectedBlockId === block.id ? "table-row-clickable table-row-active" : "table-row-clickable"}${draggedBlockId === block.id ? " table-row-dragging" : ""}`}
                    onClick={() => {
                      setSelectedBlockId(block.id);
                      setBlockForm(blockFormFromBlock(block));
                      setShowEditBlockModal(true);
                    }}
                    onDragStart={() => setDraggedBlockId(block.id)}
                    onDragEnd={() => setDraggedBlockId(null)}
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={(event) => {
                      event.preventDefault();
                      const sourceId = draggedBlockId;
                      setDraggedBlockId(null);
                      if (sourceId) {
                        void reorderBlocks(sourceId, block.id);
                      }
                    }}
                  >
                    <td>
                      <strong>{blockDisplayName(block, t)}</strong>
                    </td>
                    <td>{optionLabel(elementTypeOptions, block.element_type_id, t)}</td>
                    <td>{block.block_title?.trim() ? block.block_title : t("noSubtitle")}</td>
                    <td><span className="pill">{t("drag")}</span></td>
                    <td>
                      <div className="table-actions">
                        <button
                          type="button"
                          className="button-secondary button-ghost"
                          onClick={(event) => {
                            event.stopPropagation();
                            setSelectedBlockId(block.id);
                            setBlockForm(blockFormFromBlock(block));
                            setShowEditBlockModal(true);
                          }}
                        >
                          Bearbeiten
                        </button>
                        <button type="button" className="button-secondary button-danger" onClick={(event) => {
                          event.stopPropagation();
                          void deleteBlock(block.id);
                        }}>{t("delete")}</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </DataTable>
            </SettingsSection>
          </div>
      ) : null}
      </Modal>

      <Modal
        open={showCreateBlockModal && (!!selectedDefinition || creatingNewDefinition)}
        onClose={() => {
          setShowCreateBlockModal(false);
          setShowCreateBlockHelp(false);
          setMatrixDesignerMode(null);
          setCreatingNewDefinition(false);
          if (typePickerMode === "create") {
            setTypePickerMode(null);
          }
        }}
        title={creatingNewDefinition ? t("createElementTitle") : t("createBlockTitle")}
        className="element-create-modal"
        hideCloseButton
        description={
          creatingNewDefinition
            ? t("createElementDescription")
            : t("createBlockDescription")
        }
        size="wide"
        headerActions={
          <>
          <button type="button" className="button-ghost" onClick={() => setShowCreateBlockHelp((current) => !current)}>
            Hilfe
          </button>
          <button type="button" className="button-icon" aria-label={t("close")} title={t("close")} onClick={() => { setShowCreateBlockModal(false); setShowCreateBlockHelp(false); setCreatingNewDefinition(false); setMatrixDesignerMode(null); setTypePickerMode(null); }}><ActionIcon name="close" /></button>
          </>
        }
      >
        <ModalSaveForm className="grid element-create-form" onSubmit={creatingNewDefinition ? createDefinitionWithBlock : createBlock}>
          <div className="element-create-layout">
          <div className="element-create-fields">
          {showCreateBlockHelp ? (
            <div className="compact-info-pop">
              <strong>{t("blockHint")}</strong>
              <span className="muted">{t("blockHintCreateText")}</span>
            </div>
          ) : null}
          <BlockEditorSummary form={createBlockForm} mode="create" onChooseType={() => setTypePickerMode("create")} />
          {creatingNewDefinition ? (
            <SettingsSection
              title={t("elementSectionTitle")}
              description={t("elementSectionDescription")}
            >
              <div className="grid">
                <label className="field-stack">
                  <span className="field-label">{t("elementTitleLabel")}</span>
                  <input value={createDefinitionForm.title} onChange={(event) => setCreateDefinitionForm((current) => ({ ...current, title: event.target.value }))} placeholder={t("elementTitlePlaceholder")} required />
                  <span className="field-help" hidden={!showCreateBlockHelp}>
                    Verfuegbare Zyklus-Platzhalter: {"{cycle_name}"}, {"{cycle_year_start}"}, {"{cycle_year_end}"} — werden beim Erstellen des Protokolls anhand des Zyklus der Vorlage ersetzt.
                  </span>
                </label>
              </div>
            </SettingsSection>
          ) : null}
          <SettingsSection
            title={t("basicsTitle")}
            description={t("basicsDescription")}
          >
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">{t("blockNameLabel")}</span>
                <input value={createBlockForm.title} onChange={(event) => setCreateBlockForm((current) => ({ ...current, title: event.target.value }))} placeholder={t("blockNamePlaceholder")} />
                <span className="field-help">{t("blockNameHelpCreate")}</span>
              </label>
              <label className="field-stack">
                <span className="field-label">{t("subtitleLabel")}</span>
                <input value={createBlockForm.block_title} onChange={(event) => setCreateBlockForm((current) => ({ ...current, block_title: event.target.value }))} placeholder={t("subtitlePlaceholderCreate")} />
                <span className="field-help">{t("subtitleHelpCreate")}</span>
              </label>
            </div>
            {/* Plain div, not <label>: the field-stack label pattern relies on there being exactly
                one labelable descendant so a click focuses it. RichTextEditor renders its own
                toolbar buttons before the contenteditable area, and a <label> forwards clicks to
                the *first* labelable descendant - so wrapping it in <label> sent every click into
                the Bold button instead of the editor, making the field look rendered but dead. */}
            <div className="field-stack">
              <span className="field-label">{t("contentLabel")}</span>
              <RichTextEditor
                value={createBlockForm.default_content}
                onChange={(md) => setCreateBlockForm((current) => ({ ...current, default_content: md }))}
                placeholder={t("contentPlaceholder")}
              />
              <span className="field-help">{t("contentHelp")}</span>
              <span className="field-help">
                Verfuegbare Zyklus-Platzhalter: {"{cycle_name}"}, {"{cycle_year_start}"}, {"{cycle_year_end}"} — werden beim Erstellen des Protokolls anhand des Zyklus der Vorlage ersetzt.
              </span>
            </div>
          </SettingsSection>
          <SettingsSection
            title={t("repeatTitle")}
            description={t("repeatDescriptionCreate")}
          >
            <div className="rule-option-grid">
              {[
                { value: "none", title: "Einmalig", description: "Der Block erscheint genau einmal im Element." },
                { value: "event", title: "Pro Termin", description: "Der Block wird fuer jeden passenden Termin erneut erzeugt." },
                { value: "todo", title: "Pro Todo", description: "Der Block wird fuer jedes passende Todo erneut erzeugt." },
              ].map((option) => (
                <button
                  key={`create-repeat-${option.value}`}
                  type="button"
                  className={`rule-option-card${createBlockForm.repeat_source === option.value ? " rule-option-card-active" : ""}`}
                  onClick={() => setCreateBlockForm((current) => ({ ...current, repeat_source: option.value as "none" | "event" | "todo" }))}
                >
                  <strong>{option.title}</strong>
                  <span className="muted">{option.description}</span>
                </button>
              ))}
            </div>
            {createBlockForm.repeat_source === "event" ? (
              <>
                <div className="three-col">
                    <label className="field-stack">
                      <span className="field-label">{t("tagFilterLabel")}</span>
                      <TagInput
                        value={createBlockForm.event_tag_filter}
                        onChange={(v) => setCreateBlockForm((current) => ({ ...current, event_tag_filter: v }))}
                        suggestions={knownEventTags}
                  tagConfig={tagConfig}
                  onTagColorChange={updateTagColor}
                  onTagRename={renameTag}
                        placeholder={t("tagFilterPlaceholder")}
                      />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">{t("titleFilterLabel")}</span>
                    <input value={createBlockForm.event_title_filter} onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_title_filter: event.target.value }))} placeholder={t("containsPlaceholder")} />
                  </label>
                </div>
                <div className="field-stack">
                  <span className="field-label">{t("whichEventsLabel")}</span>
                  <FilterTabs
                    options={eventDateModeOptions(t)}
                    value={createBlockForm.event_date_mode}
                    onChange={(value) => setCreateBlockForm((current) => ({ ...current, event_date_mode: value }))}
                  />
                </div>
                {createBlockForm.event_date_mode === "relative_window" ? (
                  <div className="event-window-box">
                    <div className="event-window-row">
                      Termine von
                      <DayOffsetStepper
                        value={Math.max(0, -Number(createBlockForm.event_window_start_days || "0"))}
                        onChange={(days) => setCreateBlockForm((current) => ({ ...current, event_window_start_days: String(-days) }))}
                        ariaLabel={t("daysBeforeAriaLabel")}
                      />
                      Tagen <strong>{t("before")}</strong> bis
                      <DayOffsetStepper
                        value={Math.max(0, Number(createBlockForm.event_window_end_days || "0"))}
                        onChange={(days) => setCreateBlockForm((current) => ({ ...current, event_window_end_days: String(days) }))}
                        ariaLabel={t("daysAfterAriaLabel")}
                      />
                      Tagen <strong>{t("after")}</strong> dem Protokolldatum.
                    </div>
                    <span className="field-help">
                      Gezählt ab dem Datum des Protokolls — der Block entsteht für jeden Termin in diesem Fenster neu.
                    </span>
                  </div>
                ) : null}
                <label className="checkbox-row">
                  <input type="checkbox" checked={createBlockForm.event_include_unlisted_past} onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_include_unlisted_past: event.target.checked }))} />
                  Vergangene passende Termine nachziehen, wenn sie in den letzten 3 Protokollen unter diesem Element noch nicht gelistet wurden
                </label>
                <div className="info-note">
                  Verfuegbare Platzhalter: {"{title}"}, {"{description}"}, {"{event_date}"}, {"{tag}"} und {"{id}"}.
                </div>
              </>
            ) : null}
            {createBlockForm.repeat_source === "todo" ? (
              <>
                <div className="three-col">
                  <label className="field-stack">
                    <span className="field-label">{t("todoBlockTitleLabel")}</span>
                    <input value={createBlockForm.todo_block_title_filter} onChange={(event) => setCreateBlockForm((current) => ({ ...current, todo_block_title_filter: event.target.value }))} placeholder={t("containsPlaceholder")} />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">{t("todoTextLabel")}</span>
                    <input value={createBlockForm.todo_task_filter} onChange={(event) => setCreateBlockForm((current) => ({ ...current, todo_task_filter: event.target.value }))} placeholder={t("containsPlaceholder")} />
                  </label>
                  <label className="checkbox-row">
                    <input type="checkbox" checked={createBlockForm.todo_open_only} onChange={(event) => setCreateBlockForm((current) => ({ ...current, todo_open_only: event.target.checked }))} />
                    Nur offene Todos
                  </label>
                </div>
                <div className="info-note">
                  Verfuegbare Platzhalter: {"{title}"}, {"{task}"}, {"{description}"}, {"{due_date}"}, {"{participant}"} und {"{id}"}.
                </div>
              </>
            ) : null}
            {createBlockForm.element_type_id === "1" && createBlockForm.repeat_source !== "none" ? (
              <label className="field-stack">
                <span className="field-label">In {createBlockForm.repeat_source === "event" ? "Termin" : "Todo"}-Feld speichern (optional)</span>
                <select
                  value={createBlockForm.sync_target_field}
                  onChange={(event) => setCreateBlockForm((current) => ({ ...current, sync_target_field: event.target.value }))}
                >
                  <option value="">{t("doNotSave")}</option>
                  {(createBlockForm.repeat_source === "event" ? EVENT_SYNC_FIELDS : TODO_SYNC_FIELDS).map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
                <span className="field-help">
                  Der Blockinhalt wird beim Speichern zusätzlich in dieses Feld des verknüpften {createBlockForm.repeat_source === "event" ? "Termins" : "Todos"} geschrieben (immer überschrieben).
                  {createBlockForm.repeat_source === "event" ? " Beim Word-Import wird das Feld ebenfalls berücksichtigt: ist es leer, wird es befüllt; enthält es bereits einen abweichenden Wert, entscheidet die Reviewerin/der Reviewer im Import-Assistenten." : ""}
                </span>
              </label>
            ) : null}
          </SettingsSection>
          {createBlockForm.element_type_id === "1" ? (
            <SettingsSection
              title={t("textSectionTitle")}
              description={t("textSectionDescription")}
            >
              <div className="element-create-options">
                <label className="element-create-option">
                  <input type="checkbox" checked={createBlockForm.copy_from_last_protocol} onChange={(event) => setCreateBlockForm((current) => ({ ...current, copy_from_last_protocol: event.target.checked }))} />
                  <span><strong>{t("copyFromLastLabel")}</strong><span className="field-help">{t("copyFromLastHelp")}</span></span>
                </label>
                <label className="element-create-option">
                  <input type="checkbox" checked={createBlockForm.title_as_subtitle} onChange={(event) => setCreateBlockForm((current) => ({ ...current, title_as_subtitle: event.target.checked }))} />
                  <span><strong>{t("titleAsSubtitleLabel")}</strong><span className="field-help">{t("titleAsSubtitleHelp")}</span></span>
                </label>
              </div>
              <p className="muted">{t("textFixedHelp")}</p>
            </SettingsSection>
          ) : null}
          {createBlockForm.element_type_id === "2" ? (
            <SettingsSection
              title={t("todoSettingsTitle")}
              description={t("todoSettingsDescription")}
            >
              <div className="three-col">
                <label className="field-stack">
                  <span className="field-label">{t("dueTagFilterLabel")}</span>
                  <TagInput
                    value={createBlockForm.todo_due_tag_filter}
                    onChange={(v) => setCreateBlockForm((current) => ({ ...current, todo_due_tag_filter: v }))}
                    suggestions={knownEventTags}
                    tagConfig={tagConfig}
                    onTagColorChange={updateTagColor}
                    onTagRename={renameTag}
                    placeholder={t("allEventsNoFilter")}
                  />
                </label>
              </div>
            </SettingsSection>
          ) : null}
          {createBlockForm.element_type_id === "3" ? (
            <SettingsSection
              title={t("imageSectionTitle")}
              description={t("imageSectionDescription")}
            >
              <p className="info-note">{t("imageSectionNote")}</p>
            </SettingsSection>
          ) : null}
          {createBlockForm.element_type_id === "9" ? (
            <SettingsSection
              title={t("attendanceSectionTitle")}
              description={t("attendanceSectionDescription")}
            >
              <div className="three-col">
                <label className="field-stack">
                  <span className="field-label">{t("fineAccountLabel")}</span>
                  <SearchableSelect
                    options={availableAccounts}
                    getId={(a) => a.id}
                    getLabel={(a) => `${a.name} (${a.currency_label})`}
                    value={createBlockForm.fine_account_id || null}
                    onChange={(a) => setCreateBlockForm((c) => ({ ...c, fine_account_id: a ? String(a.id) : "" }))}
                    nullLabel={t("noFineAccount")}
                  />
                </label>
                {createBlockForm.fine_account_id ? (
                  <>
                    <label className="field-stack">
                      <span className="field-label">{t("fineLateLabel")}</span>
                      <input type="number" min="0" step="0.50" value={createBlockForm.fine_amount_late} placeholder="z. B. 5.00" onChange={(e) => setCreateBlockForm((c) => ({ ...c, fine_amount_late: e.target.value }))} />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">{t("fineAbsentLabel")}</span>
                      <input type="number" min="0" step="0.50" value={createBlockForm.fine_amount_absent} placeholder="z. B. 10.00" onChange={(e) => setCreateBlockForm((c) => ({ ...c, fine_amount_absent: e.target.value }))} />
                    </label>
                  </>
                ) : null}
              </div>
            </SettingsSection>
          ) : null}
          {createBlockForm.element_type_id === "10" ? (
            <SettingsSection
              title={t("sessionDateTitle")}
              description={t("sessionDateDescription")}
            >
              <label className="field-stack">
                <span className="field-label">{t("sessionDateTagFilterLabel")}</span>
                <TagInput
                  value={createBlockForm.event_tag_filter}
                  onChange={(v) => setCreateBlockForm((current) => ({ ...current, event_tag_filter: v }))}
                  suggestions={knownEventTags}
                  tagConfig={tagConfig}
                  onTagColorChange={updateTagColor}
                  onTagRename={renameTag}
                  placeholder={t("eventTagFilterPlaceholder")}
                />
              </label>
              <p className="info-note">{t("sessionDateNote")}</p>
            </SettingsSection>
          ) : null}
          {(createBlockForm.element_type_id === "12" || createBlockForm.element_type_id === "13") ? (
            <SettingsSection
              title={createBlockForm.element_type_id === "12" ? t("balanceTitle") : t("transactionsTitle")}
              description={t("financeSectionDescription")}
            >
              <div className="three-col">
                <label className="field-stack">
                  <span className="field-label">{t("accountLabel")}</span>
                  <SearchableSelect
                    options={availableAccounts}
                    getId={(a) => a.id}
                    getLabel={(a) => `${a.name} (${a.currency_label})`}
                    value={createBlockForm.finance_account_id || null}
                    onChange={(a) => setCreateBlockForm((c) => ({ ...c, finance_account_id: a ? String(a.id) : "" }))}
                    nullLabel={t("noAccount")}
                  />
                </label>
                {createBlockForm.element_type_id === "13" ? (
                  <>
                    <label className="field-stack">
                      <span className="field-label">{t("transactionsShowLabel")}</span>
                      <select
                        value={createBlockForm.finance_filter_type}
                        onChange={(e) => setCreateBlockForm((c) => ({ ...c, finance_filter_type: e.target.value as BlockFormState["finance_filter_type"] }))}
                      >
                        <option value="all">{t("filterAll")}</option>
                        <option value="since_last_session">{t("filterSinceLastSession")}</option>
                        <option value="this_year">{t("filterThisYear")}</option>
                        <option value="last_n">{t("filterLastN")}</option>
                      </select>
                    </label>
                    {createBlockForm.finance_filter_type === "last_n" && (
                      <label className="field-stack">
                        <span className="field-label">{t("countLabel")}</span>
                        <input type="number" min="1" value={createBlockForm.finance_last_n} onChange={(e) => setCreateBlockForm((c) => ({ ...c, finance_last_n: e.target.value }))} />
                      </label>
                    )}
                    {createBlockForm.finance_filter_type === "since_last_session" && (
                      <label className="field-stack">
                        <span className="field-label">{t("sinceDateLabel")}</span>
                        <DateInput value={createBlockForm.finance_since_date} onChange={(value) => setCreateBlockForm((c) => ({ ...c, finance_since_date: value }))} />
                      </label>
                    )}
                  </>
                ) : null}
              </div>
            </SettingsSection>
          ) : null}
          {createBlockForm.element_type_id === "14" ? (
            <SettingsSection
              title={t("finesListTitle")}
              description={t("finesListDescription")}
            >
              <p className="info-note">{t("finesListNote")}</p>
            </SettingsSection>
          ) : null}
          {createBlockForm.element_type_id === "7" ? (
            <SettingsSection
              title={t("eventListTitle")}
              description={t("eventListDescriptionCreate")}
            >
              <label className="field-stack">
                <span className="field-label">{t("eventTagFilterLabel")}</span>
                <TagInput
                  value={createBlockForm.event_tag_filter}
                  onChange={(v) => setCreateBlockForm((current) => ({ ...current, event_tag_filter: v }))}
                  suggestions={knownEventTags}
                  tagConfig={tagConfig}
                  onTagColorChange={updateTagColor}
                  onTagRename={renameTag}
                  placeholder={t("eventTagFilterPlaceholder")}
                />
              </label>
              <div className="field-stack">
                <span className="field-label">{t("visibilityFilterLabel")}</span>
                <div className="element-create-options">
                  <label className="element-create-option">
                    <input type="checkbox" checked={createBlockForm.event_only_from_protocol_date} onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_only_from_protocol_date: event.target.checked, event_only_before_protocol_date: false }))} />
                    <span><strong>{t("onlyFromProtocolDateLabel")}</strong></span>
                  </label>
                  <label className="element-create-option">
                    <input type="checkbox" checked={createBlockForm.event_only_before_protocol_date} onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_only_before_protocol_date: event.target.checked, event_only_from_protocol_date: false }))} />
                    <span><strong>{t("onlyBeforeProtocolDateLabel")}</strong></span>
                  </label>
                  <label className="element-create-option">
                    <input type="checkbox" checked={createBlockForm.event_only_current_cycle} onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_only_current_cycle: event.target.checked }))} />
                    <span><strong>{t("onlyCurrentCycleLabel")}</strong></span>
                  </label>
                  <label className="element-create-option">
                    <input type="checkbox" checked={createBlockForm.event_gray_past} onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_gray_past: event.target.checked }))} />
                    <span><strong>{t("grayPastLabel")}</strong></span>
                  </label>
                  <label className="element-create-option">
                    <input type="checkbox" checked={createBlockForm.event_allow_end_date} onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_allow_end_date: event.target.checked }))} />
                    <span><strong>{t("allowMultiDayLabel")}</strong></span>
                  </label>
                </div>
              </div>
              <div className="field-stack">
                <span className="field-label">{t("tableColumnsLabel")}</span>
                <span className="field-help">{t("tableColumnsHelp")}</span>
                <div className="table-pill-wrap">
                  {[
                    { key: "event_show_date" as const, label: t("fieldDate") },
                    { key: "event_show_tag" as const, label: t("fieldTag") },
                    { key: "event_show_title" as const, label: t("fieldTitle") },
                    { key: "event_show_description" as const, label: t("fieldDescription") },
                    { key: "event_show_participant_count" as const, label: t("fieldParticipantCount") },
                    { key: "event_show_cancelled" as const, label: t("fieldCancelled") },
                    { key: "event_show_tag_colors" as const, label: t("fieldTagColors") },
                  ].map((column) => (
                    <button
                      key={column.key}
                      type="button"
                      className={`button-pill${createBlockForm[column.key] ? " button-pill-active" : ""}`}
                      onClick={() => setCreateBlockForm((current) => ({ ...current, [column.key]: !current[column.key] }))}
                    >
                      {createBlockForm[column.key] ? "✓" : "+"} {column.label}
                    </button>
                  ))}
                </div>
              </div>
            </SettingsSection>
          ) : null}
          {createBlockForm.element_type_id === "6" ? (
            <SettingsSection
              title={t("tableSectionTitleCreate")}
              description={
                createBlockForm.linked_list_id
                  ? t("tableLinkedDescription")
                  : t("tableUnlinkedDescriptionCreate")
              }
              actions={
                createBlockForm.linked_list_id ? null : (
                  <button type="button" className="button-secondary" onClick={() => openTableDesigner("create")}>
                    Tabelle konfigurieren
                  </button>
                )
              }
            >
              <label className="field-stack">
                <span className="field-label">{t("linkedListLabel")}</span>
                <SearchableSelect
                  options={listOptions}
                  getId={(listDefinition) => listDefinition.id}
                  getLabel={(listDefinition) => listDefinition.name}
                  value={createBlockForm.linked_list_id || null}
                  onChange={(listDefinition) =>
                    setCreateBlockForm((current) => ({
                      ...current,
                      linked_list_id: listDefinition ? String(listDefinition.id) : "",
                      linked_list_group_by: listDefinition ? current.linked_list_group_by : "",
                      linked_list_sort_by: listDefinition ? current.linked_list_sort_by : "",
                      linked_list_sort_direction: listDefinition ? current.linked_list_sort_direction : "asc",
                    }))
                  }
                  nullLabel={t("noGlobalList")}
                />
                <span className="field-help">
                  Wenn eine Liste gewaehlt ist, zeigt der Tabellenblock spaeter genau diese globale Liste im Protokoll an.
                </span>
              </label>
              {createLinkedList ? (
                <div className="card grid">
                  <div className="eyebrow">{t("linkedListLabel")}</div>
                  <strong>{createLinkedList.name}</strong>
                  <div className="status-row">
                    <span className="pill">
                      {createLinkedList.column_one_title} · {valueTypeLabel(createLinkedList.column_one_value_type, t)}
                    </span>
                    <span className="pill">
                      {createLinkedList.column_two_title} · {valueTypeLabel(createLinkedList.column_two_value_type, t)}
                    </span>
                  </div>
                  <p className="muted">
                    Inhalt und Zeilen dieser Tabelle kommen aus `Datensaetze &gt; Listen`. Die lokale Tabellenkonfiguration wird in diesem Fall ignoriert.
                  </p>
                  <div className="three-col">
                    <label className="field-stack">
                      <span className="field-label">{t("groupByLabel")}</span>
                      <SearchableSelect
                        options={linkedListColumnOptions(createLinkedList)}
                        getId={(option) => option.value}
                        getLabel={(option) => option.label}
                        value={createBlockForm.linked_list_group_by || null}
                        onChange={(option) =>
                          setCreateBlockForm((current) => ({
                            ...current,
                            linked_list_group_by: (option?.value ?? "") as BlockFormState["linked_list_group_by"],
                          }))
                        }
                        nullLabel={t("noGrouping")}
                      />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">{t("sortAlphaLabel")}</span>
                      <SearchableSelect
                        options={linkedListColumnOptions(createLinkedList)}
                        getId={(option) => option.value}
                        getLabel={(option) => option.label}
                        value={createBlockForm.linked_list_sort_by || null}
                        onChange={(option) =>
                          setCreateBlockForm((current) => ({
                            ...current,
                            linked_list_sort_by: (option?.value ?? "") as BlockFormState["linked_list_sort_by"],
                            linked_list_sort_direction: option ? current.linked_list_sort_direction : "asc",
                          }))
                        }
                        nullLabel={t("manualListOrder")}
                      />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">{t("sortDirectionLabel")}</span>
                      <select
                        value={createBlockForm.linked_list_sort_direction}
                        disabled={!createBlockForm.linked_list_sort_by}
                        onChange={(event) =>
                          setCreateBlockForm((current) => ({
                            ...current,
                            linked_list_sort_direction: event.target.value as BlockFormState["linked_list_sort_direction"],
                          }))
                        }
                      >
                        <option value="asc">A-Z</option>
                        <option value="desc">Z-A</option>
                      </select>
                    </label>
                  </div>
                  <p className="muted">
                    Diese Anzeigeoptionen gelten nur fuer diesen Tabellenblock und werden auch im PDF-Export beruecksichtigt.
                  </p>
                </div>
              ) : (
                <>
                {createBlockForm.repeat_source === "event" && !createBlockForm.linked_list_id && (
                  <EventFieldSelector fields={createBlockForm.event_fields} onChange={(event_fields) => setCreateBlockForm((current) => ({ ...current, event_fields }))} />
                )}
                <div className="two-col">
                  <label className="field-stack">
                    <span className="field-label">{t("leftColumnHeadingLabel")}</span>
                    <input value={createBlockForm.left_column_heading} onChange={(event) => setCreateBlockForm((current) => ({ ...current, left_column_heading: event.target.value }))} placeholder={t("leftColumnHeadingPlaceholder")} />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">{t("valueColumnHeadingLabel")}</span>
                    <input value={createBlockForm.value_column_heading} onChange={(event) => setCreateBlockForm((current) => ({ ...current, value_column_heading: event.target.value }))} placeholder={t("valueColumnHeadingPlaceholder")} />
                  </label>
                </div>
                {createBlockForm.table_fields.length || selectedEventFields(createBlockForm).length ? (
                  <DataTable columns={[createBlockForm.left_column_heading || t("rowWord"), createBlockForm.value_column_heading || t("valueWord")]}>
                    {eventFieldPreviewRows(createBlockForm, t)}
                    {createBlockForm.table_fields.map((field, index) => (
                      <tr
                        key={`create-table-row-preview-${field.id}`}
                        className="table-row-clickable"
                        onClick={() => openTableDesigner("create", field.id)}
                      >
                        <td>
                          <strong>{field.label || `Zeile ${index + 1}`}</strong>
                          <div className="muted">{valueTypeLabel(field.row_type as Parameters<typeof valueTypeLabel>[0], t)}</div>
                        </td>
                        <td>
                          {tableRowPreviewValue(field)}
                          {field.locked_in_protocol ? <span className="pill">{t("lockedPill")}</span> : null}
                        </td>
                      </tr>
                    ))}
                  </DataTable>
                ) : (
                  <p className="muted">{t("noRowsYet")}</p>
                )}
                </>
              )}
            </SettingsSection>
          ) : null}
          {createBlockForm.element_type_id === "11" ? (
            <SettingsSection
              title={t("matrixSectionTitle")}
              description={t("matrixSectionDescriptionCreate")}
              actions={
                <button type="button" className="button-secondary" onClick={() => openMatrixDesigner("create")}>
                  Matrix konfigurieren
                </button>
              }
            >
              <div className="status-row">
                <span className="pill">{createBlockForm.matrix_columns.length} Spalten</span>
                <span className="pill">{createBlockForm.table_fields.length} Zeilen</span>
                <span className="pill">{createBlockForm.matrix_mode === "auto" ? "Automatisch" : "Manuell"}</span>
              </div>
              {createBlockForm.matrix_columns.length || createBlockForm.table_fields.length ? (
                <div className="table-pill-wrap">
                  {createBlockForm.matrix_columns.map((column) => (
                    <span key={`create-matrix-column-pill-${column.id}`} className="pill">
                      {column.title || t("noColumnTitle")}
                    </span>
                  ))}
                  {createBlockForm.table_fields.map((field) => (
                    <span key={`create-matrix-row-pill-${field.id}`} className="pill">
                      {field.label || t("unnamedRow")} · {matrixEmbeddedBlockLabel(field.row_type, tTypes, t) !== t("valueType.value") ? matrixEmbeddedBlockLabel(field.row_type, tTypes, t) : valueTypeLabel(field.row_type as Parameters<typeof valueTypeLabel>[0], t)}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="muted">{t("noMatrixYet")}</p>
              )}
            </SettingsSection>
          ) : null}
          {createBlockForm.element_type_id === "15" ? (
            <SettingsSection
              title={t("chartSectionTitle")}
              description={t("chartSectionDescription")}
            >
              <div className="three-col">
                <label className="field-stack">
                  <span className="field-label">{t("chartTypeLabel")}</span>
                  <select
                    value={createBlockForm.chart_type}
                    onChange={(e) => setCreateBlockForm((c) => ({ ...c, chart_type: e.target.value }))}
                  >
                    <option value="">{t("chartTypeChoose")}</option>
                    <option value="attendance_over_time">{t("chartAttendanceOverTime")}</option>
                    <option value="attendance_by_participant">{t("chartAttendanceByParticipant")}</option>
                    <option value="finance_by_month">{t("chartFinanceByMonth")}</option>
                    <option value="fines_by_participant">{t("chartFinesByParticipant")}</option>
                    <option value="fines_by_type">{t("chartFinesByType")}</option>
                    <option value="groups_sessions">{t("chartGroupsSessions")}</option>
                    <option value="groups_avg">{t("chartGroupsAvg")}</option>
                    <option value="todos">{t("chartTodos")}</option>
                  </select>
                </label>
              </div>
              <ChartCycleSelection
                config={{ cycle_config_id: createBlockForm.chart_cycle_config_id, cycle_offset: createBlockForm.chart_cycle_offset }}
                onChange={(config) => setCreateBlockForm((c) => ({ ...c, chart_cycle_config_id: config.cycle_config_id ?? "", chart_cycle_offset: config.cycle_offset ?? 0, chart_cycle_key: "all" }))}
              />
            </SettingsSection>
          ) : null}
          {createBlockForm.element_type_id === "16" ? (
            <SettingsSection
              title={t("entryExitSectionTitle")}
              description={t("entryExitSectionDescription")}
            >
              <div className="three-col">
                <label className="field-stack">
                  <span className="field-label">{t("entryExitFirstUseLabel")}</span>
                  <select
                    value={createBlockForm.entry_exit_first_use_mode}
                    onChange={(e) => setCreateBlockForm((c) => ({ ...c, entry_exit_first_use_mode: e.target.value as BlockFormState["entry_exit_first_use_mode"] }))}
                  >
                    <option value="all">{t("entryExitAll")}</option>
                    <option value="since_date">{t("entryExitSinceDate")}</option>
                  </select>
                </label>
                {createBlockForm.entry_exit_first_use_mode === "since_date" && (
                  <label className="field-stack">
                    <span className="field-label">{t("startDateLabel")}</span>
                    <DateInput value={createBlockForm.entry_exit_first_use_date} onChange={(value) => setCreateBlockForm((c) => ({ ...c, entry_exit_first_use_date: value }))} />
                  </label>
                )}
              </div>
            </SettingsSection>
          ) : null}
          {createBlockForm.element_type_id === "17" ? (
            <p className="info-note">{t("sessionNotesBlockNote")}</p>
          ) : null}
          </div>
          <aside className="element-create-sidebar">
            <section className="element-create-preview">
              <h3>{t("previewHeading")}</h3>
              <div className="element-create-paper">
                <h4>{(creatingNewDefinition ? createDefinitionForm.title : selectedDefinition?.title)?.trim() || t("newElement")}</h4>
                <p className="muted">
                  {createBlockForm.repeat_source === "none"
                    ? t("previewTypeOnce", { label: optionLabel(elementTypeOptions, createBlockForm.element_type_id, t) })
                    : `${repeatSourceLabel(createBlockForm.repeat_source, t)}${createBlockForm.event_tag_filter ? t("previewTagSuffix", { tag: createBlockForm.event_tag_filter }) : ""}`}
                </p>
                {createBlockForm.title ? <strong>{createBlockForm.title}</strong> : null}
                {createBlockForm.block_title ? <p>{createBlockForm.block_title}</p> : null}
                {createBlockForm.element_type_id === "6" ? (
                  <DataTable columns={[{ key: "label", label: "Zeile" }, { key: "value", label: "Wert" }]} emptyMessage={t("noRowsYetShort")}>
                    {eventFieldPreviewRows(createBlockForm, t)}
                    {createBlockForm.table_fields.map((field, index) => (
                      <tr key={field.id}>
                        <td>{field.label || `Zeile ${index + 1}`}</td>
                        <td>
                          {tableRowPreviewValue(field)}
                          {field.locked_in_protocol ? <span className="pill">{t("lockedPill")}</span> : null}
                        </td>
                      </tr>
                    ))}
                  </DataTable>
                ) : createBlockForm.default_content ? (
                  <p className="element-create-content-preview">{createBlockForm.default_content}</p>
                ) : renderBlockTypePreview(createBlockForm.element_type_id)}
                <p className="element-create-preview-meta">element_type_id {createBlockForm.element_type_id} · {createBlockForm.is_editable ? "editierbar" : "fixiert"}</p>
              </div>
            </section>
            <section className="element-create-behavior">
              <h3>{t("behaviorHeading")}</h3>
              <div className="element-create-options">
                <label className="element-create-option">
                  <input type="checkbox" checked={createBlockForm.is_editable} onChange={(event) => setCreateBlockForm((current) => ({ ...current, is_editable: event.target.checked }))} />
                  <span><strong>{t("editableInProtocolLabel")}</strong><span className="field-help">{t("editableInProtocolHelp")}</span></span>
                </label>
                <label className="element-create-option">
                  <input type="checkbox" checked={createBlockForm.export_visible} onChange={(event) => setCreateBlockForm((current) => ({ ...current, export_visible: event.target.checked }))} />
                  <span><strong>{t("exportVisibleLabel")}</strong><span className="field-help">{t("exportVisibleHelp")}</span></span>
                </label>
              </div>
            </section>
            <section className="element-create-cycle-hints">
              <h3>{t("cycleTokensHeading")}</h3>
              <div className="element-create-cycle-tokens">
                <code>{"{cycle_name}"}</code>
                <code>{"{cycle_year_start}"}</code>
                <code>{"{cycle_year_end}"}</code>
              </div>
              <p className="muted">{t("cycleTokensHelp")}</p>
            </section>
          </aside>
          </div>
          <div className="modal-actions element-create-footer">
            <p className="muted">{t("createFooterNote")}</p>
            <button type="button" className="button-secondary" onClick={() => { setShowCreateBlockModal(false); setShowCreateBlockHelp(false); setCreatingNewDefinition(false); setMatrixDesignerMode(null); setTypePickerMode(null); }}>{t("cancel")}</button>
            <button data-modal-save type="submit" className="button-primary" disabled={creatingNewDefinition && !createDefinitionForm.title.trim()}>{creatingNewDefinition ? t("createElementTitle") : t("createBlockTitle")}</button>
          </div>
        </ModalSaveForm>
      </Modal>

      <Modal
        open={showEditBlockModal && !!selectedBlock}
        className="element-edit-modal"
        onClose={() => {
          setShowEditBlockModal(false);
          setShowEditBlockHelp(false);
          setMatrixDesignerMode(null);
          if (typePickerMode === "edit") {
            setTypePickerMode(null);
          }
        }}
        title={selectedBlock ? t("editBlockNamed", { name: blockDisplayName(selectedBlock, t) }) : t("editBlockTitle")}
        description={t("editBlockModalDescription")}
        size="wide"
        headerActions={
          <button type="button" className="button-ghost" onClick={() => setShowEditBlockHelp((current) => !current)}>
            Hilfe
          </button>
        }
      >
        {selectedBlock ? (
          <ModalSaveForm className="grid section-stack block-editor-form" onSubmit={updateBlock}>
            {showEditBlockHelp ? (
              <div className="compact-info-pop">
                <strong>{t("blockHint")}</strong>
                <span className="muted">{t("blockHintEditText")}</span>
              </div>
            ) : null}
            <BlockEditorSummary form={blockForm} mode="edit" onChooseType={() => setTypePickerMode("edit")} />
            <SettingsSection
              title={t("basicsTitle")}
              description={t("basicsDescriptionEdit")}
            >
              <div className="two-col">
                <label className="field-stack">
                  <span className="field-label">{t("blockNameLabel")}</span>
                  <input value={blockForm.title} onChange={(event) => setBlockForm((current) => ({ ...current, title: event.target.value }))} placeholder={t("blockNamePlaceholder")} />
                  <span className="field-help">{t("blockNameHelpEdit")}</span>
                </label>
                <label className="field-stack">
                  <span className="field-label">{t("subtitleLabel")}</span>
                  <input value={blockForm.block_title} onChange={(event) => setBlockForm((current) => ({ ...current, block_title: event.target.value }))} placeholder={t("subtitlePlaceholderEdit")} />
                </label>
              </div>
              {/* Plain div, not <label> - see the create-form field above for why. */}
              <div className="field-stack">
                <span className="field-label">{t("contentLabel")}</span>
                <RichTextEditor
                  value={blockForm.default_content}
                  onChange={(md) => setBlockForm((current) => ({ ...current, default_content: md }))}
                />
                <span className="field-help">
                  Verfuegbare Zyklus-Platzhalter: {"{cycle_name}"}, {"{cycle_year_start}"}, {"{cycle_year_end}"} — werden beim Erstellen des Protokolls anhand des Zyklus der Vorlage ersetzt.
                </span>
              </div>
            </SettingsSection>
            <SettingsSection
              title={t("repeatTitle")}
              description={t("repeatDescriptionEdit")}
            >
              <div className="rule-option-grid">
                {[
                  { value: "none", title: "Einmalig", description: "Der Block erscheint genau einmal im Element." },
                  { value: "event", title: "Pro Termin", description: "Der Block wird fuer jeden passenden Termin erneut erzeugt." },
                  { value: "todo", title: "Pro Todo", description: "Der Block wird fuer jedes passende Todo erneut erzeugt." },
                ].map((option) => (
                  <button
                    key={`edit-repeat-${option.value}`}
                    type="button"
                    className={`rule-option-card${blockForm.repeat_source === option.value ? " rule-option-card-active" : ""}`}
                    onClick={() => setBlockForm((current) => ({ ...current, repeat_source: option.value as "none" | "event" | "todo" }))}
                  >
                    <strong>{option.title}</strong>
                    <span className="muted">{option.description}</span>
                  </button>
                ))}
              </div>
              {blockForm.repeat_source === "event" ? (
                <>
                  <div className="three-col">
                    <label className="field-stack">
                      <span className="field-label">{t("tagFilterLabel")}</span>
                      <TagInput
                        value={blockForm.event_tag_filter}
                        onChange={(v) => setBlockForm((current) => ({ ...current, event_tag_filter: v }))}
                        suggestions={knownEventTags}
                  tagConfig={tagConfig}
                  onTagColorChange={updateTagColor}
                  onTagRename={renameTag}
                        placeholder={t("tagFilterPlaceholder")}
                      />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">{t("titleFilterLabel")}</span>
                      <input value={blockForm.event_title_filter} onChange={(event) => setBlockForm((current) => ({ ...current, event_title_filter: event.target.value }))} placeholder={t("containsPlaceholder")} />
                    </label>
                  </div>
                  <div className="field-stack">
                    <span className="field-label">{t("whichEventsLabel")}</span>
                    <FilterTabs
                      options={eventDateModeOptions(t)}
                      value={blockForm.event_date_mode}
                      onChange={(value) => setBlockForm((current) => ({ ...current, event_date_mode: value }))}
                    />
                  </div>
                  {blockForm.event_date_mode === "relative_window" ? (
                    <div className="event-window-box">
                      <div className="event-window-row">
                        Termine von
                        <DayOffsetStepper
                          value={Math.max(0, -Number(blockForm.event_window_start_days || "0"))}
                          onChange={(days) => setBlockForm((current) => ({ ...current, event_window_start_days: String(-days) }))}
                          ariaLabel={t("daysBeforeAriaLabel")}
                        />
                        Tagen <strong>{t("before")}</strong> bis
                        <DayOffsetStepper
                          value={Math.max(0, Number(blockForm.event_window_end_days || "0"))}
                          onChange={(days) => setBlockForm((current) => ({ ...current, event_window_end_days: String(days) }))}
                          ariaLabel={t("daysAfterAriaLabel")}
                        />
                        Tagen <strong>{t("after")}</strong> dem Protokolldatum.
                      </div>
                      <span className="field-help">
                        Gezählt ab dem Datum des Protokolls — der Block entsteht für jeden Termin in diesem Fenster neu.
                      </span>
                    </div>
                  ) : null}
                  <label className="checkbox-row">
                    <input type="checkbox" checked={blockForm.event_include_unlisted_past} onChange={(event) => setBlockForm((current) => ({ ...current, event_include_unlisted_past: event.target.checked }))} />
                    Vergangene passende Termine nachziehen, wenn sie in den letzten 3 Protokollen unter diesem Element noch nicht gelistet wurden
                  </label>
                  <div className="info-note">
                    Verfuegbare Platzhalter: {"{title}"}, {"{description}"}, {"{event_date}"}, {"{tag}"} und {"{id}"}.
                  </div>
                </>
              ) : null}
              {blockForm.repeat_source === "todo" ? (
                <>
                  <div className="three-col">
                    <label className="field-stack">
                      <span className="field-label">{t("todoBlockTitleLabel")}</span>
                      <input value={blockForm.todo_block_title_filter} onChange={(event) => setBlockForm((current) => ({ ...current, todo_block_title_filter: event.target.value }))} placeholder={t("containsPlaceholder")} />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">{t("todoTextLabel")}</span>
                      <input value={blockForm.todo_task_filter} onChange={(event) => setBlockForm((current) => ({ ...current, todo_task_filter: event.target.value }))} placeholder={t("containsPlaceholder")} />
                    </label>
                    <label className="checkbox-row">
                      <input type="checkbox" checked={blockForm.todo_open_only} onChange={(event) => setBlockForm((current) => ({ ...current, todo_open_only: event.target.checked }))} />
                      Nur offene Todos
                    </label>
                  </div>
                <div className="info-note">
                  Verfuegbare Platzhalter: {"{title}"}, {"{task}"}, {"{description}"}, {"{due_date}"}, {"{participant}"} und {"{id}"}.
                </div>
              </>
            ) : null}
            {blockForm.element_type_id === "1" && blockForm.repeat_source !== "none" ? (
              <label className="field-stack">
                <span className="field-label">In {blockForm.repeat_source === "event" ? "Termin" : "Todo"}-Feld speichern (optional)</span>
                <select
                  value={blockForm.sync_target_field}
                  onChange={(event) => setBlockForm((current) => ({ ...current, sync_target_field: event.target.value }))}
                >
                  <option value="">{t("doNotSave")}</option>
                  {(blockForm.repeat_source === "event" ? EVENT_SYNC_FIELDS : TODO_SYNC_FIELDS).map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
                <span className="field-help">
                  Der Blockinhalt wird beim Speichern zusätzlich in dieses Feld des verknüpften {blockForm.repeat_source === "event" ? "Termins" : "Todos"} geschrieben (immer überschrieben).
                  {blockForm.repeat_source === "event" ? " Beim Word-Import wird das Feld ebenfalls berücksichtigt: ist es leer, wird es befüllt; enthält es bereits einen abweichenden Wert, entscheidet die Reviewerin/der Reviewer im Import-Assistenten." : ""}
                </span>
              </label>
            ) : null}
            </SettingsSection>
            {blockForm.element_type_id === "2" ? (
              <SettingsSection
                title={t("todoSettingsTitle")}
                description={t("todoSettingsDescription")}
              >
                <div className="three-col">
                  <label className="field-stack">
                    <span className="field-label">{t("dueTagFilterLabel")}</span>
                    <TagInput
                      value={blockForm.todo_due_tag_filter}
                      onChange={(v) => setBlockForm((current) => ({ ...current, todo_due_tag_filter: v }))}
                      suggestions={knownEventTags}
                      tagConfig={tagConfig}
                      onTagColorChange={updateTagColor}
                      onTagRename={renameTag}
                      placeholder={t("allEventsNoFilter")}
                    />
                  </label>
                </div>
              </SettingsSection>
            ) : null}
            {blockForm.element_type_id === "9" ? (
              <SettingsSection
                title={t("attendanceSectionTitle")}
                description={t("attendanceSectionDescription")}
              >
                <div className="three-col">
                  <label className="field-stack">
                    <span className="field-label">{t("fineAccountLabel")}</span>
                    <SearchableSelect
                      options={availableAccounts}
                      getId={(a) => a.id}
                      getLabel={(a) => `${a.name} (${a.currency_label})`}
                      value={blockForm.fine_account_id || null}
                      onChange={(a) => setBlockForm((c) => ({ ...c, fine_account_id: a ? String(a.id) : "" }))}
                      nullLabel={t("noFineAccount")}
                    />
                  </label>
                  {blockForm.fine_account_id ? (
                    <>
                      <label className="field-stack">
                        <span className="field-label">{t("fineLateLabel")}</span>
                        <input type="number" min="0" step="0.50" value={blockForm.fine_amount_late} placeholder="z. B. 5.00" onChange={(e) => setBlockForm((c) => ({ ...c, fine_amount_late: e.target.value }))} />
                      </label>
                      <label className="field-stack">
                        <span className="field-label">{t("fineAbsentLabel")}</span>
                        <input type="number" min="0" step="0.50" value={blockForm.fine_amount_absent} placeholder="z. B. 10.00" onChange={(e) => setBlockForm((c) => ({ ...c, fine_amount_absent: e.target.value }))} />
                      </label>
                    </>
                  ) : null}
                </div>
              </SettingsSection>
            ) : null}
            {blockForm.element_type_id === "10" ? (
              <SettingsSection
                title={t("sessionDateTitle")}
                description={t("sessionDateDescription")}
              >
                <label className="field-stack">
                  <span className="field-label">{t("sessionDateTagFilterLabel")}</span>
                  <TagInput
                    value={blockForm.event_tag_filter}
                    onChange={(v) => setBlockForm((current) => ({ ...current, event_tag_filter: v }))}
                    suggestions={knownEventTags}
                    tagConfig={tagConfig}
                    onTagColorChange={updateTagColor}
                    onTagRename={renameTag}
                    placeholder={t("eventTagFilterPlaceholder")}
                  />
                </label>
                <p className="info-note">{t("sessionDateNote")}</p>
              </SettingsSection>
            ) : null}
            {(blockForm.element_type_id === "12" || blockForm.element_type_id === "13") ? (
              <SettingsSection
                title={blockForm.element_type_id === "12" ? t("balanceTitle") : t("transactionsTitle")}
                description={t("financeSectionDescription")}
              >
                <div className="three-col">
                  <label className="field-stack">
                    <span className="field-label">{t("accountLabel")}</span>
                    <SearchableSelect
                      options={availableAccounts}
                      getId={(a) => a.id}
                      getLabel={(a) => `${a.name} (${a.currency_label})`}
                      value={blockForm.finance_account_id || null}
                      onChange={(a) => setBlockForm((c) => ({ ...c, finance_account_id: a ? String(a.id) : "" }))}
                      nullLabel={t("noAccount")}
                    />
                  </label>
                  {blockForm.element_type_id === "13" ? (
                    <>
                      <label className="field-stack">
                        <span className="field-label">{t("transactionsShowLabel")}</span>
                        <select
                          value={blockForm.finance_filter_type}
                          onChange={(e) => setBlockForm((c) => ({ ...c, finance_filter_type: e.target.value as BlockFormState["finance_filter_type"] }))}
                        >
                          <option value="all">{t("filterAll")}</option>
                          <option value="since_last_session">{t("filterSinceLastSession")}</option>
                          <option value="this_year">{t("filterThisYear")}</option>
                          <option value="last_n">{t("filterLastN")}</option>
                        </select>
                      </label>
                      {blockForm.finance_filter_type === "last_n" && (
                        <label className="field-stack">
                          <span className="field-label">{t("countLabel")}</span>
                          <input type="number" min="1" value={blockForm.finance_last_n} onChange={(e) => setBlockForm((c) => ({ ...c, finance_last_n: e.target.value }))} />
                        </label>
                      )}
                      {blockForm.finance_filter_type === "since_last_session" && (
                        <label className="field-stack">
                          <span className="field-label">{t("sinceDateLabel")}</span>
                          <DateInput value={blockForm.finance_since_date} onChange={(value) => setBlockForm((c) => ({ ...c, finance_since_date: value }))} />
                        </label>
                      )}
                    </>
                  ) : null}
                </div>
              </SettingsSection>
            ) : null}
            {blockForm.element_type_id === "7" ? (
              <SettingsSection
                title={t("eventListTitle")}
                description={t("eventListDescriptionEdit")}
              >
                <div className="three-col">
                <label className="field-stack">
                  <span className="field-label">{t("eventTagFilterLabel")}</span>
                  <TagInput
                    value={blockForm.event_tag_filter}
                    onChange={(v) => setBlockForm((current) => ({ ...current, event_tag_filter: v }))}
                    suggestions={knownEventTags}
                  tagConfig={tagConfig}
                  onTagColorChange={updateTagColor}
                  onTagRename={renameTag}
                    placeholder={t("eventTagFilterPlaceholder")}
                  />
                </label>
                <label className="checkbox-row"><input type="checkbox" checked={blockForm.event_only_from_protocol_date} onChange={(event) => setBlockForm((current) => ({ ...current, event_only_from_protocol_date: event.target.checked, event_only_before_protocol_date: false }))} />{t("onlyFromProtocolDateLabel")}</label>
                <label className="checkbox-row"><input type="checkbox" checked={blockForm.event_only_before_protocol_date} onChange={(event) => setBlockForm((current) => ({ ...current, event_only_before_protocol_date: event.target.checked, event_only_from_protocol_date: false }))} />{t("onlyBeforeProtocolDateLabel")}</label>
                <label className="checkbox-row"><input type="checkbox" checked={blockForm.event_only_current_cycle} onChange={(event) => setBlockForm((current) => ({ ...current, event_only_current_cycle: event.target.checked }))} />{t("onlyCurrentCycleLabel")}</label>
                <label className="checkbox-row"><input type="checkbox" checked={blockForm.event_gray_past} onChange={(event) => setBlockForm((current) => ({ ...current, event_gray_past: event.target.checked }))} />{t("grayPastLabel")}</label>
                <label className="checkbox-row"><input type="checkbox" checked={blockForm.event_allow_end_date} onChange={(event) => setBlockForm((current) => ({ ...current, event_allow_end_date: event.target.checked }))} />{t("allowMultiDayLabel")}</label>
                </div>
                <div className="three-col">
                  <label className="checkbox-row"><input type="checkbox" checked={blockForm.event_show_date} onChange={(event) => setBlockForm((current) => ({ ...current, event_show_date: event.target.checked }))} />{t("colDate")}</label>
                  <label className="checkbox-row"><input type="checkbox" checked={blockForm.event_show_tag} onChange={(event) => setBlockForm((current) => ({ ...current, event_show_tag: event.target.checked }))} />{t("colTag")}</label>
                  <label className="checkbox-row"><input type="checkbox" checked={blockForm.event_show_tag_colors} onChange={(event) => setBlockForm((current) => ({ ...current, event_show_tag_colors: event.target.checked }))} />{t("colTagColors")}</label>
                  <label className="checkbox-row"><input type="checkbox" checked={blockForm.event_show_title} onChange={(event) => setBlockForm((current) => ({ ...current, event_show_title: event.target.checked }))} />{t("colTitle")}</label>
                  <label className="checkbox-row"><input type="checkbox" checked={blockForm.event_show_description} onChange={(event) => setBlockForm((current) => ({ ...current, event_show_description: event.target.checked }))} />{t("colDescription")}</label>
                  <label className="checkbox-row"><input type="checkbox" checked={blockForm.event_show_participant_count} onChange={(event) => setBlockForm((current) => ({ ...current, event_show_participant_count: event.target.checked }))} />{t("colParticipantCount")}</label>
                  <label className="checkbox-row"><input type="checkbox" checked={blockForm.event_show_cancelled} onChange={(event) => setBlockForm((current) => ({ ...current, event_show_cancelled: event.target.checked }))} />{t("colCancelled")}</label>
                </div>
              </SettingsSection>
            ) : null}
            {blockForm.element_type_id === "6" ? (
              <SettingsSection
                title={t("tableSectionTitleEdit")}
                description={
                  blockForm.linked_list_id
                    ? t("tableLinkedDescription")
                    : t("tableUnlinkedDescriptionEdit")
                }
                actions={
                  blockForm.linked_list_id ? null : (
                    <button type="button" className="button-secondary" onClick={() => openTableDesigner("edit")}>
                      Tabelle konfigurieren
                    </button>
                  )
                }
              >
                <label className="field-stack">
                  <span className="field-label">{t("linkedListLabel")}</span>
                <SearchableSelect
                  options={listOptions}
                  getId={(listDefinition) => listDefinition.id}
                  getLabel={(listDefinition) => listDefinition.name}
                  value={blockForm.linked_list_id || null}
                  onChange={(listDefinition) =>
                    setBlockForm((current) => ({
                      ...current,
                      linked_list_id: listDefinition ? String(listDefinition.id) : "",
                      linked_list_group_by: listDefinition ? current.linked_list_group_by : "",
                      linked_list_sort_by: listDefinition ? current.linked_list_sort_by : "",
                      linked_list_sort_direction: listDefinition ? current.linked_list_sort_direction : "asc",
                    }))
                  }
                  nullLabel={t("noGlobalList")}
                />
                  <span className="field-help">
                    Wenn eine Liste gewaehlt ist, zeigt der Tabellenblock spaeter genau diese globale Liste im Protokoll an.
                  </span>
                </label>
                {editLinkedList ? (
                  <div className="card grid">
                    <div className="eyebrow">{t("linkedListLabel")}</div>
                    <strong>{editLinkedList.name}</strong>
                    <div className="status-row">
                      <span className="pill">
                        {editLinkedList.column_one_title} · {valueTypeLabel(editLinkedList.column_one_value_type, t)}
                      </span>
                      <span className="pill">
                        {editLinkedList.column_two_title} · {valueTypeLabel(editLinkedList.column_two_value_type, t)}
                      </span>
                    </div>
                    <p className="muted">
                      Inhalt und Zeilen dieser Tabelle kommen aus `Datensaetze &gt; Listen`. Die lokale Tabellenkonfiguration wird in diesem Fall ignoriert.
                    </p>
                    <div className="three-col">
                      <label className="field-stack">
                        <span className="field-label">{t("groupByLabel")}</span>
                        <SearchableSelect
                          options={linkedListColumnOptions(editLinkedList)}
                          getId={(option) => option.value}
                          getLabel={(option) => option.label}
                          value={blockForm.linked_list_group_by || null}
                          onChange={(option) =>
                            setBlockForm((current) => ({
                              ...current,
                              linked_list_group_by: (option?.value ?? "") as BlockFormState["linked_list_group_by"],
                            }))
                          }
                          nullLabel={t("noGrouping")}
                        />
                      </label>
                      <label className="field-stack">
                        <span className="field-label">{t("sortAlphaLabel")}</span>
                        <SearchableSelect
                          options={linkedListColumnOptions(editLinkedList)}
                          getId={(option) => option.value}
                          getLabel={(option) => option.label}
                          value={blockForm.linked_list_sort_by || null}
                          onChange={(option) =>
                            setBlockForm((current) => ({
                              ...current,
                              linked_list_sort_by: (option?.value ?? "") as BlockFormState["linked_list_sort_by"],
                              linked_list_sort_direction: option ? current.linked_list_sort_direction : "asc",
                            }))
                          }
                          nullLabel={t("manualListOrder")}
                        />
                      </label>
                      <label className="field-stack">
                        <span className="field-label">{t("sortDirectionLabel")}</span>
                        <select
                          value={blockForm.linked_list_sort_direction}
                          disabled={!blockForm.linked_list_sort_by}
                          onChange={(event) =>
                            setBlockForm((current) => ({
                              ...current,
                              linked_list_sort_direction: event.target.value as BlockFormState["linked_list_sort_direction"],
                            }))
                          }
                        >
                          <option value="asc">A-Z</option>
                          <option value="desc">Z-A</option>
                        </select>
                      </label>
                    </div>
                    <p className="muted">
                      Diese Anzeigeoptionen gelten nur fuer diesen Tabellenblock und werden auch im PDF-Export beruecksichtigt.
                    </p>
                  </div>
                ) : (
                  <>
                    {blockForm.repeat_source === "event" && !blockForm.linked_list_id && (
                      <EventFieldSelector fields={blockForm.event_fields} onChange={(event_fields) => setBlockForm((current) => ({ ...current, event_fields }))} />
                    )}
                    <div className="two-col">
                      <label className="field-stack">
                        <span className="field-label">{t("leftColumnHeadingLabelEdit")}</span>
                        <input
                          value={blockForm.left_column_heading}
                          onChange={(event) => setBlockForm((current) => ({ ...current, left_column_heading: event.target.value }))}
                          placeholder={t("noHeadingPlaceholder")}
                        />
                      </label>
                      <label className="field-stack">
                        <span className="field-label">{t("rightColumnHeadingLabelEdit")}</span>
                        <input
                          value={blockForm.value_column_heading}
                          onChange={(event) => setBlockForm((current) => ({ ...current, value_column_heading: event.target.value }))}
                          placeholder={t("noHeadingPlaceholder")}
                        />
                      </label>
                    </div>
                {blockForm.table_fields.length || selectedEventFields(blockForm).length ? (
                  <DataTable columns={[blockForm.left_column_heading || t("rowWord"), blockForm.value_column_heading || t("valueWord")]}>
                    {eventFieldPreviewRows(blockForm, t)}
                    {blockForm.table_fields.map((field, index) => (
                      <tr
                        key={`edit-table-row-preview-${field.id}`}
                        className="table-row-clickable"
                        onClick={() => openTableDesigner("edit", field.id)}
                      >
                        <td>
                          <strong>{field.label || `Zeile ${index + 1}`}</strong>
                          <div className="muted">{valueTypeLabel(field.row_type as Parameters<typeof valueTypeLabel>[0], t)}</div>
                        </td>
                        <td>{tableRowPreviewValue(field)}</td>
                      </tr>
                    ))}
                  </DataTable>
                ) : (
                  <p className="muted">{t("noRowsYet")}</p>
                )}
                  </>
                )}
              </SettingsSection>
            ) : null}
            {blockForm.element_type_id === "11" ? (
              <SettingsSection
                title={t("matrixSectionTitle")}
                description={t("matrixSectionDescriptionEdit")}
                actions={
                  <button type="button" className="button-secondary" onClick={() => openMatrixDesigner("edit")}>
                    Matrix konfigurieren
                  </button>
                }
              >
                <div className="status-row">
                  <span className="pill">{blockForm.matrix_columns.length} Spalten</span>
                  <span className="pill">{blockForm.table_fields.length} Zeilen</span>
                  <span className="pill">{blockForm.matrix_mode === "auto" ? "Automatisch" : "Manuell"}</span>
                </div>
                {blockForm.matrix_columns.length || blockForm.table_fields.length ? (
                  <div className="table-pill-wrap">
                    {blockForm.matrix_columns.map((column) => (
                      <span key={`edit-matrix-column-pill-${column.id}`} className="pill">
                        {column.title || t("noColumnTitle")}
                      </span>
                    ))}
                    {blockForm.table_fields.map((field) => (
                      <span key={`edit-matrix-row-pill-${field.id}`} className="pill">
                        {field.label || t("unnamedRow")} · {matrixEmbeddedBlockLabel(field.row_type, tTypes, t) !== t("valueType.value") ? matrixEmbeddedBlockLabel(field.row_type, tTypes, t) : valueTypeLabel(field.row_type as Parameters<typeof valueTypeLabel>[0], t)}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="muted">{t("noMatrixYet")}</p>
                )}
              </SettingsSection>
            ) : null}
            {blockForm.element_type_id === "15" ? (
              <SettingsSection
                title={t("chartSectionTitle")}
                description={t("chartSectionDescription")}
              >
                <div className="three-col">
                  <label className="field-stack">
                    <span className="field-label">{t("chartTypeLabel")}</span>
                    <select
                      value={blockForm.chart_type}
                      onChange={(e) => setBlockForm((c) => ({ ...c, chart_type: e.target.value }))}
                    >
                      <option value="">{t("chartTypeChoose")}</option>
                      <option value="attendance_over_time">{t("chartAttendanceOverTime")}</option>
                      <option value="attendance_by_participant">{t("chartAttendanceByParticipant")}</option>
                      <option value="finance_by_month">{t("chartFinanceByMonth")}</option>
                      <option value="fines_by_participant">{t("chartFinesByParticipant")}</option>
                      <option value="fines_by_type">{t("chartFinesByType")}</option>
                      <option value="groups_sessions">{t("chartGroupsSessions")}</option>
                      <option value="groups_avg">{t("chartGroupsAvg")}</option>
                      <option value="todos">{t("chartTodos")}</option>
                    </select>
                  </label>
                </div>
                <ChartCycleSelection
                  config={{ cycle_config_id: blockForm.chart_cycle_config_id, cycle_offset: blockForm.chart_cycle_offset }}
                  onChange={(config) => setBlockForm((c) => ({ ...c, chart_cycle_config_id: config.cycle_config_id ?? "", chart_cycle_offset: config.cycle_offset ?? 0, chart_cycle_key: "all" }))}
                />
              </SettingsSection>
            ) : null}
            {blockForm.element_type_id === "16" ? (
              <SettingsSection
                title={t("entryExitSectionTitle")}
                description={t("entryExitSectionDescription")}
              >
                <div className="three-col">
                  <label className="field-stack">
                    <span className="field-label">{t("entryExitFirstUseLabel")}</span>
                    <select
                      value={blockForm.entry_exit_first_use_mode}
                      onChange={(e) => setBlockForm((c) => ({ ...c, entry_exit_first_use_mode: e.target.value as BlockFormState["entry_exit_first_use_mode"] }))}
                    >
                      <option value="all">{t("entryExitAll")}</option>
                      <option value="since_date">{t("entryExitSinceDate")}</option>
                    </select>
                  </label>
                  {blockForm.entry_exit_first_use_mode === "since_date" && (
                    <label className="field-stack">
                      <span className="field-label">{t("startDateLabel")}</span>
                      <DateInput value={blockForm.entry_exit_first_use_date} onChange={(value) => setBlockForm((c) => ({ ...c, entry_exit_first_use_date: value }))} />
                    </label>
                  )}
                </div>
              </SettingsSection>
            ) : null}
            {blockForm.element_type_id === "17" ? (
              <p className="info-note">{t("sessionNotesBlockNote")}</p>
            ) : null}
            <div className="block-editor-footer">
              <button data-modal-save type="submit" className="button-secondary">{t("saveBlockButton")}</button>
            </div>
          </ModalSaveForm>
        ) : null}
      </Modal>

      <Modal
        open={typePickerMode !== null}
        onClose={() => setTypePickerMode(null)}
        title={t("typePickerTitle")}
        description={t("typePickerDescription")}
        size="fullscreen"
      >
        <div className="grid">
          <div className="block-type-category-stack">
            {elementTypeCategories.map((category, categoryIndex) => {
              const activeType = typePickerMode === "create" ? createBlockForm.element_type_id : blockForm.element_type_id;
              const isLast = categoryIndex === elementTypeCategories.length - 1;
              const categorizedTypes = new Set(elementTypeCategories.flatMap((entry) => entry.types));
              const options = [
                ...category.types
                  .map((typeId) => elementTypeOptions.find((option) => option.value === typeId))
                  .filter((option): option is (typeof elementTypeOptions)[number] => Boolean(option)),
                ...(isLast ? elementTypeOptions.filter((option) => !categorizedTypes.has(option.value)) : []),
              ];
              if (options.length === 0) return null;
              return (
                <section key={category.key} className="block-type-category">
                  <div className="block-type-category-head">
                    <h3>{t(`typeCategories.${category.key}.title`)}</h3>
                    <p className="muted">{t(`typeCategories.${category.key}.description`)}</p>
                  </div>
                  <div className="block-type-grid">
                    {options.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        className={`block-type-card${activeType === option.value ? " block-type-card-active" : ""}`}
                        onClick={() => applyBlockType(option.value, typePickerMode ?? "create")}
                      >
                        {renderBlockTypePreview(option.value)}
                        <div className="block-type-summary">
                          <div className="block-type-card-head">
                            <strong>{option.label}</strong>
                            <span className="block-type-card-number">#{option.value}</span>
                          </div>
                          <span className="muted">{option.description}</span>
                        </div>
                      </button>
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setTypePickerMode(null)}>{t("cancel")}</button>
          </div>
        </div>
      </Modal>

      <Modal
        open={matrixDesignerMode !== null && !!matrixDesignerForm}
        onEscape={saveMatrixDesigner}
        onClose={closeMatrixDesigner}
        title={t("matrixDesignerTitle")}
        description={t("matrixDesignerDescription")}
        size="fullscreen"
        headerActions={
          matrixDesignerMode === "edit" ? (
            <button type="button" className="button-secondary" onClick={() => { void saveMatrixDesigner(); }}>
              Übernehmen
            </button>
          ) : undefined
        }
      >
        {matrixDesignerForm ? (
          <div className="matrix-designer-layout">

            {/* ── Settings strip ── */}
            <div className="matrix-designer-strip">
              <div className="matrix-designer-strip-left">
                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={matrixDesignerForm.allow_column_management}
                    onChange={(e) => updateMatrixDesignerForm((c) => ({ ...c, allow_column_management: e.target.checked }))}
                  />
                  Spalten im Protokoll editierbar
                </label>
                <div className="matrix-designer-source-row">
                  <span className="field-label" style={{ whiteSpace: "nowrap" }}>{t("modeLabel")}</span>
                  <select
                    value={matrixDesignerForm.matrix_mode}
                    onChange={(e) => updateMatrixDesignerForm((c) => ({ ...c, matrix_mode: e.target.value as "manual" | "auto" }))}
                    style={{ minWidth: 100 }}
                  >
                    <option value="manual">{t("modeManual")}</option>
                    <option value="auto">{t("modeAuto")}</option>
                  </select>
                  {matrixDesignerForm.matrix_mode === "auto" ? (
                    <>
                      <span className="field-label" style={{ whiteSpace: "nowrap" }}>{t("sourceLabel")}</span>
                      <select
                        value={matrixDesignerForm.auto_source_type}
                        onChange={(e) => updateMatrixDesignerForm((c) => ({ ...c, auto_source_type: e.target.value as "" | "participants" | "events" | "list" }))}
                        style={{ minWidth: 130 }}
                      >
                        <option value="">{t("pleaseChoose")}</option>
                        <option value="participants">{t("sourceParticipants")}</option>
                        <option value="events">{t("sourceEvents")}</option>
                        <option value="list">{t("sourceList")}</option>
                      </select>
                      {matrixDesignerForm.auto_source_type === "events" ? (
                        <TagInput
                          value={matrixDesignerForm.auto_source_event_tag}
                          onChange={(v) => updateMatrixDesignerForm((c) => ({ ...c, auto_source_event_tag: v }))}
                          suggestions={knownEventTags}
                  tagConfig={tagConfig}
                  onTagColorChange={updateTagColor}
                  onTagRename={renameTag}
                          placeholder={t("tagFilterOptionalPlaceholder")}
                        />
                      ) : null}
                      {matrixDesignerForm.auto_source_type === "list" ? (
                        <span style={{ minWidth: 160, display: "inline-block" }}>
                          <SearchableSelect
                            options={listOptions}
                            getId={(list) => list.id}
                            getLabel={(list) => list.name}
                            value={matrixDesignerForm.auto_source_list_id || null}
                            onChange={(list) => updateMatrixDesignerForm((c) => ({ ...c, auto_source_list_id: list ? String(list.id) : "" }))}
                            nullLabel={t("chooseListPlaceholderDots")}
                          />
                        </span>
                      ) : null}
                    </>
                  ) : null}
                </div>
              </div>
              <div className="matrix-designer-strip-actions">
                <button
                  type="button"
                  className="button-secondary"
                  onClick={() => {
                    const nextId = nextTableFieldId(matrixDesignerRows);
                    updateMatrixDesignerForm((c) => ({ ...c, table_fields: [...c.table_fields, defaultFieldRow(nextId)] }));
                    setSelectedMatrixRowId(nextId);
                  }}
                >
                  + Zeile
                </button>
                {matrixDesignerForm.matrix_mode !== "auto" ? (
                  <button
                    type="button"
                    className="button-secondary"
                    onClick={() => {
                      const nextId = nextMatrixColumnConfigId(matrixDesignerColumns);
                      updateMatrixDesignerForm((c) => ({ ...c, matrix_columns: [...c.matrix_columns, defaultMatrixColumn(nextId)] }));
                      setSelectedMatrixColumnId(nextId);
                    }}
                  >
                    + Spalte
                  </button>
                ) : (
                  <button
                    type="button"
                    className="button-secondary"
                    disabled={matrixPreviewLoading}
                    onClick={() => { void loadMatrixPreview(); }}
                  >
                    {matrixPreviewLoading ? t("loadingDots") : matrixPreviewColumns ? t("refresh") : t("previewAction")}
                  </button>
                )}
              </div>
            </div>

            {/* ── Main body: grid + editor panel ── */}
            <div className="matrix-designer-body">

              {/* Grid */}
              <div className="matrix-designer-grid-scroll">
                {(() => {
                  const designerColCount = matrixDesignerForm.matrix_mode === "auto"
                    ? (matrixPreviewColumns ? matrixPreviewColumns.length : 1)
                    : matrixDesignerColumns.length || 1;
                  return (
                <div
                  className="matrix-designer-grid matrix-designer-grid--compact"
                  style={{ gridTemplateColumns: `minmax(140px, 180px) repeat(${designerColCount}, minmax(140px, 1fr))` }}
                >
                  <div className="matrix-designer-corner">{t("matrixSectionTitle")}</div>
                  {matrixDesignerForm.matrix_mode !== "auto" && matrixDesignerColumns.map((column, index) => (
                    <button
                      key={`mc-${column.id}`}
                      type="button"
                      className={`matrix-designer-column-button${selectedMatrixColumn?.id === column.id ? " matrix-designer-column-button-active" : ""}`}
                      onClick={() => setSelectedMatrixColumnId(column.id)}
                    >
                      <strong>{column.title || `Spalte ${index + 1}`}</strong>
                      {column.event_tag_filter ? <span className="muted">{column.event_tag_filter}</span> : null}
                    </button>
                  ))}
                  {matrixDesignerForm.matrix_mode === "auto" && matrixPreviewColumns && matrixPreviewColumns.map((col) => (
                    <div key={col.id} className="matrix-designer-column-button matrix-designer-column-preview">
                      <strong>{col.title}</strong>
                    </div>
                  ))}
                  {matrixDesignerForm.matrix_mode === "auto" && !matrixPreviewColumns && (
                    <div className="matrix-designer-column-button matrix-designer-column-placeholder">
                      <span className="muted">{matrixPreviewLoading ? "Lädt…" : "↑ Vorschau"}</span>
                    </div>
                  )}
                  {matrixDesignerRows.map((row, rowIndex) => (
                    <Fragment key={`mr-${row.id}`}>
                      <button
                        type="button"
                        className={`matrix-designer-row-button${selectedMatrixRow?.id === row.id ? " matrix-designer-row-button-active" : ""}`}
                        onClick={() => setSelectedMatrixRowId(row.id)}
                      >
                        <strong>{row.label || `Zeile ${rowIndex + 1}`}</strong>
                        <span className="muted">{matrixEmbeddedBlockLabel(row.row_type, tTypes, t) !== t("valueType.value") ? matrixEmbeddedBlockLabel(row.row_type, tTypes, t) : valueTypeLabel(row.row_type as Parameters<typeof valueTypeLabel>[0], t)}</span>
                      </button>
                      {matrixDesignerForm.matrix_mode !== "auto" && matrixDesignerColumns.map((column, columnIndex) => (
                        <button
                          key={`cell-${row.id}-${column.id}`}
                          type="button"
                          className={`matrix-designer-cell${selectedMatrixRow?.id === row.id && selectedMatrixColumn?.id === column.id ? " matrix-designer-cell-active" : ""}`}
                          onClick={() => { setSelectedMatrixRowId(row.id); setSelectedMatrixColumnId(column.id); }}
                        >
                          <strong>{column.title || `Sp. ${columnIndex + 1}`}</strong>
                          <span className="muted">
                            {matrixEmbeddedBlockLabel(row.row_type, tTypes, t) !== t("valueType.value")
                              ? matrixEmbeddedBlockLabel(row.row_type, tTypes, t)
                              : row.row_type === "events"
                              ? (column.event_tag_filter || (row.row_config?.event_tag_filter as string | undefined) || t("allEvents"))
                              : valueTypeLabel(row.row_type as Parameters<typeof valueTypeLabel>[0], t)}
                          </span>
                        </button>
                      ))}
                      {matrixDesignerForm.matrix_mode === "auto" && matrixPreviewColumns && matrixPreviewColumns.map((col) => (
                        <div key={`pv-${row.id}-${col.id}`} className="matrix-designer-cell matrix-designer-cell-preview">
                          <span className="muted">{row.auto_source_field || valueTypeLabel(row.row_type as Parameters<typeof valueTypeLabel>[0], t)}</span>
                        </div>
                      ))}
                      {matrixDesignerForm.matrix_mode === "auto" && !matrixPreviewColumns && (
                        <div className="matrix-designer-cell matrix-designer-column-placeholder" />
                      )}
                    </Fragment>
                  ))}
                </div>
                  );
                })()}
              </div>

              {/* Editor panel */}
              <div className="matrix-designer-panel">
                {selectedMatrixRow ? (
                  <div className="matrix-designer-panel-section">
                    <div className="matrix-designer-panel-header">
                      <div>
                        <div className="eyebrow">{t("rowWord")}</div>
                        <strong>{selectedMatrixRow.label || t("newRow")}</strong>
                      </div>
                      <button
                        type="button"
                        className="button-secondary button-danger"
                        onClick={() => {
                          updateMatrixDesignerForm((c) => ({ ...c, table_fields: c.table_fields.filter((e) => e.id !== selectedMatrixRow.id) }));
                          const next = matrixDesignerRows.find((e) => e.id !== selectedMatrixRow.id) ?? null;
                          setSelectedMatrixRowId(next?.id ?? null);
                        }}
                      >
                        Entfernen
                      </button>
                    </div>
                    <label className="field-stack">
                      <span className="field-label">{t("rowLabelLabel")}</span>
                      <input
                        value={selectedMatrixRow.label}
                        onChange={(event) =>
                          updateMatrixDesignerForm((current) => ({
                            ...current,
                            table_fields: current.table_fields.map((entry) =>
                              entry.id === selectedMatrixRow.id ? { ...entry, label: event.target.value } : entry
                            ),
                          }))
                        }
                        placeholder={t("rowLabelPlaceholder")}
                      />
                    </label>
                    <label className="checkbox-row">
                      <input
                        type="checkbox"
                        checked={Boolean(selectedMatrixRow.locked_in_protocol)}
                        onChange={(event) =>
                          updateMatrixDesignerForm((current) => ({
                            ...current,
                            table_fields: current.table_fields.map((entry) =>
                              entry.id === selectedMatrixRow.id ? { ...entry, locked_in_protocol: event.target.checked } : entry
                            ),
                          }))
                        }
                      />
                      Diese Zeile ist im Protokoll gesperrt
                    </label>
                    <label className="field-stack">
                      <span className="field-label">{t("rowTypeLabel")}</span>
                      <select
                        value={selectedMatrixRow.row_type}
                        onChange={(event) => {
                          const newRowType = event.target.value;
                          const isEmbedded = !["text", "participant", "participants", "event", "events"].includes(newRowType);
                          updateMatrixDesignerForm((current) => ({
                            ...current,
                            table_fields: current.table_fields.map((entry) =>
                              entry.id === selectedMatrixRow.id
                                ? {
                                    ...entry,
                                    row_type: newRowType,
                                    row_config: isEmbedded
                                      ? matrixEmbeddedBlockConfiguration(newRowType, entry.row_config)
                                      : (newRowType === "events" ? { event_tag_filter: "", event_title_filter: "", use_column_title_as_tag: true, hide_past_events: true } : {}),
                                  }
                                : entry
                            ),
                          }));
                        }}
                      >
                        <optgroup label={t("simpleValuesGroup")}>
                          {valueTypeChoices("11", t).map((option) => (
                            <option key={`matrix-row-type-${option.value}`} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </optgroup>
                        <optgroup label={t("embeddedBlocksGroup")}>
                          {matrixEmbeddedBlockOptions.map((option) => (
                            <option key={`matrix-embedded-type-${option.value}`} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </optgroup>
                      </select>
                    </label>
                    {selectedMatrixRow.row_type === "7" ? (
                      <div className="grid">
                        <div className="three-col">
                          <label className="field-stack">
                            <span className="field-label">{t("eventTagFilterLabel")}</span>
                            <TagInput
                              value={String(selectedMatrixEmbeddedConfig.event_tag_filter ?? "")}
                              onChange={(v) => updateSelectedMatrixRowConfig({ event_tag_filter: v })}
                              suggestions={knownEventTags}
                  tagConfig={tagConfig}
                  onTagColorChange={updateTagColor}
                  onTagRename={renameTag}
                              placeholder={t("emptyForAllTags")}
                            />
                          </label>
                          <label className="checkbox-row">
                            <input
                              type="checkbox"
                              checked={selectedMatrixEmbeddedConfig.event_only_from_protocol_date !== false}
                              onChange={(event) =>
                                updateSelectedMatrixRowConfig({ event_only_from_protocol_date: event.target.checked })
                              }
                            />
                            Nur Termine ab Protokolldatum anzeigen
                          </label>
                          <label className="checkbox-row">
                            <input
                              type="checkbox"
                              checked={selectedMatrixEmbeddedConfig.event_gray_past !== false}
                              onChange={(event) => updateSelectedMatrixRowConfig({ event_gray_past: event.target.checked })}
                            />
                            Vergangene Termine ausgegraut darstellen
                          </label>
                          <label className="checkbox-row">
                            <input
                              type="checkbox"
                              checked={selectedMatrixEmbeddedConfig.event_allow_end_date === true}
                              onChange={(event) => updateSelectedMatrixRowConfig({ event_allow_end_date: event.target.checked })}
                            />
                            Mehrtägige Termine erlauben
                          </label>
                          <label className="checkbox-row">
                            <input
                              type="checkbox"
                              checked={selectedMatrixEmbeddedConfig.event_use_column_tag_filter === true}
                              onChange={(event) =>
                                updateSelectedMatrixRowConfig({ event_use_column_tag_filter: event.target.checked })
                              }
                            />
                            Spalten-Tagfilter zusätzlich anwenden
                          </label>
                        </div>
                        <div className="three-col">
                          <label className="checkbox-row">
                            <input
                              type="checkbox"
                              checked={selectedMatrixEmbeddedConfig.event_show_date !== false}
                              onChange={(event) => updateSelectedMatrixRowConfig({ event_show_date: event.target.checked })}
                            />
                            Spalte Datum
                          </label>
                          <label className="checkbox-row">
                            <input
                              type="checkbox"
                              checked={selectedMatrixEmbeddedConfig.event_show_tag !== false}
                              onChange={(event) => updateSelectedMatrixRowConfig({ event_show_tag: event.target.checked })}
                            />
                            Spalte Tag
                          </label>
                          <label className="checkbox-row">
                            <input
                              type="checkbox"
                              checked={selectedMatrixEmbeddedConfig.event_show_title !== false}
                              onChange={(event) => updateSelectedMatrixRowConfig({ event_show_title: event.target.checked })}
                            />
                            Spalte Titel
                          </label>
                          <label className="checkbox-row">
                            <input
                              type="checkbox"
                              checked={selectedMatrixEmbeddedConfig.event_show_description !== false}
                              onChange={(event) =>
                                updateSelectedMatrixRowConfig({ event_show_description: event.target.checked })
                              }
                            />
                            Spalte Beschreibung
                          </label>
                          <label className="checkbox-row">
                            <input
                              type="checkbox"
                              checked={selectedMatrixEmbeddedConfig.event_show_participant_count === true}
                              onChange={(event) =>
                                updateSelectedMatrixRowConfig({ event_show_participant_count: event.target.checked })
                              }
                            />
                            Spalte Teilnehmerzahl
                          </label>
                          <label className="checkbox-row">
                            <input
                              type="checkbox"
                              checked={selectedMatrixEmbeddedConfig.event_show_cancelled === true}
                              onChange={(event) =>
                                updateSelectedMatrixRowConfig({ event_show_cancelled: event.target.checked })
                              }
                            />
                            Spalte Abgesagt
                          </label>
                        </div>
                      </div>
                    ) : null}
                    {["text", "participant", "participants", "event"].includes(selectedMatrixRow.row_type) ? (
                      renderTypedInitialValueEditor(selectedMatrixRow, (patch) =>
                        updateMatrixDesignerForm((current) => ({
                          ...current,
                          table_fields: current.table_fields.map((entry) =>
                            entry.id === selectedMatrixRow.id ? { ...entry, ...patch } : entry
                          ),
                        }))
                      )
                    ) : null}
                    {selectedMatrixRow.row_type === "events" ? (
                      <div className="two-col">
                        <label className="field-stack">
                          <span className="field-label">{t("eventTitleFilterLabel")}</span>
                          <input
                            value={String(selectedMatrixRow.row_config?.event_title_filter ?? "")}
                            onChange={(event) => updateSelectedMatrixRowConfig({ event_title_filter: event.target.value })}
                            placeholder={t("containsPlaceholder")}
                          />
                        </label>
                        <label className="field-stack">
                          <span className="field-label">{t("eventTagFilterLabel")}</span>
                          <TagInput
                            value={String(selectedMatrixRow.row_config?.event_tag_filter ?? "")}
                            onChange={(v) => updateSelectedMatrixRowConfig({ event_tag_filter: v })}
                            suggestions={knownEventTags}
                  tagConfig={tagConfig}
                  onTagColorChange={updateTagColor}
                  onTagRename={renameTag}
                            placeholder={t("emptyForAllTags")}
                          />
                        </label>
                        <label className="checkbox-row">
                          <input
                            type="checkbox"
                            checked={Boolean(selectedMatrixRow.row_config?.use_column_title_as_tag ?? true)}
                            onChange={(event) => updateSelectedMatrixRowConfig({ use_column_title_as_tag: event.target.checked })}
                          />
                          Spaltentitel als Tag verwenden
                        </label>
                        <label className="checkbox-row">
                          <input
                            type="checkbox"
                            checked={Boolean(selectedMatrixRow.row_config?.hide_past_events ?? true)}
                            onChange={(event) => updateSelectedMatrixRowConfig({ hide_past_events: event.target.checked })}
                          />
                          Vergangene Termine ausblenden
                        </label>
                      </div>
                    ) : null}
                    {matrixDesignerForm.matrix_mode === "auto" && matrixDesignerForm.auto_source_type ? (
                      <div className="grid">
                        <div className="eyebrow">{t("columnPlaceholdersHeading")}</div>
                        <label className="field-stack">
                          <span className="field-label">
                            {matrixDesignerForm.auto_source_type === "participants" ? t("valueFromParticipant") :
                             matrixDesignerForm.auto_source_type === "events" ? t("valueFromEvent") :
                             t("valueFromList")}
                          </span>
                          <select
                            value={selectedMatrixRow.auto_source_field ?? ""}
                            onChange={(event) =>
                              updateMatrixDesignerForm((current) => ({
                                ...current,
                                table_fields: current.table_fields.map((entry) =>
                                  entry.id === selectedMatrixRow.id ? { ...entry, auto_source_field: event.target.value } : entry
                                ),
                              }))
                            }
                          >
                            <option value="">{t("noPlaceholder")}</option>
                            {matrixDesignerForm.auto_source_type === "participants" ? (
                              <>
                                <option value="display_name">{t("fieldDisplayName")}</option>
                                <option value="first_name">{t("fieldFirstName")}</option>
                                <option value="last_name">{t("fieldLastName")}</option>
                                <option value="email">{t("fieldEmail")}</option>
                              </>
                            ) : matrixDesignerForm.auto_source_type === "events" ? (
                              <>
                                <option value="title">{t("fieldTitle")}</option>
                                <option value="event_date">{t("fieldDate")}</option>
                                <option value="tag">{t("fieldTag")}</option>
                                <option value="participant_count">{t("fieldParticipantCount")}</option>
                              </>
                            ) : (
                              <>
                                <option value="column_one">{t("fieldColumnOne")}</option>
                                <option value="column_two">{t("fieldColumnTwo")}</option>
                              </>
                            )}
                          </select>
                          <span className="field-help">{t("autoSourceFieldHelp")}</span>
                        </label>
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <p className="muted">{t("selectRowHint")}</p>
                )}

                {matrixDesignerForm.matrix_mode !== "auto" && selectedMatrixColumn ? (
                  <div className="matrix-designer-panel-section">
                    <div className="matrix-designer-panel-header">
                      <div>
                        <div className="eyebrow">{t("columnWord")}</div>
                        <strong>{selectedMatrixColumn.title || t("newColumn")}</strong>
                      </div>
                      <button
                        type="button"
                        className="button-secondary button-danger"
                        onClick={() => {
                          updateMatrixDesignerForm((c) => ({ ...c, matrix_columns: c.matrix_columns.filter((e) => e.id !== selectedMatrixColumn.id) }));
                          const next = matrixDesignerColumns.find((e) => e.id !== selectedMatrixColumn.id) ?? null;
                          setSelectedMatrixColumnId(next?.id ?? null);
                        }}
                      >
                        Entfernen
                      </button>
                    </div>
                    <label className="field-stack">
                      <span className="field-label">{t("columnTitleLabel")}</span>
                      <input
                        value={selectedMatrixColumn.title}
                        onChange={(e) => updateMatrixDesignerForm((c) => ({ ...c, matrix_columns: c.matrix_columns.map((col) => col.id === selectedMatrixColumn.id ? { ...col, title: e.target.value } : col) }))}
                        placeholder={t("columnTitlePlaceholder")}
                      />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">{t("columnPlaceholderLabel")}</span>
                      <input
                        value={selectedMatrixColumn.title_placeholder ?? ""}
                        onChange={(e) => updateMatrixDesignerForm((c) => ({ ...c, matrix_columns: c.matrix_columns.map((col) => col.id === selectedMatrixColumn.id ? { ...col, title_placeholder: e.target.value } : col) }))}
                        placeholder={t("columnPlaceholderPlaceholder")}
                      />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">{t("columnTagFilterLabel")}</span>
                      <TagInput
                        value={selectedMatrixColumn.event_tag_filter ?? ""}
                        onChange={(v) => updateMatrixDesignerForm((c) => ({ ...c, matrix_columns: c.matrix_columns.map((col) => col.id === selectedMatrixColumn.id ? { ...col, event_tag_filter: v } : col) }))}
                        suggestions={knownEventTags}
                  tagConfig={tagConfig}
                  onTagColorChange={updateTagColor}
                  onTagRename={renameTag}
                        placeholder={t("optional")}
                      />
                    </label>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        ) : null}
      </Modal>

      <Modal
        open={tableDesignerMode !== null && !!tableDesignerForm}
        onEscape={saveTableDesigner}
        onClose={closeTableDesigner}
        title={t("tableDesignerTitle")}
        description={t("tableDesignerDescription")}
        size="fullscreen"
        headerActions={
          tableDesignerMode === "edit" ? (
            <button type="button" className="button-secondary" onClick={() => { void saveTableDesigner(); }}>
              Übernehmen
            </button>
          ) : undefined
        }
      >
        {tableDesignerForm ? (
          <div className="matrix-designer-layout">
            <div className="matrix-designer-strip">
              <div className="matrix-designer-strip-left" />
              <div className="matrix-designer-strip-actions">
                <button type="button" className="button-secondary" onClick={addTableDesignerRow}>
                  + Zeile
                </button>
              </div>
            </div>
            <div className="table-designer-body">
              <div className="matrix-designer-grid-scroll">
                <div className="table-designer-row-list">
                  {selectedEventFields(tableDesignerForm).length > 0 ? (
                    <DataTable columns={[tableDesignerForm.left_column_heading || t("rowWord"), tableDesignerForm.value_column_heading || t("valueWord")]}>
                      {eventFieldPreviewRows(tableDesignerForm, t)}
                    </DataTable>
                  ) : null}
                  {tableDesignerRows.map((row, index) => (
                    <button
                      key={`table-row-${row.id}`}
                      type="button"
                      draggable
                      className={`matrix-designer-row-button${selectedTableRow?.id === row.id ? " matrix-designer-row-button-active" : ""}`}
                      onClick={() => setSelectedTableRowId(row.id)}
                      onDragStart={() => setDraggedTableRowId(row.id)}
                      onDragEnd={() => setDraggedTableRowId(null)}
                      onDragOver={(event) => event.preventDefault()}
                      onDrop={(event) => {
                        event.preventDefault();
                        const sourceId = draggedTableRowId;
                        setDraggedTableRowId(null);
                        if (sourceId) {
                          reorderTableDesignerRows(sourceId, row.id);
                        }
                      }}
                    >
                      <strong>{row.label || `Zeile ${index + 1}`}</strong>
                      <span className="muted">{valueTypeLabel(row.row_type as Parameters<typeof valueTypeLabel>[0], t)}</span>
                    </button>
                  ))}
                </div>
              </div>
              <div className="matrix-designer-panel">
                {selectedTableRow ? (
                  <div className="matrix-designer-panel-section">
                    <div className="matrix-designer-panel-header">
                      <div>
                        <div className="eyebrow">{t("rowWord")}</div>
                        <strong>{selectedTableRow.label || t("newRow")}</strong>
                      </div>
                      <button
                        type="button"
                        className="button-secondary button-danger"
                        onClick={() => removeTableDesignerRow(selectedTableRow.id)}
                      >
                        Entfernen
                      </button>
                    </div>
                    <label className="field-stack">
                      <span className="field-label">{selectedTableRow.row_type === "list_entry" ? "Alias (optional)" : "Zeilenlabel"}</span>
                      <input
                        value={selectedTableRow.label}
                        onChange={(event) =>
                          updateTableDesignerForm((current) => ({
                            ...current,
                            table_fields: current.table_fields.map((entry) =>
                              entry.id === selectedTableRow.id ? { ...entry, label: event.target.value } : entry
                            ),
                          }))
                        }
                        placeholder={selectedTableRow.row_type === "list_entry" ? "Leer lassen für Listenwert" : "z. B. Verantwortlich"}
                      />
                    </label>
                    <label className="checkbox-row">
                      <input
                        type="checkbox"
                        checked={Boolean(selectedTableRow.locked_in_protocol)}
                        onChange={(event) =>
                          updateTableDesignerForm((current) => ({
                            ...current,
                            table_fields: current.table_fields.map((entry) =>
                              entry.id === selectedTableRow.id ? { ...entry, locked_in_protocol: event.target.checked } : entry
                            ),
                          }))
                        }
                      />
                      Diese Zeile ist im Protokoll gesperrt
                    </label>
                    <label className="field-stack">
                      <span className="field-label">{t("dataTypeLabel")}</span>
                      <select
                        value={selectedTableRow.row_type}
                        onChange={(event) =>
                          updateTableDesignerForm((current) => ({
                            ...current,
                            table_fields: current.table_fields.map((entry) =>
                              entry.id === selectedTableRow.id ? { ...entry, row_type: event.target.value } : entry
                            ),
                          }))
                        }
                      >
                        {valueTypeChoices("6", t).map((option) => (
                          <option key={`table-designer-row-type-${option.value}`} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    {renderTypedInitialValueEditor(selectedTableRow, (patch) =>
                      updateTableDesignerForm((current) => ({
                        ...current,
                        table_fields: current.table_fields.map((entry) =>
                          entry.id === selectedTableRow.id ? { ...entry, ...patch } : entry
                        ),
                      }))
                    )}
                  </div>
                ) : (
                  <p className="muted">{t("noRowSelected")}</p>
                )}
              </div>
            </div>
          </div>
        ) : null}
      </Modal>

    </div>
  );
}
