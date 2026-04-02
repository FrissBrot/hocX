"use client";

import { FormEvent, Fragment, useEffect, useMemo, useState } from "react";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { ElementDefinition, ElementDefinitionBlock, EventSummary, ParticipantSummary, StructuredListDefinition, StructuredListEntry } from "@/types/api";

type ElementDefinitionManagerProps = {
  initialDefinitions: ElementDefinition[];
  knownEventTags: string[];
  availableParticipants?: ParticipantSummary[];
  availableEvents?: EventSummary[];
  availableLists?: StructuredListDefinition[];
};

type DefinitionFormState = {
  title: string;
  description: string;
  is_active: boolean;
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
  event_tag_filter: string;
  event_title_filter: string;
  event_description_filter: string;
  event_window_start_days: string;
  event_window_end_days: string;
  event_date_mode: "relative_window" | "all_future";
  event_include_unlisted_past: boolean;
  event_only_from_protocol_date: boolean;
  event_gray_past: boolean;
  event_allow_end_date: boolean;
  event_show_date: boolean;
  event_show_tag: boolean;
  event_show_title: boolean;
  event_show_description: boolean;
  event_show_participant_count: boolean;
  allow_column_management: boolean;
  matrix_mode: "manual" | "auto";
  auto_source_type: "" | "participants" | "events" | "list";
  auto_source_list_id: string;
  auto_source_event_tag: string;
  todo_block_title_filter: string;
  todo_task_filter: string;
  todo_open_only: boolean;
  left_column_heading: string;
  value_column_heading: string;
  linked_list_id: string;
  is_editable: boolean;
  export_visible: boolean;
  is_visible: boolean;
  sort_index: string;
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
  }>;
};

const initialDefinitionForm: DefinitionFormState = {
  title: "",
  description: "",
  is_active: true
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
  event_tag_filter: "",
  event_title_filter: "",
  event_description_filter: "",
  event_window_start_days: "0",
  event_window_end_days: "14",
  event_date_mode: "relative_window",
  event_include_unlisted_past: false,
  event_only_from_protocol_date: true,
  event_gray_past: true,
  event_allow_end_date: false,
  event_show_date: true,
  event_show_tag: true,
  event_show_title: true,
  event_show_description: true,
  event_show_participant_count: false,
  allow_column_management: true,
  matrix_mode: "manual" as "manual" | "auto",
  auto_source_type: "" as "" | "participants" | "events" | "list",
  auto_source_list_id: "",
  auto_source_event_tag: "",
  todo_block_title_filter: "",
  todo_task_filter: "",
  todo_open_only: true,
  left_column_heading: "",
  value_column_heading: "",
  linked_list_id: "",
  is_editable: true,
  export_visible: true,
  is_visible: true,
  sort_index: "10",
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

const elementTypeOptions = [
  { value: "1", label: "Text", description: "Editierbarer Text mit Markdown (fett, kursiv, Listen)" },
  { value: "2", label: "Todo", description: "Checklist or task list" },
  { value: "3", label: "Image", description: "Image upload area" },
  { value: "6", label: "Table", description: "Rows with labels and typed values such as text, participant or event" },
  { value: "7", label: "Events", description: "Filtered list of events in a table" },
  { value: "9", label: "Attendance", description: "Attendance list for all template participants" },
  { value: "10", label: "Session date", description: "Set the next session date inside the protocol" },
  { value: "11", label: "Matrix", description: "Responsive matrix with free values, participants and automatic event rows" }
];

const matrixEmbeddedBlockOptions = [
  { value: "1", label: "Text" },
  { value: "6", label: "Tabelle" },
  { value: "2", label: "Todo" },
  { value: "3", label: "Bild" },
  { value: "7", label: "Terminliste" },
  { value: "9", label: "Anwesenheit" },
  { value: "10", label: "Sitzungsdatum" },
];

const renderTypeLabels: Record<string, string> = {
  "1": "Heading",
  "2": "Paragraph",
  "3": "Todo list",
  "4": "Image",
  "5": "Key-value",
  "6": "Plain text",
  "7": "Raw LaTeX"
};

function optionLabel(options: { value: string; label: string }[], value: number | string) {
  return options.find((option) => option.value === String(value))?.label ?? `Unknown (${value})`;
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
  };
  return mapping[String(elementTypeId)] ?? "text";
}

function definitionFormFromDefinition(definition: ElementDefinition): DefinitionFormState {
  return {
    title: definition.title,
    description: definition.description ?? "",
    is_active: definition.is_active
  };
}

function inferAllowsMultipleValues(elementTypeId: string | number) {
  return String(elementTypeId) === "2" || String(elementTypeId) === "3";
}

function valueTypeChoices(elementTypeId: string) {
  const choices: Array<{ value: "text" | "participant" | "participants" | "event" | "events"; label: string }> = [
    { value: "text", label: "Freier Text" },
    { value: "participant", label: "Ein Teilnehmer" },
    { value: "participants", label: "Mehrere Teilnehmer" },
    { value: "event", label: "Ein Termin" },
  ];
  if (elementTypeId === "11") {
    choices.push({ value: "events", label: "Mehrere Termine (automatisch)" });
  }
  return choices;
}

function valueTypeLabel(valueType: "text" | "participant" | "participants" | "event" | "events") {
  switch (valueType) {
    case "participant":
      return "Ein Teilnehmer";
    case "participants":
      return "Mehrere Teilnehmer";
    case "event":
      return "Ein Termin";
    case "events":
      return "Mehrere Termine";
    default:
      return "Freier Text";
  }
}

