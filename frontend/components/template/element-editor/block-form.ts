// Formularzustand eines Blocks im Element-Editor und Umwandlung von/zu ElementDefinitionBlock.
//
// Früher hielt ein flaches Objekt mit rund 80 Feldern die Optionen aller Typen, und
// blockPayload schrieb sie bei jedem Typ in configuration_json. Jetzt liegt die Konfiguration
// in `config` direkt im gespeicherten Schema (siehe backend/app/services/element_config.py);
// Vorgaben und erlaubte Wiederholungen kommen aus der Elementtyp-Registry.
import { defaultEventFilter, normalizeEventFilter, type EventFilter } from "@/lib/element-types/event-filter";
import { elementType, elementTypeCode, type ElementTypeCode, type RepeatSource } from "@/lib/element-types/registry";
import type { ElementDefinitionBlock } from "@/types/api";

export type BlockConfig = Record<string, any>;

export type TableRow = {
  id: string;
  label: string;
  /** Einfacher Werttyp ("text", "participant", …) oder id eines eingebetteten Elementtyps ("7"). */
  row_type: string;
  locked_in_protocol: boolean;
  row_config: BlockConfig;
  auto_source_field: string | null;
  template_value: string;
  template_participant_id: string | null;
  template_participant_ids: string[];
  template_event_id: string | null;
};

export type MatrixColumn = {
  id: string;
  title: string;
  event_tag_filter: string;
  title_placeholder: string;
};

export type BlockForm = {
  id: number;
  title: string;
  block_title: string;
  /** Hinweis für Protokollführer, erscheint im Protokoll unter dem Block. */
  description: string;
  default_content: string;
  element_type_id: number;
  is_editable: boolean;
  export_visible: boolean;
  is_visible: boolean;
  copy_from_last_protocol: boolean;
  title_as_subtitle: boolean;
  sort_index: number;
  config: BlockConfig;
};

export type BehaviorField = "is_editable" | "export_visible" | "is_visible" | "copy_from_last_protocol" | "title_as_subtitle";

export const SIMPLE_ROW_TYPES = ["text", "participant", "participants", "event", "events", "list_entry"] as const;
export type SimpleRowType = (typeof SIMPLE_ROW_TYPES)[number];

export function isSimpleRowType(rowType: string): rowType is SimpleRowType {
  return (SIMPLE_ROW_TYPES as readonly string[]).includes(rowType);
}

/** Display-Optionen einer Terminliste (auch eingebettet in Matrixzeilen). */
export const EVENT_DISPLAY_DEFAULTS = {
  event_gray_past: true,
  event_allow_end_date: false,
  event_show_date: true,
  event_show_end_date: false,
  event_show_tag: true,
  event_show_tag_colors: false,
  event_show_title: true,
  event_show_description: true,
  event_show_location: false,
  event_show_organizers: false,
  event_show_participant_count: false,
  event_show_cancelled: false,
} as const;

export type EventDisplayKey = keyof typeof EVENT_DISPLAY_DEFAULTS;

/** Matrixzeile «Mehrere Termine»: was pro Termin in der Zelle steht (bisher fest Datum + Beschreibung). */
export const EVENTS_ROW_DISPLAY_DEFAULTS = {
  event_show_date: true,
  event_show_title: false,
  event_show_description: true,
  event_show_location: false,
} as const;

export function defaultRow(id = "1"): TableRow {
  return {
    id,
    label: "",
    row_type: "text",
    locked_in_protocol: false,
    row_config: {},
    auto_source_field: null,
    template_value: "",
    template_participant_id: null,
    template_participant_ids: [],
    template_event_id: null,
  };
}

export function defaultColumn(id = "matrix-column-1"): MatrixColumn {
  return { id, title: "", event_tag_filter: "", title_placeholder: "" };
}

/** Zeilen-Konfiguration beim Wechsel des Zeilentyps (wie im Backend-Schema). */
export function defaultRowConfig(rowType: string): BlockConfig {
  if (rowType === "events") return { ...EVENTS_ROW_DISPLAY_DEFAULTS, event_filter: defaultEventFilter("future") };
  if (rowType === "7") return { ...EVENT_DISPLAY_DEFAULTS, event_filter: defaultEventFilter("future") };
  return {};
}

export function defaultConfig(code: ElementTypeCode): BlockConfig {
  const base: BlockConfig = { block_kind: code, repeat_source: "none" };
  switch (code) {
    case "todo":
      return { ...base, todo_due_tag_filter: "", todo_assignee_participant_id: null };
    case "form":
      return {
        ...base,
        rows: [defaultRow("1")],
        left_column_heading: "",
        value_column_heading: "",
        linked_list_id: null,
        linked_list_group_by: null,
        linked_list_sort_by: null,
        linked_list_sort_direction: null,
        linked_list_highlight_empty: false,
        linked_list_filter_column: null,
        linked_list_filter_text: "",
        event_fields: null,
      };
    case "event_list":
      return { ...base, ...EVENT_DISPLAY_DEFAULTS, event_filter: defaultEventFilter("future") };
    case "attendance":
      return { ...base, fines_enabled: false, attendance_excluded_participant_ids: [] };
    case "session_date":
      return { ...base, event_filter: defaultEventFilter("all") };
    case "matrix":
      return {
        ...base,
        mode: "manual",
        allow_column_management: true,
        auto_source: null,
        rows: [defaultRow("1")],
        columns: [defaultColumn()],
        left_column_heading: "",
      };
    case "finance_balance":
      return { ...base, finance_account_id: null, finance_balance_date: "today" };
    case "finance_transactions":
      return { ...base, finance_account_id: null, finance_filter_type: "all", finance_last_n: 10, finance_since_date: null };
    case "fine_list":
      return { ...base, fine_list_account_id: null, fine_list_status: "all", fine_list_range: "all", fine_list_group_by: "none" };
    case "chart":
      return { ...base, chart_type: null, cycle_config_id: null, cycle_offset: 0 };
    case "entry_exit":
      return { ...base, entry_exit_first_use_mode: "all", entry_exit_first_use_date: null };
    default:
      return base;
  }
}

export function newBlockForm(elementTypeId: number, id: number, sortIndex: number): BlockForm {
  const info = elementType(elementTypeId);
  return {
    id,
    title: "",
    block_title: "",
    description: "",
    default_content: "",
    element_type_id: info.id,
    is_editable: info.defaultEditable,
    export_visible: true,
    is_visible: true,
    copy_from_last_protocol: false,
    title_as_subtitle: true,
    sort_index: sortIndex,
    config: defaultConfig(info.code),
  };
}

function normalizeRow(raw: Record<string, any>, index: number): TableRow {
  return {
    id: String(raw.id ?? index + 1),
    label: String(raw.label ?? ""),
    row_type: String(raw.row_type ?? "text"),
    locked_in_protocol: Boolean(raw.locked_in_protocol),
    row_config: raw.row_config && typeof raw.row_config === "object" ? { ...raw.row_config } : {},
    auto_source_field: raw.auto_source_field ? String(raw.auto_source_field) : null,
    template_value: String(raw.template_value ?? ""),
    template_participant_id: raw.template_participant_id != null ? String(raw.template_participant_id) : null,
    template_participant_ids: Array.isArray(raw.template_participant_ids) ? raw.template_participant_ids.map(String).filter(Boolean) : [],
    template_event_id: raw.template_event_id != null ? String(raw.template_event_id) : null,
  };
}

function normalizeColumn(raw: Record<string, any>, index: number): MatrixColumn {
  return {
    id: String(raw.id ?? `matrix-column-${index + 1}`),
    title: String(raw.title ?? ""),
    event_tag_filter: String(raw.event_tag_filter ?? ""),
    title_placeholder: String(raw.title_placeholder ?? ""),
  };
}