function matrixEmbeddedBlockLabel(elementTypeId: string | number | null | undefined) {
  return matrixEmbeddedBlockOptions.find((option) => option.value === String(elementTypeId ?? ""))?.label ?? "Wert";
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
      event_gray_past: true,
      event_allow_end_date: false,
      event_use_column_tag_filter: false,
      event_show_date: true,
      event_show_tag: true,
      event_show_title: true,
      event_show_description: true,
      event_show_participant_count: false,
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
    event_tag_filter: String(block.configuration_json?.event_tag_filter ?? ""),
    event_title_filter: String(block.configuration_json?.event_title_filter ?? ""),
    event_description_filter: String(block.configuration_json?.event_description_filter ?? ""),
    event_window_start_days: String(block.configuration_json?.event_window_start_days ?? "0"),
    event_window_end_days: String(block.configuration_json?.event_window_end_days ?? "14"),
    event_date_mode: (String(block.configuration_json?.event_date_mode ?? "relative_window") as "relative_window" | "all_future"),
    event_include_unlisted_past: Boolean(block.configuration_json?.event_include_unlisted_past ?? false),
    event_only_from_protocol_date: Boolean(block.configuration_json?.event_only_from_protocol_date ?? true),
    event_gray_past: Boolean(block.configuration_json?.event_gray_past ?? true),
    event_allow_end_date: Boolean(block.configuration_json?.event_allow_end_date ?? false),
    event_show_date: Boolean(block.configuration_json?.event_show_date ?? true),
    event_show_tag: Boolean(block.configuration_json?.event_show_tag ?? true),
    event_show_title: Boolean(block.configuration_json?.event_show_title ?? true),
    event_show_description: Boolean(block.configuration_json?.event_show_description ?? true),
    event_show_participant_count: Boolean(block.configuration_json?.event_show_participant_count ?? false),
    allow_column_management: Boolean(
      block.configuration_json?.allow_column_management ?? block.configuration_json?.matrix_allow_column_management ?? true
    ),
    matrix_mode: ((block.configuration_json?.mode ?? "manual") === "auto" ? "auto" : "manual") as "manual" | "auto",
    auto_source_type: (() => {
      const autoSrc = block.configuration_json?.auto_source;
      if (autoSrc && typeof autoSrc === "object" && (autoSrc as any).type) return (autoSrc as any).type as "" | "participants" | "events" | "list";
      return (String(block.configuration_json?.matrix_column_source ?? "") as "" | "participants" | "events" | "list");
    })(),
    auto_source_list_id: (() => {
      const autoSrc = block.configuration_json?.auto_source;
      if (autoSrc && typeof autoSrc === "object" && (autoSrc as any).list_id != null) return String((autoSrc as any).list_id);
      return block.configuration_json?.matrix_column_source_list_id != null ? String(block.configuration_json.matrix_column_source_list_id) : "";
    })(),
    auto_source_event_tag: (() => {
      const autoSrc = block.configuration_json?.auto_source;
      if (autoSrc && typeof autoSrc === "object") return String((autoSrc as any).event_tag_filter ?? "");
      return String(block.configuration_json?.matrix_column_source_event_tag ?? "");
    })(),
    todo_block_title_filter: String(block.configuration_json?.todo_block_title_filter ?? ""),
    todo_task_filter: String(block.configuration_json?.todo_task_filter ?? ""),
    todo_open_only: Boolean(block.configuration_json?.todo_open_only ?? true),
    left_column_heading: String(block.configuration_json?.left_column_heading ?? ""),
    value_column_heading: String(block.configuration_json?.value_column_heading ?? ""),
    linked_list_id: block.configuration_json?.linked_list_id != null ? String(block.configuration_json?.linked_list_id) : "",
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
      event_tag_filter: form.event_tag_filter || null,
      event_title_filter: form.event_title_filter || null,
      event_description_filter: form.event_description_filter || null,
      event_window_start_days: Number(form.event_window_start_days || "0"),
      event_window_end_days: Number(form.event_window_end_days || "14"),
      event_date_mode: form.event_date_mode,
      event_include_unlisted_past: form.event_include_unlisted_past,
      event_only_from_protocol_date: form.event_only_from_protocol_date,
      event_gray_past: form.event_gray_past,
      event_allow_end_date: form.event_allow_end_date,
      event_show_date: form.event_show_date,
      event_show_tag: form.event_show_tag,
      event_show_title: form.event_show_title,
      event_show_description: form.event_show_description,
      event_show_participant_count: form.event_show_participant_count,
      mode: form.matrix_mode,
      allow_column_management: form.allow_column_management,
      auto_source: form.auto_source_type ? {
        type: form.auto_source_type,
        list_id: form.auto_source_type === "list" && form.auto_source_list_id ? Number(form.auto_source_list_id) : null,
        event_tag_filter: form.auto_source_type === "events" ? (form.auto_source_event_tag || null) : null,
      } : null,
      todo_block_title_filter: form.todo_block_title_filter || null,
      todo_task_filter: form.todo_task_filter || null,
      todo_open_only: form.todo_open_only,
      left_column_heading: form.left_column_heading || null,
      value_column_heading: form.value_column_heading || null,
      linked_list_id:
        form.element_type_id === "6" && form.linked_list_id ? Number(form.linked_list_id) : null,
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
              template_participant_id: field.template_participant_id ? Number(field.template_participant_id) : null,
              template_participant_ids: (field.template_participant_ids ?? []).map((participantId) => Number(participantId)).filter(Boolean),
              template_event_id: field.template_event_id ? Number(field.template_event_id) : null,
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

function blockDisplayName(block: { title?: string | null; block_title?: string | null }) {
  const title = String(block.title ?? "").trim();
  const subtitle = String(block.block_title ?? "").trim();
  if (title) {
    return title;
  }
  if (subtitle) {
    return `Direkt unter "${subtitle}"`;
  }
  return "Direkt unter dem Elementtitel";
}

export function ElementDefinitionManager({
  initialDefinitions,
  knownEventTags,
  availableParticipants,
  availableEvents,
  availableLists,
}: ElementDefinitionManagerProps) {
  const [definitions, setDefinitions] = useState(initialDefinitions);
  const [selectedDefinitionId, setSelectedDefinitionId] = useState<number | null>(initialDefinitions[0]?.id ?? null);
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
  const [showCreateDefinition, setShowCreateDefinition] = useState(false);
  const [showDetailModal, setShowDetailModal] = useState(false);
  const [showCreateBlockModal, setShowCreateBlockModal] = useState(false);
  const [showEditBlockModal, setShowEditBlockModal] = useState(false);
  const [typePickerMode, setTypePickerMode] = useState<"create" | "edit" | null>(null);
  const [showCreateBlockHelp, setShowCreateBlockHelp] = useState(false);
  const [showEditBlockHelp, setShowEditBlockHelp] = useState(false);
  const [matrixDesignerMode, setMatrixDesignerMode] = useState<"create" | "edit" | null>(null);
  const [selectedMatrixRowId, setSelectedMatrixRowId] = useState<string | null>(null);
  const [selectedMatrixColumnId, setSelectedMatrixColumnId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("Ready");
  const [statusTone, setStatusTone] = useState<"neutral" | "success" | "error">("neutral");
  const [draggedBlockId, setDraggedBlockId] = useState<number | null>(null);
  const [matrixPreviewColumns, setMatrixPreviewColumns] = useState<Array<{ id: string; title: string }> | null>(null);
  const [matrixPreviewLoading, setMatrixPreviewLoading] = useState(false);
  const participantOptions = Array.isArray(availableParticipants) ? availableParticipants : [];
  const eventOptions = Array.isArray(availableEvents) ? availableEvents : [];
  const listOptions = Array.isArray(availableLists) ? availableLists : [];

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

  async function loadMatrixPreview() {
    if (!matrixDesignerForm) return;
    const source = matrixDesignerForm.auto_source_type;
    setMatrixPreviewLoading(true);
    try {
      if (source === "participants") {
        setMatrixPreviewColumns(
          participantOptions.map((p) => ({ id: `prev-p-${p.id}`, title: p.display_name }))
        );
      } else if (source === "events") {
        const tagFilter = matrixDesignerForm.auto_source_event_tag.trim().toLowerCase();
        const filtered = tagFilter
          ? sortedAvailableEvents.filter((e) => String(e.tag ?? "").toLowerCase() === tagFilter)
          : sortedAvailableEvents;
        setMatrixPreviewColumns(filtered.map((e) => ({ id: `prev-e-${e.id}`, title: e.title })));
      } else if (source === "list") {
        const listDefId = Number(matrixDesignerForm.auto_source_list_id || 0);
        if (!listDefId) {
          setMatrixPreviewColumns([]);
        } else {
          const entries = await browserApiFetch<StructuredListEntry[]>(`/api/lists/${listDefId}/entries`);
          setMatrixPreviewColumns(
            (entries ?? []).map((entry) => ({
              id: `prev-l-${entry.id}`,
              title:
                String((entry.column_one_value as any)?.text_value ?? "").trim() ||
                String((entry.column_two_value as any)?.text_value ?? "").trim() ||
                `Eintrag ${entry.id}`,
            }))
          );
        }
      }
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
        : matrixEmbeddedBlockConfiguration(String((selectedMatrixRow as any).embedded_element_type_id ?? ""), (selectedMatrixRow as any).embedded_configuration_json))
    : {};
  const selectedMatrixColumn =
    matrixDesignerColumns.find((column) => column.id === selectedMatrixColumnId) ?? matrixDesignerColumns[0] ?? null;
  const createLinkedList = useMemo(
    () => listOptions.find((entry) => entry.id === Number(createBlockForm.linked_list_id || 0)) ?? null,
    [createBlockForm.linked_list_id, listOptions]
  );
  const editLinkedList = useMemo(
    () => listOptions.find((entry) => entry.id === Number(blockForm.linked_list_id || 0)) ?? null,
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
          <span className="field-label">Initialer Teilnehmer</span>
          <select
            value={field.template_participant_id ?? ""}
            onChange={(event) => applyPatch({ template_participant_id: event.target.value })}
          >
            <option value="">Kein Standardwert</option>
            {participantOptions.map((participant) => (
              <option key={`initial-participant-${participant.id}`} value={participant.id}>
                {participant.display_name}
              </option>
            ))}
          </select>
        </label>
      );
    }

    if (field.row_type === "participants") {
      return (
        <label className="field-stack">
          <span className="field-label">Initiale Teilnehmer</span>
          <select
            multiple
            size={Math.min(6, Math.max(3, participantOptions.length || 3))}
            value={field.template_participant_ids ?? []}
            onChange={(event) =>
              applyPatch({
                template_participant_ids: Array.from(event.target.selectedOptions).map((option) => option.value),
              })
            }
          >
            {participantOptions.map((participant) => (
              <option key={`initial-participants-${participant.id}`} value={participant.id}>
                {participant.display_name}
              </option>
            ))}
          </select>
        </label>
      );
    }

    if (field.row_type === "event") {
      return (
        <label className="field-stack">
          <span className="field-label">Initialer Termin</span>
          <select
            value={field.template_event_id ?? ""}
            onChange={(event) => applyPatch({ template_event_id: event.target.value })}
          >
            <option value="">Kein Standardwert</option>
            {sortedAvailableEvents.map((eventRow) => (
              <option key={`initial-event-${eventRow.id}`} value={eventRow.id}>
                {eventRow.event_date} · {eventRow.title}
              </option>
            ))}
          </select>
        </label>
      );
    }

    if (field.row_type === "events") {
      return <p className="muted">Automatische Terminzeilen arbeiten mit Filtern, nicht mit einem festen Initialwert.</p>;
    }

    return (
      <label className="field-stack">
        <span className="field-label">{fieldLabel}</span>
        <input
          value={field.template_value ?? ""}
          onChange={(event) => applyPatch({ template_value: event.target.value })}
          placeholder="{title} oder fixer Text"
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

  async function createDefinition(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("Creating element...");
    setStatusTone("neutral");
    try {
      const created = await browserApiFetch<ElementDefinition>("/api/element-definitions", {
        method: "POST",
        body: JSON.stringify({
          tenant_id: 1,
          title: createDefinitionForm.title,
          description: createDefinitionForm.description || null,
          is_active: createDefinitionForm.is_active,
          blocks: []
        })
      });
      setDefinitions((current) => [created, ...current]);
      setCreateDefinitionForm(initialDefinitionForm);
      setShowCreateDefinition(false);
      selectDefinition(created);
      setStatus(`Created element #${created.id}`);
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Element creation failed");
      setStatusTone("error");
    }
  }

  async function saveDefinition(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedDefinition) return;
    setStatus(`Saving element #${selectedDefinition.id}...`);
    setStatusTone("neutral");
    try {
      const updated = await browserApiFetch<ElementDefinition>(`/api/element-definitions/${selectedDefinition.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: definitionForm.title,
          description: definitionForm.description || null,
          is_active: definitionForm.is_active,
          blocks: selectedDefinition.blocks
        })
      });
      replaceDefinition(updated);
      setStatus(`Saved element #${updated.id}`);
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Element save failed");
      setStatusTone("error");
    }
  }

  async function deleteDefinition(definitionId: number) {
    setStatus(`Deleting element #${definitionId}...`);
    setStatusTone("neutral");
    try {
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
      setStatus(`Deleted element #${definitionId}`);
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Element deletion failed");
      setStatusTone("error");
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
      setStatus(message);
      setStatusTone("success");
      const selected = updated.blocks.find((block) => block.id === selectedBlockId) ?? updated.blocks[0] ?? null;
      setSelectedBlockId(selected?.id ?? null);
      setBlockForm(selected ? blockFormFromBlock(selected) : { ...initialBlockForm, id: nextBlockId(updated.blocks), sort_index: nextSortIndex(updated.blocks) });
      setCreateBlockForm({ ...initialBlockForm, id: nextBlockId(updated.blocks), sort_index: nextSortIndex(updated.blocks) });
      return updated;
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Block update failed");
      setStatusTone("error");
      return null;
    }
  }

  async function persistEditedBlock(message: string) {
    if (!selectedDefinition || !selectedBlock) {
      return false;
    }
    setStatus("Saving block...");
    setStatusTone("neutral");
    const updatedBlock = blockPayload(blockForm);
    const nextBlocks = resequenceBlocks(
      selectedDefinition.blocks
        .map((block) => (block.id === selectedBlock.id ? updatedBlock : block))
        .sort((left, right) => left.sort_index - right.sort_index)
    );
    const updated = await saveBlocks(nextBlocks, message);
    return Boolean(updated);
  }

  async function closeMatrixDesigner() {
    if (matrixDesignerMode === "edit") {
      const saved = await persistEditedBlock("Matrix gespeichert");
      if (!saved) {
        return;
      }
    }
    setMatrixDesignerMode(null);
  }

  async function createBlock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedDefinition) return;
    setStatus("Adding block to element...");
    setStatusTone("neutral");
    const nextBlocks = resequenceBlocks(
      [...selectedDefinition.blocks, blockPayload({ ...createBlockForm, sort_index: nextSortIndex(selectedDefinition.blocks) })].sort(
        (left, right) => left.sort_index - right.sort_index
      )
    );
    await saveBlocks(nextBlocks, "Block added");
    setShowCreateBlockModal(false);
  }

  async function updateBlock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const saved = await persistEditedBlock("Block saved");
    if (saved) {
      setShowEditBlockModal(false);
    }
  }

  async function deleteBlock(blockId: number) {
    if (!selectedDefinition) return;
    setStatus("Deleting block...");
    setStatusTone("neutral");
    const nextBlocks = resequenceBlocks(selectedDefinition.blocks.filter((block) => block.id !== blockId));
    await saveBlocks(nextBlocks, "Block deleted");
  }

  async function reorderBlocks(sourceId: number, targetId: number) {
    if (!selectedDefinition || sourceId === targetId) return;
    setStatus("Saving block order...");
    setStatusTone("neutral");
    const ordered = [...selectedDefinition.blocks].sort((left, right) => left.sort_index - right.sort_index);
    const sourceIndex = ordered.findIndex((block) => block.id === sourceId);
    const targetIndex = ordered.findIndex((block) => block.id === targetId);
    if (sourceIndex === -1 || targetIndex === -1) {
      return;
    }
    const [moved] = ordered.splice(sourceIndex, 1);
    ordered.splice(targetIndex, 0, moved);
    await saveBlocks(resequenceBlocks(ordered), "Block order saved");
  }

function applyBlockType(elementTypeId: string, mode: "create" | "edit") {
  const nextEditable = !["5", "7", "9"].includes(elementTypeId);
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
    if (elementTypeId === "2") {
      return (
        <div className="block-type-preview">
          <div className="block-type-preview-title" />
          <div className="block-type-preview-chip-row">
            <div className="block-type-preview-chip" />
            <div className="block-type-preview-line block-type-preview-line-short" />
          </div>
          <div className="block-type-preview-chip-row">
            <div className="block-type-preview-chip" />
            <div className="block-type-preview-line" />
          </div>
          <div className="block-type-preview-chip-row">
            <div className="block-type-preview-chip" />
            <div className="block-type-preview-line block-type-preview-line-short" />
          </div>
        </div>
      );
    }
    if (elementTypeId === "3") {
      return (
        <div className="block-type-preview">
          <div className="block-type-preview-image" />
          <div className="block-type-preview-line block-type-preview-line-short" />
        </div>
      );
    }
    if (elementTypeId === "6") {
      return (
        <div className="block-type-preview">
          <div className="block-type-preview-chip-row">
            <div className="block-type-preview-chip" />
            <div className="block-type-preview-line block-type-preview-line-short" />
          </div>
          <div className="block-type-preview-chip-row">
            <div className="block-type-preview-chip" />
            <div className="block-type-preview-line" />
          </div>
          <div className="block-type-preview-chip-row">
            <div className="block-type-preview-chip" />
            <div className="block-type-preview-line block-type-preview-line-short" />
          </div>
        </div>
      );
    }
    if (elementTypeId === "7") {
      return (
        <div className="block-type-preview">
          <div className="block-type-preview-title" />
          <div className="block-type-preview-line" />
          <div className="block-type-preview-line" />
          <div className="block-type-preview-line" />
        </div>
      );
    }
    if (elementTypeId === "8") {
      return (
        <div className="block-type-preview">
          <div className="block-type-preview-chip-row">
            <div className="block-type-preview-chip" />
            <div className="block-type-preview-line" />
          </div>
          <div className="block-type-preview-chip-row">
            <div className="block-type-preview-chip" />
            <div className="block-type-preview-line block-type-preview-line-short" />
          </div>
          <div className="block-type-preview-chip-row">
            <div className="block-type-preview-chip" />
            <div className="block-type-preview-line" />
          </div>
        </div>
      );
    }
    if (elementTypeId === "9") {
      return (
        <div className="block-type-preview">
          <div className="block-type-preview-chip-row">
            <div className="block-type-preview-chip" />
            <div className="block-type-preview-chip" />
            <div className="block-type-preview-chip" />
          </div>
          <div className="block-type-preview-box" />
        </div>
      );
    }
    if (elementTypeId === "10") {
      return (
        <div className="block-type-preview">
          <div className="block-type-preview-title" />
          <div className="block-type-preview-line block-type-preview-line-short" />
          <div className="block-type-preview-line block-type-preview-line-short" />
        </div>
      );
    }
    if (elementTypeId === "11") {
      return (
        <div className="block-type-preview">
          <div className="block-type-preview-chip-row">
            <div className="block-type-preview-chip" />
            <div className="block-type-preview-chip" />
            <div className="block-type-preview-chip" />
          </div>
          <div className="block-type-preview-box" />
          <div className="block-type-preview-chip-row">
            <div className="block-type-preview-line block-type-preview-line-short" />
            <div className="block-type-preview-line block-type-preview-line-short" />
          </div>
        </div>
      );
    }
    if (elementTypeId === "5") {
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
      <DataToolbar
        title="Elements"
        description="Each element has a title and can contain multiple blocks such as text, todos or images. Templates only choose these finished elements and sort them."
        actions={
          <button type="button" className="button-inline" onClick={() => setShowCreateDefinition((current) => !current)}>
            {showCreateDefinition ? "Close create form" : "New element"}
          </button>
        }
      />

      <Modal
        open={showCreateDefinition}
        onClose={() => setShowCreateDefinition(false)}
        title="Create element"
        description="Build a reusable element with one title and multiple internal blocks."
      >
        <form className="grid" onSubmit={createDefinition}>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Element title</span>
              <input value={createDefinitionForm.title} onChange={(event) => setCreateDefinitionForm((current) => ({ ...current, title: event.target.value }))} placeholder="e.g. Zusammenarbeit mit Blauring" required />
              <span className="field-help">This is the main title of the whole element.</span>
            </label>
            <label className="field-stack">
              <span className="field-label">Description</span>
              <input value={createDefinitionForm.description} onChange={(event) => setCreateDefinitionForm((current) => ({ ...current, description: event.target.value }))} placeholder="Optional note for editors" />
              <span className="field-help">Optional explanation of what this element is for.</span>
            </label>
          </div>
          <label className="field-stack">
            <span className="field-label">State</span>
            <label className="checkbox-row">
              <input type="checkbox" checked={createDefinitionForm.is_active} onChange={(event) => setCreateDefinitionForm((current) => ({ ...current, is_active: event.target.checked }))} />
              Active
            </label>
            <span className="field-help">Inactive elements stay in the system but should not be chosen for new templates.</span>
          </label>
          <div className="table-toolbar-actions">
            <button type="submit" className="button-inline">Create element</button>
          </div>
        </form>
      </Modal>

      <article className="card">
        <div className="two-col">
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search elements" />
          <div className="info-note">Fixed blocks should be created here as non-editable blocks. They will appear read-only later in the protocol editor.</div>
        </div>
      </article>

      <StatusBanner tone={statusTone} message={status} />

      <DataTable columns={["Element", "Blocks", "State", "Actions"]}>
        {filteredDefinitions.map((definition) => (
          <tr key={definition.id} className={`table-row-clickable${selectedDefinitionId === definition.id ? " table-row-active" : ""}`} onClick={() => selectDefinition(definition)}>
            <td>
              <strong>{definition.title}</strong>
              <div className="muted">Element #{definition.id}</div>
            </td>
            <td>{definition.blocks.length} block{definition.blocks.length === 1 ? "" : "s"}</td>
            <td><span className="pill">{definition.is_active ? "active" : "inactive"}</span></td>
            <td>
              <div className="table-actions">
                <button type="button" className="button-inline button-danger" onClick={(event) => {
                  event.stopPropagation();
                  void deleteDefinition(definition.id);
                }}>Delete</button>
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
        title={selectedDefinition ? selectedDefinition.title : "Element detail"}
        description="Edit the element metadata and its internal blocks in one focused popup."
        size="wide"
      >
        {selectedDefinition ? (
        <>
          <article className="card">
            <div className="eyebrow">Element Detail</div>
            <h3>{selectedDefinition.title}</h3>
            <form className="grid" onSubmit={saveDefinition}>
              <div className="two-col">
                <label className="field-stack">
                  <span className="field-label">Element title</span>
                  <input value={definitionForm.title} onChange={(event) => setDefinitionForm((current) => ({ ...current, title: event.target.value }))} />
                </label>
                <label className="field-stack">
                  <span className="field-label">Description</span>
                  <input value={definitionForm.description} onChange={(event) => setDefinitionForm((current) => ({ ...current, description: event.target.value }))} />
                </label>
              </div>
              <label className="field-stack">
                <span className="field-label">State</span>
                <label className="checkbox-row">
                  <input type="checkbox" checked={definitionForm.is_active} onChange={(event) => setDefinitionForm((current) => ({ ...current, is_active: event.target.checked }))} />
                  Active
                </label>
              </label>
              <div className="table-toolbar-actions">
                <button type="submit" className="button-inline">Save element</button>
              </div>
            </form>
          </article>

          <article className="card">
            <DataToolbar
              title={`Blocks inside ${selectedDefinition.title}`}
              description="These blocks belong to this element. Templates cannot change them, they only choose the whole element. Drag rows to reorder blocks."
              actions={
                <button type="button" className="button-inline" onClick={() => setShowCreateBlockModal(true)}>
                  New block
                </button>
              }
            />

            <DataTable columns={["Block", "Type", "Subtitle", "Order", "Actions"]}>
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
                      <strong>{blockDisplayName(block)}</strong>
                      <div className="muted">Block #{block.id}</div>
                    </td>
                    <td>{optionLabel(elementTypeOptions, block.element_type_id)}</td>
                    <td>{block.block_title?.trim() ? block.block_title : "Kein Untertitel"}</td>
                    <td><span className="pill">Drag</span></td>
                    <td>
                      <div className="table-actions">
                        <button
                          type="button"
                          className="button-inline button-ghost"
                          onClick={(event) => {
                            event.stopPropagation();
                            setSelectedBlockId(block.id);
                            setBlockForm(blockFormFromBlock(block));
                            setShowEditBlockModal(true);
                          }}
                        >
                          Edit
                        </button>
                        <button type="button" className="button-inline button-danger" onClick={(event) => {
                          event.stopPropagation();
                          void deleteBlock(block.id);
                        }}>Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
            </DataTable>
          </article>
        </>
      ) : null}
      </Modal>

      <Modal
        open={showCreateBlockModal && !!selectedDefinition}
        onClose={() => {
          setShowCreateBlockModal(false);
          setShowCreateBlockHelp(false);
          setMatrixDesignerMode(null);
          if (typePickerMode === "create") {
            setTypePickerMode(null);
          }
        }}
        title="New block"
        description="Add a new block to this element."
        size="wide"
        headerActions={
          <button type="button" className="button-ghost" onClick={() => setShowCreateBlockHelp((current) => !current)}>
            Info
          </button>
        }
      >
        <form className="grid section-stack" onSubmit={createBlock}>
          {showCreateBlockHelp ? (
            <div className="compact-info-pop">
              <strong>Block help</strong>
              <span className="muted">The block title is shown inside the protocol. Fixed blocks should be non-editable. Todo and image blocks can contain multiple entries automatically.</span>
            </div>
          ) : null}
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Block name</span>
              <input value={createBlockForm.title} onChange={(event) => setCreateBlockForm((current) => ({ ...current, title: event.target.value }))} placeholder="Optional, z. B. Besprechungstext" />
              <span className="field-help">Optional. Wenn leer, erscheint der Block direkt unter dem Elementtitel.</span>
            </label>
            <label className="field-stack">
              <span className="field-label">Block subtitle</span>
              <input value={createBlockForm.block_title} onChange={(event) => setCreateBlockForm((current) => ({ ...current, block_title: event.target.value }))} placeholder="e.g. Offene Punkte" />
              <span className="field-help">Optional subtitle shown inside the element in the protocol editor.</span>
            </label>
          </div>
          <label className="field-stack">
            <span className="field-label">Description</span>
            <input value={createBlockForm.description} onChange={(event) => setCreateBlockForm((current) => ({ ...current, description: event.target.value }))} placeholder="Optional note for editors" />
          </label>
          <label className="field-stack">
            <span className="field-label">Default or fixed content</span>
            <textarea
              rows={6}
              value={createBlockForm.default_content}
              onChange={(event) => setCreateBlockForm((current) => ({ ...current, default_content: event.target.value }))}
              placeholder="Used for static text or initial text"
            />
            <span className="field-help">For static text blocks this becomes the fixed content. For normal text blocks it is the initial text.</span>
          </label>
          <div className="field-stack">
            <label className="field-stack">
              <span className="field-label">Block type</span>
              <button type="button" className="button-ghost type-picker-button" onClick={() => setTypePickerMode("create")}>
                Select
              </button>
              <span className="field-help">{optionDescription(elementTypeOptions, createBlockForm.element_type_id)}</span>
            </label>
          </div>
          <article className="card grid">
            <DataToolbar
              title="Wiederholung"
              description="Lege fest, ob dieser Block einmalig erscheint oder sich pro Termin bzw. Todo wiederholt."
            />
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
                      <span className="field-label">Tag filter</span>
                    <input
                      value={createBlockForm.event_tag_filter}
                      onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_tag_filter: event.target.value }))}
                      placeholder="z. B. Scharanlass"
                      list="element-event-tag-suggestions"
                    />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">Titel filter</span>
                    <input value={createBlockForm.event_title_filter} onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_title_filter: event.target.value }))} placeholder="enthaelt..." />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">Beschreibungsfilter</span>
                    <input value={createBlockForm.event_description_filter} onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_description_filter: event.target.value }))} placeholder="enthaelt..." />
                  </label>
                </div>
                <div className="three-col">
                  <label className="field-stack">
                    <span className="field-label">Datumsmodus</span>
                    <select value={createBlockForm.event_date_mode} onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_date_mode: event.target.value as "relative_window" | "all_future" }))}>
                      <option value="relative_window">Relatives Fenster</option>
                      <option value="all_future">Alle künftigen Termine</option>
                    </select>
                  </label>
                  <label className="field-stack">
                    <span className="field-label">Fenster Start (Tage)</span>
                    <input type="number" value={createBlockForm.event_window_start_days} onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_window_start_days: event.target.value }))} />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">Fenster Ende (Tage)</span>
                    <input type="number" value={createBlockForm.event_window_end_days} onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_window_end_days: event.target.value }))} />
                  </label>
                </div>
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
                    <span className="field-label">Todo-Blocktitel</span>
                    <input value={createBlockForm.todo_block_title_filter} onChange={(event) => setCreateBlockForm((current) => ({ ...current, todo_block_title_filter: event.target.value }))} placeholder="enthaelt..." />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">Todo-Text</span>
                    <input value={createBlockForm.todo_task_filter} onChange={(event) => setCreateBlockForm((current) => ({ ...current, todo_task_filter: event.target.value }))} placeholder="enthaelt..." />
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
          </article>
          {createBlockForm.element_type_id === "7" ? (
            <div className="grid">
              <div className="three-col">
              <label className="field-stack">
                <span className="field-label">Termin-Tagfilter</span>
                  <input
                    value={createBlockForm.event_tag_filter}
                    onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_tag_filter: event.target.value }))}
                    placeholder="e.g. Sitzung"
                    list="element-event-tag-suggestions"
                  />
                </label>
              <label className="checkbox-row"><input type="checkbox" checked={createBlockForm.event_only_from_protocol_date} onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_only_from_protocol_date: event.target.checked }))} />Nur Termine ab Protokolldatum anzeigen</label>
              <label className="checkbox-row"><input type="checkbox" checked={createBlockForm.event_gray_past} onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_gray_past: event.target.checked }))} />Vergangene Termine ausgegraut darstellen</label>
              <label className="checkbox-row"><input type="checkbox" checked={createBlockForm.event_allow_end_date} onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_allow_end_date: event.target.checked }))} />Mehrtägige Termine erlauben</label>
              </div>
              <div className="three-col">
                <label className="checkbox-row"><input type="checkbox" checked={createBlockForm.event_show_date} onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_show_date: event.target.checked }))} />Spalte Datum</label>
                <label className="checkbox-row"><input type="checkbox" checked={createBlockForm.event_show_tag} onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_show_tag: event.target.checked }))} />Spalte Tag</label>
                <label className="checkbox-row"><input type="checkbox" checked={createBlockForm.event_show_title} onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_show_title: event.target.checked }))} />Spalte Titel</label>
                <label className="checkbox-row"><input type="checkbox" checked={createBlockForm.event_show_description} onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_show_description: event.target.checked }))} />Spalte Beschreibung</label>
                <label className="checkbox-row"><input type="checkbox" checked={createBlockForm.event_show_participant_count} onChange={(event) => setCreateBlockForm((current) => ({ ...current, event_show_participant_count: event.target.checked }))} />Spalte Teilnehmerzahl</label>
              </div>
            </div>
          ) : null}
          {createBlockForm.element_type_id === "6" ? (
            <div className="card grid">
              <DataToolbar
                title="Table rows"
                description={
                  createBlockForm.linked_list_id
                    ? "Diese Tabelle ist direkt mit einer globalen Liste gekoppelt."
                    : "Define the fixed left column and the value type for each row."
                }
                actions={
                  createBlockForm.linked_list_id ? null : (
                    <button
                      type="button"
                      className="button-inline"
                      onClick={() =>
                        setCreateBlockForm((current) => ({
                          ...current,
                          table_fields: [
                            ...current.table_fields,
                            defaultFieldRow(nextTableFieldId(current.table_fields)),
                          ],
                        }))
                      }
                    >
                      Add row
                    </button>
                  )
                }
              />
              <label className="field-stack">
                <span className="field-label">Gekoppelte Liste</span>
                <select
                  value={createBlockForm.linked_list_id}
                  onChange={(event) =>
                    setCreateBlockForm((current) => ({
                      ...current,
                      linked_list_id: event.target.value,
                    }))
                  }
                >
                  <option value="">Keine globale Liste</option>
                  {listOptions.map((listDefinition) => (
                    <option key={`create-linked-list-${listDefinition.id}`} value={listDefinition.id}>
                      {listDefinition.name}
                    </option>
                  ))}
                </select>
                <span className="field-help">
                  Wenn eine Liste gewaehlt ist, zeigt der Tabellenblock spaeter genau diese globale Liste im Protokoll an.
                </span>
              </label>
              {createLinkedList ? (
                <div className="card grid">
                  <div className="eyebrow">Gekoppelte Liste</div>
                  <strong>{createLinkedList.name}</strong>
                  <div className="status-row">
                    <span className="pill">
                      {createLinkedList.column_one_title} · {valueTypeLabel(createLinkedList.column_one_value_type)}
                    </span>
                    <span className="pill">
                      {createLinkedList.column_two_title} · {valueTypeLabel(createLinkedList.column_two_value_type)}
                    </span>
                  </div>
                  <p className="muted">
                    Inhalt und Zeilen dieser Tabelle kommen aus `Datensaetze &gt; Listen`. Die lokale Tabellenkonfiguration wird in diesem Fall ignoriert.
                  </p>
                </div>
              ) : (
                <>
                <div className="two-col">
                  <label className="field-stack">
                    <span className="field-label">Linke Spaltenueberschrift</span>
                    <input value={createBlockForm.left_column_heading} onChange={(event) => setCreateBlockForm((current) => ({ ...current, left_column_heading: event.target.value }))} placeholder="Leer lassen fuer keine Ueberschrift" />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">Rechte Spaltenueberschrift</span>
                    <input value={createBlockForm.value_column_heading} onChange={(event) => setCreateBlockForm((current) => ({ ...current, value_column_heading: event.target.value }))} placeholder="Leer lassen fuer keine Ueberschrift" />
                  </label>
                </div>
              {(createBlockForm.table_fields.length ? createBlockForm.table_fields : [defaultFieldRow("1")]).map((field, index) => (
                <div className="grid" key={`create-table-field-${field.id}`}>
                <div className="four-col">
                  <label className="field-stack">
                    <span className="field-label">Left column label</span>
                    <input
                      value={field.label}
                      onChange={(event) =>
                        setCreateBlockForm((current) => ({
                          ...current,
                          table_fields: (current.table_fields.length ? current.table_fields : [defaultFieldRow("1")]).map((entry, entryIndex) =>
                            entryIndex === index ? { ...entry, label: event.target.value } : entry
                          ),
                        }))
                      }
                      placeholder="e.g. Verantwortlich"
                    />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">Datentyp</span>
                    <select
                      value={field.row_type}
                      onChange={(event) =>
                        setCreateBlockForm((current) => ({
                          ...current,
                          table_fields: (current.table_fields.length ? current.table_fields : [defaultFieldRow("1")]).map((entry, entryIndex) =>
                            entryIndex === index
                              ? {
                                  ...entry,
                                  row_type: event.target.value,
                                }
                              : entry
                          ),
                        }))
                      }
                    >
                      {valueTypeChoices("6").map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                        ))}
                    </select>
                  </label>
                  {renderTypedInitialValueEditor(field, (patch) =>
                    setCreateBlockForm((current) => ({
                      ...current,
                      table_fields: (current.table_fields.length ? current.table_fields : [defaultFieldRow("1")]).map((entry, entryIndex) =>
                        entryIndex === index ? { ...entry, ...patch } : entry
                      ),
                    }))
                  )}
                  <div className="table-toolbar-actions align-end">
                    <button
                      type="button"
                      className="button-inline button-danger"
                      onClick={() =>
                        setCreateBlockForm((current) => ({
                          ...current,
                          table_fields: current.table_fields.filter((entry) => entry.id !== field.id),
                        }))
                      }
                    >
                      Remove
                    </button>
                  </div>
                </div>
                </div>
              ))}
                </>
              )}
            </div>
          ) : null}
          {createBlockForm.element_type_id === "11" ? (
            <div className="card grid">
              <DataToolbar
                title="Matrix"
                description="Lege Zeilen und Spalten in einem eigenen Designer an. Danach kannst du pro Zeile den Datentyp und pro Spalte den Terminfilter setzen."
                actions={
                  <button type="button" className="button-inline" onClick={() => openMatrixDesigner("create")}>
                    Matrix konfigurieren
                  </button>
                }
              />
              <div className="status-row">
                <span className="pill">{createBlockForm.matrix_columns.length} Spalten</span>
                <span className="pill">{createBlockForm.table_fields.length} Zeilen</span>
                <span className="pill">{createBlockForm.matrix_mode === "auto" ? "Automatisch" : "Manuell"}</span>
              </div>
              {createBlockForm.matrix_columns.length || createBlockForm.table_fields.length ? (
                <div className="table-pill-wrap">
                  {createBlockForm.matrix_columns.map((column) => (
                    <span key={`create-matrix-column-pill-${column.id}`} className="pill">
                      {column.title || "Ohne Spaltentitel"}
                    </span>
                  ))}
                  {createBlockForm.table_fields.map((field) => (
                    <span key={`create-matrix-row-pill-${field.id}`} className="pill">
                      {field.label || "Ohne Zeilenname"} · {matrixEmbeddedBlockLabel(field.row_type) !== "Wert" ? matrixEmbeddedBlockLabel(field.row_type) : valueTypeLabel(field.row_type as any)}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="muted">Noch keine Matrix angelegt. Oeffne den Designer und fuege zuerst Spalten und Zeilen hinzu.</p>
              )}
            </div>
          ) : null}
          <div className="three-col">
            <label className="checkbox-row"><input type="checkbox" checked={createBlockForm.is_editable} onChange={(event) => setCreateBlockForm((current) => ({ ...current, is_editable: event.target.checked }))} />Editable in protocol</label>
            <label className="checkbox-row"><input type="checkbox" checked={createBlockForm.title_as_subtitle} onChange={(event) => setCreateBlockForm((current) => ({ ...current, title_as_subtitle: event.target.checked }))} />Blocktitel im PDF als Untertitel rendern</label>
            <label className="checkbox-row"><input type="checkbox" checked={createBlockForm.copy_from_last_protocol} onChange={(event) => setCreateBlockForm((current) => ({ ...current, copy_from_last_protocol: event.target.checked }))} />Daten aus letzter Sitzung übernehmen</label>
          </div>
          <div className="four-col">
            <label className="checkbox-row"><input type="checkbox" checked={createBlockForm.is_visible} onChange={(event) => setCreateBlockForm((current) => ({ ...current, is_visible: event.target.checked }))} />Visible</label>
            <label className="checkbox-row"><input type="checkbox" checked={createBlockForm.export_visible} onChange={(event) => setCreateBlockForm((current) => ({ ...current, export_visible: event.target.checked }))} />Export visible</label>
          </div>
          <div className="table-toolbar-actions">
            <button type="submit" className="button-inline">Add block</button>
          </div>
        </form>
      </Modal>

      <Modal
        open={showEditBlockModal && !!selectedBlock}
        onClose={() => {
          setShowEditBlockModal(false);
          setShowEditBlockHelp(false);
          setMatrixDesignerMode(null);
          if (typePickerMode === "edit") {
            setTypePickerMode(null);
          }
        }}
        title={selectedBlock ? `Edit block: ${blockDisplayName(selectedBlock)}` : "Edit block"}
        description="Adjust the selected block without leaving the block overview."
        size="wide"
        headerActions={
          <button type="button" className="button-ghost" onClick={() => setShowEditBlockHelp((current) => !current)}>
            Info
          </button>
        }
      >
        {selectedBlock ? (
          <form className="grid section-stack" onSubmit={updateBlock}>
            {showEditBlockHelp ? (
              <div className="compact-info-pop">
                <strong>Block help</strong>
                <span className="muted">Enable the carry option if this block should prefill text or todos from the most recent earlier protocol that used the same element.</span>
              </div>
            ) : null}
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">Block name</span>
                <input value={blockForm.title} onChange={(event) => setBlockForm((current) => ({ ...current, title: event.target.value }))} placeholder="Optional, z. B. Besprechungstext" />
                <span className="field-help">Leer lassen, wenn der Block keine eigene Zwischenueberschrift haben soll.</span>
              </label>
              <label className="field-stack">
                <span className="field-label">Block subtitle</span>
                <input value={blockForm.block_title} onChange={(event) => setBlockForm((current) => ({ ...current, block_title: event.target.value }))} placeholder="Optional subtitle" />
              </label>
            </div>
            <label className="field-stack">
              <span className="field-label">Description</span>
              <input value={blockForm.description} onChange={(event) => setBlockForm((current) => ({ ...current, description: event.target.value }))} />
            </label>
            <label className="field-stack">
              <span className="field-label">Default or fixed content</span>
              <textarea
                rows={6}
                value={blockForm.default_content}
                onChange={(event) => setBlockForm((current) => ({ ...current, default_content: event.target.value }))}
              />
            </label>
            <div className="field-stack">
              <label className="field-stack">
                <span className="field-label">Block type</span>
                <button type="button" className="button-ghost type-picker-button" onClick={() => setTypePickerMode("edit")}>
                  Select
                </button>
                <span className="field-help">{optionDescription(elementTypeOptions, blockForm.element_type_id)}</span>
              </label>
            </div>
            <article className="card grid">
              <DataToolbar
                title="Wiederholung"
                description="Die Wiederholung sitzt jetzt direkt auf dem Block und nicht mehr auf dem Template-Element."
              />
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
                      <span className="field-label">Tag filter</span>
                      <input
                        value={blockForm.event_tag_filter}
                        onChange={(event) => setBlockForm((current) => ({ ...current, event_tag_filter: event.target.value }))}
                        placeholder="z. B. Scharanlass"
                        list="element-event-tag-suggestions"
                      />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">Titel filter</span>
                      <input value={blockForm.event_title_filter} onChange={(event) => setBlockForm((current) => ({ ...current, event_title_filter: event.target.value }))} placeholder="enthaelt..." />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">Beschreibungsfilter</span>
                      <input value={blockForm.event_description_filter} onChange={(event) => setBlockForm((current) => ({ ...current, event_description_filter: event.target.value }))} placeholder="enthaelt..." />
                    </label>
                  </div>
                  <div className="three-col">
                    <label className="field-stack">
                      <span className="field-label">Datumsmodus</span>
                      <select value={blockForm.event_date_mode} onChange={(event) => setBlockForm((current) => ({ ...current, event_date_mode: event.target.value as "relative_window" | "all_future" }))}>
                        <option value="relative_window">Relatives Fenster</option>
                        <option value="all_future">Alle künftigen Termine</option>
                      </select>
                    </label>
                    <label className="field-stack">
                      <span className="field-label">Fenster Start (Tage)</span>
                      <input type="number" value={blockForm.event_window_start_days} onChange={(event) => setBlockForm((current) => ({ ...current, event_window_start_days: event.target.value }))} />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">Fenster Ende (Tage)</span>
                      <input type="number" value={blockForm.event_window_end_days} onChange={(event) => setBlockForm((current) => ({ ...current, event_window_end_days: event.target.value }))} />
                    </label>
                  </div>
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
                      <span className="field-label">Todo-Blocktitel</span>
                      <input value={blockForm.todo_block_title_filter} onChange={(event) => setBlockForm((current) => ({ ...current, todo_block_title_filter: event.target.value }))} placeholder="enthaelt..." />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">Todo-Text</span>
                      <input value={blockForm.todo_task_filter} onChange={(event) => setBlockForm((current) => ({ ...current, todo_task_filter: event.target.value }))} placeholder="enthaelt..." />
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
            </article>
            {blockForm.element_type_id === "7" ? (
              <div className="grid">
                <div className="three-col">
                <label className="field-stack">
                  <span className="field-label">Termin-Tagfilter</span>
                  <input
                    value={blockForm.event_tag_filter}
                    onChange={(event) => setBlockForm((current) => ({ ...current, event_tag_filter: event.target.value }))}
                    placeholder="e.g. Sitzung"
                    list="element-event-tag-suggestions"
                  />
                </label>
                <label className="checkbox-row"><input type="checkbox" checked={blockForm.event_only_from_protocol_date} onChange={(event) => setBlockForm((current) => ({ ...current, event_only_from_protocol_date: event.target.checked }))} />Nur Termine ab Protokolldatum anzeigen</label>
                <label className="checkbox-row"><input type="checkbox" checked={blockForm.event_gray_past} onChange={(event) => setBlockForm((current) => ({ ...current, event_gray_past: event.target.checked }))} />Vergangene Termine ausgegraut darstellen</label>
                <label className="checkbox-row"><input type="checkbox" checked={blockForm.event_allow_end_date} onChange={(event) => setBlockForm((current) => ({ ...current, event_allow_end_date: event.target.checked }))} />Mehrtägige Termine erlauben</label>
                </div>
                <div className="three-col">
                  <label className="checkbox-row"><input type="checkbox" checked={blockForm.event_show_date} onChange={(event) => setBlockForm((current) => ({ ...current, event_show_date: event.target.checked }))} />Spalte Datum</label>
                  <label className="checkbox-row"><input type="checkbox" checked={blockForm.event_show_tag} onChange={(event) => setBlockForm((current) => ({ ...current, event_show_tag: event.target.checked }))} />Spalte Tag</label>
                  <label className="checkbox-row"><input type="checkbox" checked={blockForm.event_show_title} onChange={(event) => setBlockForm((current) => ({ ...current, event_show_title: event.target.checked }))} />Spalte Titel</label>
                  <label className="checkbox-row"><input type="checkbox" checked={blockForm.event_show_description} onChange={(event) => setBlockForm((current) => ({ ...current, event_show_description: event.target.checked }))} />Spalte Beschreibung</label>
                  <label className="checkbox-row"><input type="checkbox" checked={blockForm.event_show_participant_count} onChange={(event) => setBlockForm((current) => ({ ...current, event_show_participant_count: event.target.checked }))} />Spalte Teilnehmerzahl</label>
                </div>
              </div>
            ) : null}
            {blockForm.element_type_id === "6" ? (
              <div className="card grid">
                <DataToolbar
                  title="Table rows"
                  description={
                    blockForm.linked_list_id
                      ? "Diese Tabelle ist direkt mit einer globalen Liste gekoppelt."
                      : "Define the fixed left column and the value type for each row."
                  }
                  actions={
                    blockForm.linked_list_id ? null : (
                      <button
                        type="button"
                        className="button-inline"
                        onClick={() =>
                          setBlockForm((current) => ({
                            ...current,
                            table_fields: [
                              ...current.table_fields,
                              defaultFieldRow(nextTableFieldId(current.table_fields)),
                            ],
                          }))
                        }
                      >
                        Add row
                      </button>
                    )
                  }
                />
                <label className="field-stack">
                  <span className="field-label">Gekoppelte Liste</span>
                  <select
                    value={blockForm.linked_list_id}
                    onChange={(event) =>
                      setBlockForm((current) => ({
                        ...current,
                        linked_list_id: event.target.value,
                      }))
                    }
                  >
                    <option value="">Keine globale Liste</option>
                    {listOptions.map((listDefinition) => (
                      <option key={`edit-linked-list-${listDefinition.id}`} value={listDefinition.id}>
                        {listDefinition.name}
                      </option>
                    ))}
                  </select>
                  <span className="field-help">
                    Wenn eine Liste gewaehlt ist, zeigt der Tabellenblock spaeter genau diese globale Liste im Protokoll an.
                  </span>
                </label>
                {editLinkedList ? (
                  <div className="card grid">
                    <div className="eyebrow">Gekoppelte Liste</div>
                    <strong>{editLinkedList.name}</strong>
                    <div className="status-row">
                      <span className="pill">
                        {editLinkedList.column_one_title} · {valueTypeLabel(editLinkedList.column_one_value_type)}
                      </span>
                      <span className="pill">
                        {editLinkedList.column_two_title} · {valueTypeLabel(editLinkedList.column_two_value_type)}
                      </span>
                    </div>
                    <p className="muted">
                      Inhalt und Zeilen dieser Tabelle kommen aus `Datensaetze &gt; Listen`. Die lokale Tabellenkonfiguration wird in diesem Fall ignoriert.
                    </p>
                  </div>
                ) : (
                  <>
                    <div className="two-col">
                      <label className="field-stack">
                        <span className="field-label">Linke Spaltenueberschrift</span>
                        <input
                          value={blockForm.left_column_heading}
                          onChange={(event) => setBlockForm((current) => ({ ...current, left_column_heading: event.target.value }))}
                          placeholder="Leer lassen fuer keine Ueberschrift"
                        />
                      </label>
                      <label className="field-stack">
                        <span className="field-label">Rechte Spaltenueberschrift</span>
                        <input
                          value={blockForm.value_column_heading}
                          onChange={(event) => setBlockForm((current) => ({ ...current, value_column_heading: event.target.value }))}
                          placeholder="Leer lassen fuer keine Ueberschrift"
                        />
                      </label>
                    </div>
                {blockForm.table_fields.map((field, index) => (
                <div className="grid" key={`edit-table-field-${field.id}`}>
                <div className="four-col">
                  <label className="field-stack">
                    <span className="field-label">Left column label</span>
                      <input
                        value={field.label}
                        onChange={(event) =>
                          setBlockForm((current) => ({
                            ...current,
                            table_fields: current.table_fields.map((entry, entryIndex) =>
                              entryIndex === index ? { ...entry, label: event.target.value } : entry
                            ),
                          }))
                        }
                        placeholder="e.g. Verantwortlich"
                      />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">Datentyp</span>
                      <select
                        value={field.row_type}
                        onChange={(event) =>
                          setBlockForm((current) => ({
                            ...current,
                            table_fields: current.table_fields.map((entry, entryIndex) =>
                              entryIndex === index
                                ? {
                                    ...entry,
                                    row_type: event.target.value,
                                  }
                                : entry
                            ),
                          }))
                        }
                      >
                        {valueTypeChoices("6").map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                    </select>
                  </label>
                  {renderTypedInitialValueEditor(field, (patch) =>
                    setBlockForm((current) => ({
                      ...current,
                      table_fields: current.table_fields.map((entry, entryIndex) =>
                        entryIndex === index ? { ...entry, ...patch } : entry
                      ),
                    }))
                  )}
                  <div className="table-toolbar-actions align-end">
                      <button
                        type="button"
                        className="button-inline button-danger"
                        onClick={() =>
                          setBlockForm((current) => ({
                            ...current,
                            table_fields: current.table_fields.filter((entry) => entry.id !== field.id),
                          }))
                        }
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                </div>
                ))}
                  </>
                )}
              </div>
            ) : null}
            {blockForm.element_type_id === "11" ? (
              <div className="card grid">
                <DataToolbar
                  title="Matrix"
                  description="Oeffne den Matrix-Designer, um Spalten, Zeilen und Datentypen direkt visuell zu konfigurieren."
                  actions={
                    <button type="button" className="button-inline" onClick={() => openMatrixDesigner("edit")}>
                      Matrix konfigurieren
                    </button>
                  }
                />
                <div className="status-row">
                  <span className="pill">{blockForm.matrix_columns.length} Spalten</span>
                  <span className="pill">{blockForm.table_fields.length} Zeilen</span>
                  <span className="pill">{blockForm.matrix_mode === "auto" ? "Automatisch" : "Manuell"}</span>
                </div>
                {blockForm.matrix_columns.length || blockForm.table_fields.length ? (
                  <div className="table-pill-wrap">
                    {blockForm.matrix_columns.map((column) => (
                      <span key={`edit-matrix-column-pill-${column.id}`} className="pill">
                        {column.title || "Ohne Spaltentitel"}
                      </span>
                    ))}
                    {blockForm.table_fields.map((field) => (
                      <span key={`edit-matrix-row-pill-${field.id}`} className="pill">
                        {field.label || "Ohne Zeilenname"} · {matrixEmbeddedBlockLabel(field.row_type) !== "Wert" ? matrixEmbeddedBlockLabel(field.row_type) : valueTypeLabel(field.row_type as any)}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="muted">Noch keine Matrix angelegt. Oeffne den Designer und fuege zuerst Spalten und Zeilen hinzu.</p>
                )}
              </div>
            ) : null}
            <div className="three-col">
              <label className="checkbox-row"><input type="checkbox" checked={blockForm.is_editable} onChange={(event) => setBlockForm((current) => ({ ...current, is_editable: event.target.checked }))} />Editable in protocol</label>
              <label className="checkbox-row"><input type="checkbox" checked={blockForm.title_as_subtitle} onChange={(event) => setBlockForm((current) => ({ ...current, title_as_subtitle: event.target.checked }))} />Blocktitel im PDF als Untertitel rendern</label>
              <label className="checkbox-row"><input type="checkbox" checked={blockForm.copy_from_last_protocol} onChange={(event) => setBlockForm((current) => ({ ...current, copy_from_last_protocol: event.target.checked }))} />Daten aus letzter Sitzung übernehmen</label>
            </div>
            <div className="four-col">
              <label className="checkbox-row"><input type="checkbox" checked={blockForm.is_visible} onChange={(event) => setBlockForm((current) => ({ ...current, is_visible: event.target.checked }))} />Visible</label>
              <label className="checkbox-row"><input type="checkbox" checked={blockForm.export_visible} onChange={(event) => setBlockForm((current) => ({ ...current, export_visible: event.target.checked }))} />Export visible</label>
            </div>
            <div className="table-toolbar-actions">
              <button type="submit" className="button-inline">Save block</button>
            </div>
          </form>
        ) : null}
      </Modal>

      <Modal
        open={typePickerMode !== null}
        onClose={() => setTypePickerMode(null)}
        title="Choose block type"
        description="Pick the kind of block you want to add."
        size="fullscreen"
      >
        <div className="block-type-grid">
          {elementTypeOptions.map((option) => {
            const activeType = typePickerMode === "create" ? createBlockForm.element_type_id : blockForm.element_type_id;
            return (
              <button
                key={option.value}
                type="button"
                className={`block-type-card${activeType === option.value ? " block-type-card-active" : ""}`}
                onClick={() => applyBlockType(option.value, typePickerMode ?? "create")}
              >
                {renderBlockTypePreview(option.value)}
                <div className="block-type-summary">
                  <strong>{option.label}</strong>
                  <span className="muted">{option.description}</span>
                </div>
              </button>
            );
          })}
        </div>
      </Modal>

      <Modal
        open={matrixDesignerMode !== null && !!matrixDesignerForm}
        onClose={() => {
          void closeMatrixDesigner();
        }}
        title="Matrix konfigurieren"
        description="Füge Spalten und Zeilen direkt als Matrix hinzu. Klick auf eine Zeile oder eine Zelle, um Datentypen und Inhalte zu setzen."
        size="fullscreen"
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
                  <span className="field-label" style={{ whiteSpace: "nowrap" }}>Modus</span>
                  <select
                    value={matrixDesignerForm.matrix_mode}
                    onChange={(e) => updateMatrixDesignerForm((c) => ({ ...c, matrix_mode: e.target.value as "manual" | "auto" }))}
                    style={{ minWidth: 100 }}
                  >
                    <option value="manual">Manuell</option>
                    <option value="auto">Automatisch</option>
                  </select>
                  {matrixDesignerForm.matrix_mode === "auto" ? (
                    <>
                      <span className="field-label" style={{ whiteSpace: "nowrap" }}>Quelle</span>
                      <select
                        value={matrixDesignerForm.auto_source_type}
                        onChange={(e) => updateMatrixDesignerForm((c) => ({ ...c, auto_source_type: e.target.value as "" | "participants" | "events" | "list" }))}
                        style={{ minWidth: 130 }}
                      >
                        <option value="">Bitte wählen...</option>
                        <option value="participants">Teilnehmer</option>
                        <option value="events">Termine</option>
                        <option value="list">Liste</option>
                      </select>
                      {matrixDesignerForm.auto_source_type === "events" ? (
                        <input
                          value={matrixDesignerForm.auto_source_event_tag}
                          onChange={(e) => updateMatrixDesignerForm((c) => ({ ...c, auto_source_event_tag: e.target.value }))}
                          list="element-event-tag-suggestions"
                          placeholder="Tag-Filter (optional)"
                          style={{ minWidth: 160 }}
                        />
                      ) : null}
                      {matrixDesignerForm.auto_source_type === "list" ? (
                        <select
                          value={matrixDesignerForm.auto_source_list_id}
                          onChange={(e) => updateMatrixDesignerForm((c) => ({ ...c, auto_source_list_id: e.target.value }))}
                          style={{ minWidth: 160 }}
                        >
                          <option value="">Liste wählen...</option>
                          {listOptions.map((list) => (
                            <option key={`col-src-list-${list.id}`} value={list.id}>{list.name}</option>
                          ))}
                        </select>
                      ) : null}
                    </>
                  ) : null}
                </div>
              </div>
              <div className="matrix-designer-strip-actions">
                <button
                  type="button"
                  className="button-inline"
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
                    className="button-inline"
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
                    className="button-inline"
                    disabled={matrixPreviewLoading}
                    onClick={() => { void loadMatrixPreview(); }}
                  >
                    {matrixPreviewLoading ? "Lädt..." : matrixPreviewColumns ? "Aktualisieren" : "Vorschau"}
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
                  <div className="matrix-designer-corner">Matrix</div>
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
                        <span className="muted">{matrixEmbeddedBlockLabel(row.row_type) !== "Wert" ? matrixEmbeddedBlockLabel(row.row_type) : valueTypeLabel(row.row_type as any)}</span>
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
                            {matrixEmbeddedBlockLabel(row.row_type) !== "Wert"
                              ? matrixEmbeddedBlockLabel(row.row_type)
                              : row.row_type === "events"
                              ? (column.event_tag_filter || (row.row_config?.event_tag_filter as string | undefined) || "Alle Termine")
                              : valueTypeLabel(row.row_type as any)}
                          </span>
                        </button>
                      ))}
                      {matrixDesignerForm.matrix_mode === "auto" && matrixPreviewColumns && matrixPreviewColumns.map((col) => (
                        <div key={`pv-${row.id}-${col.id}`} className="matrix-designer-cell matrix-designer-cell-preview">
                          <span className="muted">{row.auto_source_field || valueTypeLabel(row.row_type as any)}</span>
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
                        <div className="eyebrow">Zeile</div>
                        <strong>{selectedMatrixRow.label || "Neue Zeile"}</strong>
                      </div>
                      <button
                        type="button"
                        className="button-inline button-danger"
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
                      <span className="field-label">Zeilenbezeichnung</span>
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
                        placeholder="z. B. Leiter"
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
                      <span className="field-label">Zeilentyp</span>
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
                        <optgroup label="Einfache Werte">
                          {valueTypeChoices("11").map((option) => (
                            <option key={`matrix-row-type-${option.value}`} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </optgroup>
                        <optgroup label="Eingebettete Blöcke">
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
                            <span className="field-label">Termin-Tagfilter</span>
                            <input
                              value={String(selectedMatrixEmbeddedConfig.event_tag_filter ?? "")}
                              onChange={(event) => updateSelectedMatrixRowConfig({ event_tag_filter: event.target.value })}
                              list="element-event-tag-suggestions"
                              placeholder="Leer fuer alle Tags"
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
                          <span className="field-label">Termin-Titelfilter</span>
                          <input
                            value={String(selectedMatrixRow.row_config?.event_title_filter ?? "")}
                            onChange={(event) => updateSelectedMatrixRowConfig({ event_title_filter: event.target.value })}
                            placeholder="enthaelt..."
                          />
                        </label>
                        <label className="field-stack">
                          <span className="field-label">Termin-Tagfilter</span>
                          <input
                            value={String(selectedMatrixRow.row_config?.event_tag_filter ?? "")}
                            onChange={(event) => updateSelectedMatrixRowConfig({ event_tag_filter: event.target.value })}
                            list="element-event-tag-suggestions"
                            placeholder="Leer fuer alle Tags"
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
                        <div className="eyebrow">Spalten-Platzhalter</div>
                        <label className="field-stack">
                          <span className="field-label">
                            {matrixDesignerForm.auto_source_type === "participants" ? "Wert aus Teilnehmer" :
                             matrixDesignerForm.auto_source_type === "events" ? "Wert aus Termin" :
                             "Wert aus Liste"}
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
                            <option value="">Kein Platzhalter</option>
                            {matrixDesignerForm.auto_source_type === "participants" ? (
                              <>
                                <option value="display_name">Anzeigename</option>
                                <option value="first_name">Vorname</option>
                                <option value="last_name">Nachname</option>
                                <option value="email">E-Mail</option>
                              </>
                            ) : matrixDesignerForm.auto_source_type === "events" ? (
                              <>
                                <option value="title">Titel</option>
                                <option value="event_date">Datum</option>
                                <option value="tag">Tag</option>
                                <option value="participant_count">Teilnehmerzahl</option>
                              </>
                            ) : (
                              <>
                                <option value="column_one">Spalte 1</option>
                                <option value="column_two">Spalte 2</option>
                              </>
                            )}
                          </select>
                          <span className="field-help">Welcher Wert soll in dieser Zeile als Vorbelegung erscheinen?</span>
                        </label>
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <p className="muted">Zeile auswählen</p>
                )}

                {matrixDesignerForm.matrix_mode !== "auto" && selectedMatrixColumn ? (
                  <div className="matrix-designer-panel-section">
                    <div className="matrix-designer-panel-header">
                      <div>
                        <div className="eyebrow">Spalte</div>
                        <strong>{selectedMatrixColumn.title || "Neue Spalte"}</strong>
                      </div>
                      <button
                        type="button"
                        className="button-inline button-danger"
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
                      <span className="field-label">Spaltentitel</span>
                      <input
                        value={selectedMatrixColumn.title}
                        onChange={(e) => updateMatrixDesignerForm((c) => ({ ...c, matrix_columns: c.matrix_columns.map((col) => col.id === selectedMatrixColumn.id ? { ...col, title: e.target.value } : col) }))}
                        placeholder="z. B. Nussknacker"
                      />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">Platzhalter (im Protokoll)</span>
                      <input
                        value={(selectedMatrixColumn as any).title_placeholder ?? ""}
                        onChange={(e) => updateMatrixDesignerForm((c) => ({ ...c, matrix_columns: c.matrix_columns.map((col) => col.id === selectedMatrixColumn.id ? { ...col, title_placeholder: e.target.value } : col) }))}
                        placeholder="z. B. Name des Teilnehmers"
                      />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">Tagfilter für Terminzeilen</span>
                      <input
                        value={selectedMatrixColumn.event_tag_filter ?? ""}
                        onChange={(e) => updateMatrixDesignerForm((c) => ({ ...c, matrix_columns: c.matrix_columns.map((col) => col.id === selectedMatrixColumn.id ? { ...col, event_tag_filter: e.target.value } : col) }))}
                        list="element-event-tag-suggestions"
                        placeholder="Optional"
                      />
                    </label>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        ) : null}
      </Modal>

      <datalist id="element-event-tag-suggestions">
        {knownEventTags.map((tag) => (
          <option key={tag} value={tag} />
        ))}
      </datalist>
    </div>
  );
}