export function blockFormFromBlock(block: ElementDefinitionBlock): BlockForm {
  const info = elementType(block.element_type_id);
  const stored = (block.configuration_json ?? {}) as BlockConfig;
  // Gespeicherte Werte über die Vorgaben des Typs legen, damit jedes Feld definiert ist.
  const config: BlockConfig = { ...defaultConfig(info.code), ...stored };
  if (Array.isArray(stored.rows)) config.rows = stored.rows.map(normalizeRow);
  if (Array.isArray(stored.columns)) config.columns = stored.columns.map(normalizeColumn);
  if (info.code === "matrix" && !Array.isArray(stored.rows)) config.rows = [];
  if (info.code === "matrix" && !Array.isArray(stored.columns)) config.columns = [];
  if (info.code === "form" && !Array.isArray(stored.rows)) config.rows = [];
  return {
    id: block.id,
    title: block.title ?? "",
    block_title: block.block_title ?? "",
    description: block.description ?? "",
    default_content: block.default_content ?? "",
    element_type_id: info.id,
    is_editable: block.is_editable,
    export_visible: block.export_visible,
    is_visible: block.is_visible,
    copy_from_last_protocol: Boolean(block.copy_from_last_protocol),
    title_as_subtitle: block.title_as_subtitle ?? true,
    sort_index: block.sort_index,
    config,
  };
}

export function repeatSourcesFor(form: BlockForm): RepeatSource[] {
  return elementType(form.element_type_id).repeat;
}

/** Wiederholung wird gezeigt, wenn der Typ sie unterstützt oder ein Block sie schon nutzt. */
export function showsRepeat(form: BlockForm): boolean {
  return repeatSourcesFor(form).length > 0 || (form.config.repeat_source ?? "none") !== "none";
}

export function repeatEventFilter(form: BlockForm): EventFilter {
  return normalizeEventFilter(form.config.repeat_event_filter, "window");
}

export function setRepeatSource(form: BlockForm, source: "none" | RepeatSource): BlockForm {
  const config: BlockConfig = { ...form.config, repeat_source: source };
  if (source === "event" && !config.repeat_event_filter) {
    config.repeat_event_filter = defaultEventFilter("window");
  }
  return { ...form, config };
}

/**
 * Typwechsel: Konfiguration des neuen Typs, Wiederholung bleibt (falls erlaubt), Tabelle und
 * Matrix teilen sich das Zeilenmodell. «Im Protokoll editierbar» wird nur beim Anlegen auf den
 * Typ-Default gesetzt (B3: beim Bearbeiten bleibt die bewusste Einstellung).
 */
export function changeElementType(form: BlockForm, nextTypeId: number, mode: "create" | "edit"): BlockForm {
  const next = elementType(nextTypeId);
  const previousCode = elementTypeCode(form.element_type_id);
  const config: BlockConfig = defaultConfig(next.code);
  const repeatSource = form.config.repeat_source ?? "none";
  if (repeatSource !== "none" && (next.repeat as string[]).includes(repeatSource)) {
    for (const key of ["repeat_source", "repeat_event_filter", "event_include_unlisted_past", "todo_block_title_filter", "todo_task_filter", "todo_open_only"]) {
      if (key in form.config) config[key] = form.config[key];
    }
  }
  const sharesRows = (code: string) => code === "form" || code === "matrix";
  if (sharesRows(previousCode) && sharesRows(next.code) && Array.isArray(form.config.rows) && form.config.rows.length) {
    config.rows = (form.config.rows as TableRow[]).filter((row) => rowTypeAllowed(next.code, row.row_type));
    if (!config.rows.length) config.rows = [defaultRow("1")];
  }
  return {
    ...form,
    element_type_id: next.id,
    is_editable: mode === "create" ? next.defaultEditable : form.is_editable,
    copy_from_last_protocol: next.carryOver ? form.copy_from_last_protocol : false,
    default_content: next.content ? form.default_content : "",
    config,
  };
}

/** Zeilentypen, die Protokoll-Editor und Export für den jeweiligen Blocktyp darstellen:
 * «Mehrere Termine (automatisch)» und eingebettete Blöcke hängen an Matrixspalten,
 * «Zeile aus Liste» an der zweispaltigen Tabelle. */
export function rowTypeAllowed(code: string, rowType: string): boolean {
  if (rowType === "events") return code === "matrix";
  if (rowType === "list_entry") return code === "form";
  if (isSimpleRowType(rowType)) return true;
  return code === "matrix" && elementType(rowType).matrixEmbeddable;
}

function cleanRow(row: TableRow, index: number) {
  return {
    id: row.id || String(index + 1),
    label: row.label,
    row_type: row.row_type || "text",
    locked_in_protocol: Boolean(row.locked_in_protocol),
    row_config: row.row_config ?? {},
    auto_source_field: row.auto_source_field || null,
    template_value: row.template_value ?? "",
    template_participant_id: row.template_participant_id || null,
    template_participant_ids: (row.template_participant_ids ?? []).filter(Boolean),
    template_event_id: row.template_event_id || null,
    sort_index: (index + 1) * 10,
  };
}

/** Konfiguration für das Speichern: nur, was der Typ und die gewählte Wiederholung nutzen. */
export function configPayload(form: BlockForm): BlockConfig {
  const code = elementTypeCode(form.element_type_id);
  const config: BlockConfig = { ...form.config, block_kind: code };
  const repeat = String(config.repeat_source ?? "none");
  if (repeat !== "event") {
    delete config.repeat_event_filter;
    delete config.event_include_unlisted_past;
  }
  if (repeat !== "todo") {
    delete config.todo_block_title_filter;
    delete config.todo_task_filter;
    delete config.todo_open_only;
  }
  if (repeat === "none" || code !== "text") delete config.sync_target_field;
  if (code === "form") {
    const linked = Boolean(config.linked_list_id);
    config.rows = linked ? [] : ((config.rows ?? []) as TableRow[]).map(cleanRow);
    if (!linked) {
      for (const key of ["linked_list_group_by", "linked_list_sort_by", "linked_list_sort_direction", "linked_list_filter_column"]) config[key] = null;
      config.linked_list_highlight_empty = false;
      config.linked_list_filter_text = "";
    }
    if (repeat !== "event" || linked) config.event_fields = null;
  }
  if (code === "matrix") {
    config.rows = ((config.rows ?? []) as TableRow[]).map(cleanRow);
    config.columns = config.mode === "auto"
      ? []
      : ((config.columns ?? []) as MatrixColumn[]).map((column, index) => ({
          id: column.id || `matrix-column-${index + 1}`,
          title: column.title,
          event_tag_filter: column.event_tag_filter?.trim() || null,
          title_placeholder: column.title_placeholder?.trim() || null,
          sort_index: (index + 1) * 10,
        }));
    if (config.mode !== "auto") config.auto_source = null;
  }
  return config;
}

export function blockPayload(form: BlockForm): ElementDefinitionBlock {
  const info = elementType(form.element_type_id);
  return {
    id: form.id,
    title: form.title,
    description: form.description.trim() || null,
    block_title: form.block_title || null,
    default_content: info.content ? form.default_content || null : null,
    copy_from_last_protocol: info.carryOver ? form.copy_from_last_protocol : false,
    title_as_subtitle: form.title_as_subtitle,
    element_type_id: info.id,
    render_type_id: info.renderTypeId,
    is_editable: form.is_editable,
    allows_multiple_values: info.allowsMultipleValues,
    export_visible: form.export_visible,
    is_visible: form.is_visible,
    sort_index: form.sort_index,
    render_order: form.sort_index,
    latex_template: null,
    configuration_json: configPayload(form),
  };
}

export function nextRowId(rows: TableRow[]): string {
  return String(Math.max(0, ...rows.map((row) => Number(row.id) || 0)) + 1);
}

export function nextColumnId(columns: MatrixColumn[]): string {
  const highest = columns.reduce((max, column) => {
    const match = String(column.id ?? "").match(/^matrix-column-(\d+)$/);
    return Math.max(max, match ? Number(match[1]) : 0);
  }, 0);
  return `matrix-column-${highest + 1}`;
}

export function nextBlockId(blocks: ElementDefinitionBlock[]): number {
  return Math.max(0, ...blocks.map((block) => block.id)) + 1;
}

export function moveItem<T>(items: T[], fromIndex: number, toIndex: number): T[] {
  if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0 || fromIndex >= items.length || toIndex >= items.length) return items;
  const next = [...items];
  const [moved] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, moved);
  return next;
}
