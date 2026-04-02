"use client";

import { Dispatch, Fragment, ReactNode, SetStateAction, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { StructuredListTable } from "@/components/lists/structured-list-table";
import { DataToolbar } from "@/components/ui/data-table";
import { RichTextEditor } from "@/components/ui/rich-text-editor";
import { Modal } from "@/components/ui/modal";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { formatDate, formatDateRange } from "@/lib/utils/format";
import {
  EventSummary,
  ParticipantSummary,
  ProtocolElement,
  ProtocolImage,
  ProtocolSummary,
  ProtocolTodo,
  SaveState,
  StructuredListDefinition,
  StructuredListEntry,
  TemplateSummary,
} from "@/types/api";

type ProtocolEditorProps = {
  protocol: ProtocolSummary;
  initialElements: ProtocolElement[];
  initialTodos: Record<number, ProtocolTodo[]>;
  initialImages: Record<number, ProtocolImage[]>;
  availableParticipants: ParticipantSummary[];
  availableEvents: EventSummary[];
  availableLists: StructuredListDefinition[];
  initialListEntries: Record<number, StructuredListEntry[]>;
  availableTemplates: TemplateSummary[];
};

const TODO_STATUS = {
  open: 1,
  in_progress: 2,
  done: 3,
  cancelled: 4
} as const;

function protocolStatusLabel(status: string) {
  switch (status) {
    case "geplant":
      return "Geplant";
    case "vorbereitet":
      return "Vorbereitet";
    case "durchgeführt":
      return "Durchgeführt";
    case "abgeschlossen":
      return "Abgeschlossen";
    default:
      return status;
  }
}

function resequenceProtocolElements(items: ProtocolElement[]) {
  return items.map((item, index) => ({ ...item, sort_index: (index + 1) * 10 }));
}

function elementSaveState(element: ProtocolElement, blockStatus: Record<number, SaveState>): SaveState {
  const states = element.blocks.map((block) => blockStatus[block.id] ?? "saved");
  if (states.includes("error")) return "error";
  if (states.includes("saving")) return "saving";
  return "saved";
}

function formatShortDate(value: string | null | undefined) {
  return formatDate(value);
}

function compareIsoDate(left: string | null | undefined, right: string | null | undefined) {
  if (!left && !right) return 0;
  if (!left) return -1;
  if (!right) return 1;
  return left.localeCompare(right);
}

const ATTENDANCE_OPTIONS = [
  { value: "present", label: "Anwesend" },
  { value: "late", label: "Verspaetet" },
  { value: "excused", label: "Entschuldigt" },
  { value: "absent", label: "Unentschuldigt" },
] as const;

const EMBEDDED_BLOCK_OPTIONS = [
  { value: 1, label: "Text" },
  { value: 6, label: "Tabelle" },
  { value: 2, label: "Todo" },
  { value: 3, label: "Bild" },
  { value: 5, label: "Statischer Text" },
  { value: 7, label: "Terminliste" },
  { value: 8, label: "Bulletpoints" },
  { value: 9, label: "Anwesenheit" },
  { value: 10, label: "Sitzungsdatum" },
] as const;

const EMBEDDED_FORM_VALUE_OPTIONS = [
  { value: "text", label: "Freier Text" },
  { value: "participant", label: "Ein Teilnehmer" },
  { value: "participants", label: "Mehrere Teilnehmer" },
  { value: "event", label: "Ein Termin" },
] as const;

type MatrixEmbeddedBlock = {
  element_type_id: number;
  title?: string | null;
  block_kind?: string | null;
  text_content?: string | null;
  configuration_snapshot_json?: Record<string, unknown>;
};

type ProtocolEventDraft = {
  event_date: string;
  event_end_date: string;
  tag: string;
  title: string;
  description: string;
  participant_count: string;
};

function createProtocolEventDraft(protocolDate: string | undefined, defaultTag = ""): ProtocolEventDraft {
  return {
    event_date: protocolDate || new Date().toISOString().slice(0, 10),
    event_end_date: "",
    tag: defaultTag,
    title: "",
    description: "",
    participant_count: "0",
  };
}

function createInlineProtocolEventDraft(protocolDate: string | undefined, defaultTag = "", showTitle = true): ProtocolEventDraft {
  const draft = createProtocolEventDraft(protocolDate, defaultTag);
  if (!showTitle) {
    draft.title = "Neuer Termin";
  }
  return draft;
}

function canCreateProtocolEventDraft(draft: ProtocolEventDraft) {
  return Boolean(draft.event_date.trim() && draft.title.trim());
}

function embeddedBlockKindForElementType(elementTypeId: number | string) {
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
  };
  return mapping[String(elementTypeId)] ?? "text";
}

function embeddedBlockTypeLabel(elementTypeId: number | string) {
  return EMBEDDED_BLOCK_OPTIONS.find((option) => option.value === Number(elementTypeId))?.label ?? `Block ${elementTypeId}`;
}

function nextEmbeddedItemId(items: Array<Record<string, any>>, prefix: string) {
  const maxValue = items.reduce((highest, item) => {
    const match = String(item.id ?? "").match(new RegExp(`^${prefix}-(\\d+)$`));
    const candidate = match ? Number(match[1]) : 0;
    return Math.max(highest, candidate);
  }, 0);
  return `${prefix}-${maxValue + 1}`;
}

function createEmbeddedFormRow(id = "form-row-1") {
  return {
    id,
    label: "",
    value_type: "text",
    text_value: "",
    participant_id: null,
    participant_ids: [],
    event_id: null,
  };
}

function createMatrixEmbeddedBlock(
  elementTypeId: number,
  rowLabel: string,
  protocol: ProtocolSummary,
  availableParticipants: ParticipantSummary[],
  configurationOverride: Record<string, unknown> = {}
): MatrixEmbeddedBlock {
  const blockKind = embeddedBlockKindForElementType(elementTypeId);
  const override = asObject(configurationOverride);

  if (elementTypeId === 2) {
    return {
      element_type_id: elementTypeId,
      title: rowLabel || embeddedBlockTypeLabel(elementTypeId),
      block_kind: blockKind,
      configuration_snapshot_json: {
        block_kind: blockKind,
        todo_items: [],
        ...override,
      },
    };
  }

  if (elementTypeId === 3) {
    return {
      element_type_id: elementTypeId,
      title: rowLabel || embeddedBlockTypeLabel(elementTypeId),
      block_kind: blockKind,
      configuration_snapshot_json: {
        block_kind: blockKind,
        images: [],
        ...override,
      },
    };
  }

  if (elementTypeId === 6) {
    return {
      element_type_id: elementTypeId,
      title: rowLabel || embeddedBlockTypeLabel(elementTypeId),
      block_kind: blockKind,
      configuration_snapshot_json: {
        block_kind: blockKind,
        rows: [createEmbeddedFormRow()],
        ...override,
      },
    };
  }

  if (elementTypeId === 7) {
    return {
      element_type_id: elementTypeId,
      title: rowLabel || embeddedBlockTypeLabel(elementTypeId),
      block_kind: blockKind,
      configuration_snapshot_json: {
        block_kind: blockKind,
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
        ...override,
      },
    };
  }

  if (elementTypeId === 8) {
    return {
      element_type_id: elementTypeId,
      title: rowLabel || embeddedBlockTypeLabel(elementTypeId),
      block_kind: blockKind,
      configuration_snapshot_json: {
        block_kind: blockKind,
        bullet_items: [],
        ...override,
      },
    };
  }

  if (elementTypeId === 9) {
    return {
      element_type_id: elementTypeId,
      title: rowLabel || embeddedBlockTypeLabel(elementTypeId),
      block_kind: blockKind,
      configuration_snapshot_json: {
        block_kind: blockKind,
        attendance_entries: availableParticipants.map((participant) => ({
          participant_id: participant.id,
          participant_name: participant.display_name,
          status: "absent",
        })),
        ...override,
      },
    };
  }

  if (elementTypeId === 10) {
    return {
      element_type_id: elementTypeId,
      title: rowLabel || embeddedBlockTypeLabel(elementTypeId),
      block_kind: blockKind,
      configuration_snapshot_json: {
        block_kind: blockKind,
        selected_date: protocol.protocol_date ?? "",
        session_label: rowLabel || "Naechste Sitzung",
        session_tag: "next_session",
        ...override,
      },
    };
  }

  return {
    element_type_id: elementTypeId,
    title: rowLabel || embeddedBlockTypeLabel(elementTypeId),
    block_kind: blockKind,
    text_content: "",
    configuration_snapshot_json: {
      block_kind: blockKind,
      ...override,
    },
  };
}

function asObject(value: unknown): Record<string, any> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, any>) : {};
}

function readMatrixEmbeddedBlock(cell: Record<string, any>): MatrixEmbeddedBlock | null {
  const embeddedBlock = asObject(cell.embedded_block);
  const elementTypeId = Number(embeddedBlock.element_type_id ?? 0);
  if (!elementTypeId) {
    return null;
  }
  return {
    element_type_id: elementTypeId,
    title: typeof embeddedBlock.title === "string" ? embeddedBlock.title : null,
    block_kind: typeof embeddedBlock.block_kind === "string" ? embeddedBlock.block_kind : embeddedBlockKindForElementType(elementTypeId),
    text_content: typeof embeddedBlock.text_content === "string" ? embeddedBlock.text_content : "",
    configuration_snapshot_json: asObject(embeddedBlock.configuration_snapshot_json),
  };
}

function embeddedBlockSummary(
  embeddedBlock: MatrixEmbeddedBlock,
  availableParticipants: ParticipantSummary[],
  availableEvents: EventSummary[],
  protocol: ProtocolSummary,
  matrixColumn?: Record<string, any>
) {
  const config = asObject(embeddedBlock.configuration_snapshot_json);
  const elementTypeId = Number(embeddedBlock.element_type_id ?? 0);

  if (elementTypeId === 2) {
    const items = (Array.isArray(config.todo_items) ? config.todo_items : []) as Array<Record<string, any>>;
    const filledItems = items.filter((item) => String(item.task ?? "").trim());
    return filledItems.length ? `${filledItems.length} Todo${filledItems.length === 1 ? "" : "s"}` : "Keine Todos";
  }

  if (elementTypeId === 3) {
    const images = (Array.isArray(config.images) ? config.images : []) as Array<Record<string, any>>;
    const filledImages = images.filter((image) => String(image.url ?? "").trim());
    return filledImages.length ? `${filledImages.length} Bild${filledImages.length === 1 ? "" : "er"}` : "Kein Bild";
  }

  if (elementTypeId === 6) {
    const rows = (Array.isArray(config.rows) ? config.rows : []) as Array<Record<string, any>>;
    return rows.length ? `${rows.length} Zeile${rows.length === 1 ? "" : "n"}` : "Leere Tabelle";
  }

  if (elementTypeId === 7) {
    const tagFilter = String(config.event_tag_filter ?? "").trim().toLowerCase();
    const columnTagFilter = config.event_use_column_tag_filter === true
      ? String(matrixColumn?.event_tag_filter || matrixColumn?.title || "").trim().toLowerCase() : "";
    const matchingEvents = availableEvents.filter((event) => {
      const effectiveEndDate = event.event_end_date || event.event_date;
      const matchesDate = config.event_only_from_protocol_date === false || !protocol.protocol_date || effectiveEndDate >= protocol.protocol_date;
      const matchesTag = (!tagFilter || (event.tag ?? "").toLowerCase().includes(tagFilter)) &&
        (!columnTagFilter || (event.tag ?? "").toLowerCase().includes(columnTagFilter));
      return matchesDate && matchesTag;
    });
    return matchingEvents.length ? `${matchingEvents.length} Termin${matchingEvents.length === 1 ? "" : "e"}` : "Keine Termine";
  }

  if (elementTypeId === 8) {
    const items = (Array.isArray(config.bullet_items) ? config.bullet_items : []) as string[];
    const filledItems = items.filter((item) => String(item).trim());
    return filledItems.length ? `${filledItems.length} Punkt${filledItems.length === 1 ? "" : "e"}` : "Keine Punkte";
  }

  if (elementTypeId === 9) {
    const entries = (Array.isArray(config.attendance_entries) ? config.attendance_entries : []) as Array<Record<string, any>>;
    const presentCount = entries.filter((entry) => String(entry.status ?? "") === "present").length;
    return entries.length ? `${presentCount}/${entries.length} anwesend` : `${availableParticipants.length} Teilnehmer`;
  }

  if (elementTypeId === 10) {
    return String(config.selected_date ?? "").trim() ? `Termin ${formatShortDate(String(config.selected_date))}` : "Kein Datum";
  }

  const text = String(embeddedBlock.text_content ?? "").trim();
  return text || "Kein Inhalt";
}

function visibleBlockTitle(block: {
  block_title_snapshot?: string | null;
  display_title_snapshot?: string | null;
  title_snapshot?: string | null;
}) {
  const blockTitle = String(block.block_title_snapshot ?? "").trim();
  const displayTitle = String(block.display_title_snapshot ?? "").trim();
  const title = String(block.title_snapshot ?? "").trim();
  return blockTitle || displayTitle || title || null;
}

function TodoMiniMenu({
  label,
  compact = false,
  align = "start",
  children,
}: {
  label: string;
  compact?: boolean;
  align?: "start" | "end";
  children: (close: () => void) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function onPointerDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }

    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  return (
    <div className={`mini-menu${compact ? " mini-menu-compact" : ""}${align === "end" ? " mini-menu-end" : ""}`} ref={rootRef}>
      <button
        type="button"
        className={`mini-menu-trigger${open ? " mini-menu-trigger-open" : ""}`}
        onClick={() => setOpen((current) => !current)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="mini-menu-trigger-label">{label}</span>
        <span className="mini-menu-trigger-icon">⌄</span>
      </button>
      {open ? (
        <div className="mini-menu-popover" role="menu">
          {children(() => setOpen(false))}
        </div>
      ) : null}
    </div>
  );
}

function TodoMenuOption({
  label,
  active = false,
  onClick,
  subtle,
}: {
  label: string;
  active?: boolean;
  onClick: () => void;
  subtle?: string;
}) {
  return (
    <button type="button" className={`mini-menu-option${active ? " mini-menu-option-active" : ""}`} onClick={onClick}>
      <span>{label}</span>
      {subtle ? <span className="mini-menu-option-subtle">{subtle}</span> : null}
    </button>
  );
}

function MatrixEmbeddedBlockEditor({
  embeddedBlock,
  protocol,
  availableParticipants,
  availableEvents,
  matrixColumn,
  editable = true,
  updateEmbeddedBlock,
  openMultiParticipantPicker,
  createEvent,
  updateEvent,
  deleteEvent,
}: {
  embeddedBlock: MatrixEmbeddedBlock;
  protocol: ProtocolSummary;
  availableParticipants: ParticipantSummary[];
  availableEvents: EventSummary[];
  matrixColumn?: Record<string, any>;
  editable?: boolean;
  updateEmbeddedBlock: (updater: (current: MatrixEmbeddedBlock) => MatrixEmbeddedBlock, persist?: boolean) => void;
  openMultiParticipantPicker: (row: Record<string, any>) => void;
  createEvent: (forcedTag: string, draft: ProtocolEventDraft) => Promise<boolean>;
  updateEvent: (eventId: number, patch: Partial<EventSummary>) => Promise<boolean>;
  deleteEvent: (eventId: number) => Promise<void>;
}) {
  const elementTypeId = Number(embeddedBlock.element_type_id ?? 0);
  const embeddedConfig = asObject(embeddedBlock.configuration_snapshot_json);
  const sortedEvents = [...availableEvents].sort((left, right) => compareIsoDate(left.event_date, right.event_date));
  const embeddedBlockClassName = "matrix-embedded-block";
  const [embeddedEventDrafts, setEmbeddedEventDrafts] = useState<Record<number, Partial<EventSummary>>>({});
  const embeddedEventAutosaveTimers = useRef<Record<number, number>>({});
  const forcedEmbeddedTag =
    (embeddedConfig.event_use_column_tag_filter === true ? String(matrixColumn?.event_tag_filter || matrixColumn?.title || "").trim() : "") ||
    String(embeddedConfig.event_tag_filter ?? "").trim();
  const [newEmbeddedEventDraft, setNewEmbeddedEventDraft] = useState<ProtocolEventDraft>(() =>
    createInlineProtocolEventDraft(protocol.protocol_date, forcedEmbeddedTag)
  );
  const [showNewEmbeddedEventRow, setShowNewEmbeddedEventRow] = useState(false);
  const [creatingEmbeddedEvent, setCreatingEmbeddedEvent] = useState(false);
  const newEmbeddedEventCreateTimer = useRef<number | null>(null);
  const allowEmbeddedEndDate = embeddedConfig.event_allow_end_date === true;
  const embeddedEventColumns = {
    showDate: embeddedConfig.event_show_date !== false,
    showTag: embeddedConfig.event_show_tag !== false,
    showTitle: embeddedConfig.event_show_title !== false,
    showDescription: embeddedConfig.event_show_description !== false,
    showParticipantCount: embeddedConfig.event_show_participant_count === true,
  };
  if (
    !embeddedEventColumns.showDate &&
    !embeddedEventColumns.showTag &&
    !embeddedEventColumns.showTitle &&
    !embeddedEventColumns.showDescription &&
    !embeddedEventColumns.showParticipantCount
  ) {
    embeddedEventColumns.showTitle = true;
  }

  function updateEmbeddedConfig(updater: (current: Record<string, any>) => Record<string, unknown>, persist = false) {
    updateEmbeddedBlock(
      (current) => ({
        ...current,
        configuration_snapshot_json: updater(asObject(current.configuration_snapshot_json)),
      }),
      persist
    );
  }

  useEffect(() => {
    setNewEmbeddedEventDraft((current) => {
      const hasManualContent =
        Boolean(current.title.trim()) ||
        Boolean(current.description.trim()) ||
        Boolean(current.event_end_date.trim()) ||
        Number(current.participant_count || "0") > 0;
      if (hasManualContent) {
        return current;
      }
      return createInlineProtocolEventDraft(protocol.protocol_date, forcedEmbeddedTag, embeddedEventColumns.showTitle);
    });
  }, [embeddedEventColumns.showTitle, forcedEmbeddedTag, protocol.protocol_date]);

  useEffect(() => {
    return () => {
      Object.values(embeddedEventAutosaveTimers.current).forEach((timerId) => window.clearTimeout(timerId));
      if (newEmbeddedEventCreateTimer.current) {
        window.clearTimeout(newEmbeddedEventCreateTimer.current);
      }
    };
  }, []);

  function participantNameById(participantId: number | null | undefined) {
    return availableParticipants.find((participant) => participant.id === Number(participantId ?? 0))?.display_name ?? "—";
  }

  function eventLabelById(eventId: number | null | undefined) {
    const eventRow = sortedEvents.find((entry) => entry.id === Number(eventId ?? 0));
    return eventRow ? `${formatDateRange(eventRow.event_date, eventRow.event_end_date)} · ${eventRow.title}` : "—";
  }

  function attendanceStatusLabel(status: string | null | undefined) {
    return ATTENDANCE_OPTIONS.find((option) => option.value === status)?.label ?? "Unbekannt";
  }

  function embeddedEventPayload(eventRow: EventSummary, draft: Partial<EventSummary>) {
    const nextEventRow = {
      ...eventRow,
      ...draft,
    };
    return {
      event_date: nextEventRow.event_date,
      event_end_date: allowEmbeddedEndDate ? nextEventRow.event_end_date || null : null,
      tag: forcedEmbeddedTag || nextEventRow.tag || null,
      title: nextEventRow.title,
      description: nextEventRow.description || null,
      participant_count: Math.max(0, Number(nextEventRow.participant_count ?? 0)),
    };
  }

  function queueEmbeddedEventSave(eventRow: EventSummary, patch: Partial<EventSummary>) {
    const nextDraft = {
      ...(embeddedEventDrafts[eventRow.id] ?? {}),
      ...patch,
    };
    setEmbeddedEventDrafts((current) => ({
      ...current,
      [eventRow.id]: nextDraft,
    }));
    if (embeddedEventAutosaveTimers.current[eventRow.id]) {
      window.clearTimeout(embeddedEventAutosaveTimers.current[eventRow.id]);
    }
    embeddedEventAutosaveTimers.current[eventRow.id] = window.setTimeout(async () => {
      const saved = await updateEvent(eventRow.id, embeddedEventPayload(eventRow, nextDraft));
      if (saved) {
        setEmbeddedEventDrafts((current) => {
          if (!current[eventRow.id]) {
            return current;
          }
          const next = { ...current };
          delete next[eventRow.id];
          return next;
        });
      }
    }, 500);
  }

  function resetNewEmbeddedEventRow() {
    if (newEmbeddedEventCreateTimer.current) {
      window.clearTimeout(newEmbeddedEventCreateTimer.current);
      newEmbeddedEventCreateTimer.current = null;
    }
    setCreatingEmbeddedEvent(false);
    setShowNewEmbeddedEventRow(false);
    setNewEmbeddedEventDraft(createInlineProtocolEventDraft(protocol.protocol_date, forcedEmbeddedTag, embeddedEventColumns.showTitle));
  }

  function scheduleEmbeddedEventCreate(nextDraft: ProtocolEventDraft) {
    if (newEmbeddedEventCreateTimer.current) {
      window.clearTimeout(newEmbeddedEventCreateTimer.current);
      newEmbeddedEventCreateTimer.current = null;
    }
    if (!canCreateProtocolEventDraft(nextDraft)) {
      return;
    }
    newEmbeddedEventCreateTimer.current = window.setTimeout(async () => {
      setCreatingEmbeddedEvent(true);
      const saved = await createEvent(forcedEmbeddedTag, nextDraft);
      setCreatingEmbeddedEvent(false);
      if (saved) {
        resetNewEmbeddedEventRow();
      }
    }, 500);
  }

  function patchNewEmbeddedEventDraft(patch: Partial<ProtocolEventDraft>) {
    setNewEmbeddedEventDraft((current) => {
      const nextDraft = { ...current, ...patch };
      scheduleEmbeddedEventCreate(nextDraft);
      return nextDraft;
    });
  }

  function embeddedParticipantSummary(row: Record<string, any>) {
    const selectedIds = Array.isArray(row.participant_ids) ? row.participant_ids.map(Number) : [];
    if (!selectedIds.length) {
      return "Teilnehmer waehlen";
    }
    const selectedParticipants = availableParticipants.filter((participant) => selectedIds.includes(participant.id));
    if (!selectedParticipants.length) {
      return `${selectedIds.length} ausgewaehlt`;
    }
    if (selectedParticipants.length === 1) {
      return selectedParticipants[0].display_name;
    }
    if (selectedParticipants.length === 2) {
      return `${selectedParticipants[0].display_name}, ${selectedParticipants[1].display_name}`;
    }
    return `${selectedParticipants[0].display_name} + ${selectedParticipants.length - 1}`;
  }

  if (elementTypeId === 1 || elementTypeId === 5) {
    if (!editable) {
      return (
        <div className={embeddedBlockClassName}>
          <div className="matrix-static-value">{String(embeddedBlock.text_content ?? "").trim() || "Kein Inhalt"}</div>
        </div>
      );
    }
    return (
      <div className={embeddedBlockClassName}>
        <textarea
          rows={4}
          className="todo-input"
          value={String(embeddedBlock.text_content ?? "")}
          onChange={(event) => updateEmbeddedBlock((current) => ({ ...current, text_content: event.target.value }))}
          onBlur={() => updateEmbeddedBlock((current) => current, true)}
          placeholder="Blockinhalt"
        />
      </div>
    );
  }

  if (elementTypeId === 2) {
    const todoItems = (Array.isArray(embeddedConfig.todo_items) ? embeddedConfig.todo_items : []) as Array<Record<string, any>>;
    if (!editable) {
      return (
        <div className={embeddedBlockClassName}>
          {todoItems.length ? (
            <div className="matrix-static-list">
              {todoItems.map((item, index) => (
                <div className="matrix-static-list-item" key={String(item.id ?? index)}>
                  {Boolean(item.done) ? "✓ " : ""}
                  {String(item.task ?? "").trim() || "Leeres Todo"}
                </div>
              ))}
            </div>
          ) : (
            <div className="matrix-static-value">Keine Todos</div>
          )}
        </div>
      );
    }
    return (
      <div className={embeddedBlockClassName}>
        <div className="todo-list">
          {todoItems.map((item, index) => {
            const isDone = Boolean(item.done);
            return (
              <article className={`todo-card todo-card-compact${isDone ? " todo-card-done" : ""}`} key={String(item.id ?? index)}>
                <button
                  type="button"
                  className={`todo-toggle${isDone ? " todo-toggle-done" : ""}`}
                  onClick={() =>
                    updateEmbeddedConfig((current) => ({
                      ...current,
                      todo_items: todoItems.map((entry, entryIndex) =>
                        entryIndex === index ? { ...entry, done: !isDone } : entry
                      ),
                    }), true)
                  }
                >
                  {isDone ? "✓" : "○"}
                </button>
                <div className="todo-main todo-main-compact">
                  <textarea
                    rows={1}
                    className="todo-input"
                    value={String(item.task ?? "")}
                    onChange={(event) =>
                      updateEmbeddedConfig((current) => ({
                        ...current,
                        todo_items: todoItems.map((entry, entryIndex) =>
                          entryIndex === index ? { ...entry, task: event.target.value } : entry
                        ),
                      }))
                    }
                    onBlur={() => updateEmbeddedBlock((current) => current, true)}
                  />
                </div>
                <button
                  type="button"
                  className="button-inline button-danger todo-delete"
                  onClick={() =>
                    updateEmbeddedConfig((current) => ({
                      ...current,
                      todo_items: todoItems.filter((_, entryIndex) => entryIndex !== index),
                    }), true)
                  }
                >
                  Delete
                </button>
              </article>
            );
          })}
        </div>
        <div className="todo-create todo-create-inline">
          <input value="" readOnly placeholder="Neues Todo mit dem Button hinzufügen" />
          <button
            type="button"
            onClick={() =>
              updateEmbeddedConfig((current) => ({
                ...current,
                todo_items: [
                  ...todoItems,
                  { id: nextEmbeddedItemId(todoItems, "todo"), task: "", done: false },
                ],
              }), true)
            }
          >
            + Todo
          </button>
        </div>
      </div>
    );
  }

  if (elementTypeId === 3) {
    const images = (Array.isArray(embeddedConfig.images) ? embeddedConfig.images : []) as Array<Record<string, any>>;
    if (!editable) {
      return (
        <div className={embeddedBlockClassName}>
          {images.length ? (
            <div className="image-grid">
              {images.map((image, index) => (
                <div className="card image-card" key={String(image.id ?? index)}>
                  {String(image.url ?? "").trim() ? <img alt={String(image.caption ?? "Matrixbild")} src={String(image.url)} /> : null}
                  {String(image.caption ?? "").trim() ? <div className="muted">{String(image.caption)}</div> : null}
                </div>
              ))}
            </div>
          ) : (
            <div className="matrix-static-value">Kein Bild</div>
          )}
        </div>
      );
    }
    return (
      <div className={embeddedBlockClassName}>
        <div className="image-grid">
          {images.map((image, index) => (
            <div className="card image-card" key={String(image.id ?? index)}>
              <label className="field-stack">
                <span className="field-label">Bild-URL</span>
                <input
                  value={String(image.url ?? "")}
                  onChange={(event) =>
                    updateEmbeddedConfig((current) => ({
                      ...current,
                      images: images.map((entry, entryIndex) =>
                        entryIndex === index ? { ...entry, url: event.target.value } : entry
                      ),
                    }))
                  }
                  onBlur={() => updateEmbeddedBlock((current) => current, true)}
                  placeholder="https://..."
                />
              </label>
              <label className="field-stack">
                <span className="field-label">Bildunterschrift</span>
                <input
                  value={String(image.caption ?? "")}
                  onChange={(event) =>
                    updateEmbeddedConfig((current) => ({
                      ...current,
                      images: images.map((entry, entryIndex) =>
                        entryIndex === index ? { ...entry, caption: event.target.value } : entry
                      ),
                    }))
                  }
                  onBlur={() => updateEmbeddedBlock((current) => current, true)}
                  placeholder="Optional"
                />
              </label>
              {String(image.url ?? "").trim() ? <img alt={String(image.caption ?? "Matrixbild")} src={String(image.url)} /> : null}
              <button
                type="button"
                className="button-inline button-danger"
                onClick={() =>
                  updateEmbeddedConfig((current) => ({
                    ...current,
                    images: images.filter((_, entryIndex) => entryIndex !== index),
                  }), true)
                }
              >
                Bild entfernen
              </button>
            </div>
          ))}
        </div>
        <div className="table-toolbar-actions">
          <button
            type="button"
            className="button-inline"
            onClick={() =>
              updateEmbeddedConfig((current) => ({
                ...current,
                images: [...images, { id: nextEmbeddedItemId(images, "image"), url: "", caption: "" }],
              }), true)
            }
          >
            Bild hinzufügen
          </button>
        </div>
      </div>
    );
  }

  if (elementTypeId === 6) {
    const rows = (Array.isArray(embeddedConfig.rows) ? embeddedConfig.rows : []) as Array<Record<string, any>>;
    if (!editable) {
      return (
        <div className={embeddedBlockClassName}>
          {rows.length ? (
            <div className="form-block-list">
              {rows.map((row, index) => {
                const rowType = String(row.value_type ?? "text");
                const rowValue =
                  rowType === "participant"
                    ? participantNameById(row.participant_id)
                    : rowType === "participants"
                    ? embeddedParticipantSummary(row)
                    : rowType === "event"
                    ? eventLabelById(row.event_id)
                    : String(row.text_value ?? "").trim() || "—";
                return (
                  <div className="form-block-row" key={String(row.id ?? index)}>
                    <div className="field-label-inline">{String(row.label ?? `Zeile ${index + 1}`)}</div>
                    <div className="matrix-static-value">{rowValue}</div>
                    <div />
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="matrix-static-value">Leere Tabelle</div>
          )}
        </div>
      );
    }
    return (
      <div className={embeddedBlockClassName}>
        <div className="form-block-list">
          {rows.map((row, index) => (
            <div className="form-block-row" key={String(row.id ?? index)}>
              <input
                value={String(row.label ?? "")}
                onChange={(event) =>
                  updateEmbeddedConfig((current) => ({
                    ...current,
                    rows: rows.map((entry, entryIndex) =>
                      entryIndex === index ? { ...entry, label: event.target.value } : entry
                    ),
                  }))
                }
                onBlur={() => updateEmbeddedBlock((current) => current, true)}
                placeholder="Zeilenbezeichnung"
              />
              <div className="grid">
                <select
                  value={String(row.value_type ?? "text")}
                  onChange={(event) =>
                    updateEmbeddedConfig((current) => ({
                      ...current,
                      rows: rows.map((entry, entryIndex) =>
                        entryIndex === index
                          ? {
                              ...entry,
                              value_type: event.target.value,
                              text_value: event.target.value === "text" ? String(entry.text_value ?? "") : "",
                              participant_id: null,
                              participant_ids: [],
                              event_id: null,
                            }
                          : entry
                      ),
                    }), true)
                  }
                >
                  {EMBEDDED_FORM_VALUE_OPTIONS.map((option) => (
                    <option key={`embedded-form-type-${option.value}`} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                {String(row.value_type ?? "text") === "participant" ? (
                  <select
                    value={row.participant_id ?? ""}
                    onChange={(event) =>
                      updateEmbeddedConfig((current) => ({
                        ...current,
                        rows: rows.map((entry, entryIndex) =>
                          entryIndex === index ? { ...entry, participant_id: event.target.value ? Number(event.target.value) : null } : entry
                        ),
                      }), true)
                    }
                  >
                    <option value="">Teilnehmer waehlen</option>
                    {availableParticipants.map((participant) => (
                      <option key={participant.id} value={participant.id}>
                        {participant.display_name}
                      </option>
                    ))}
                  </select>
                ) : String(row.value_type ?? "text") === "participants" ? (
                  <button type="button" className="button-ghost form-participant-picker-button" onClick={() => openMultiParticipantPicker(row)}>
                    {embeddedParticipantSummary(row)}
                  </button>
                ) : String(row.value_type ?? "text") === "event" ? (
                  <select
                    value={row.event_id ?? ""}
                    onChange={(event) =>
                      updateEmbeddedConfig((current) => ({
                        ...current,
                        rows: rows.map((entry, entryIndex) =>
                          entryIndex === index ? { ...entry, event_id: event.target.value ? Number(event.target.value) : null } : entry
                        ),
                      }), true)
                    }
                  >
                    <option value="">Termin waehlen</option>
                    {sortedEvents.map((eventRow) => (
                      <option key={eventRow.id} value={eventRow.id}>
                        {formatDateRange(eventRow.event_date, eventRow.event_end_date)} · {eventRow.title}
                      </option>
                    ))}
                  </select>
                ) : (
                  <textarea
                    rows={1}
                    className="todo-input"
                    value={String(row.text_value ?? "")}
                    onChange={(event) =>
                      updateEmbeddedConfig((current) => ({
                        ...current,
                        rows: rows.map((entry, entryIndex) =>
                          entryIndex === index ? { ...entry, text_value: event.target.value } : entry
                        ),
                      }))
                    }
                    onBlur={() => updateEmbeddedBlock((current) => current, true)}
                    placeholder="Inhalt"
                  />
                )}
              </div>
              <button
                type="button"
                className="button-inline button-danger todo-delete"
                onClick={() =>
                  updateEmbeddedConfig((current) => ({
                    ...current,
                    rows: rows.filter((_, entryIndex) => entryIndex !== index),
                  }), true)
                }
              >
                Delete
              </button>
            </div>
          ))}
        </div>
        <div className="table-toolbar-actions">
          <button
            type="button"
            className="button-inline"
            onClick={() =>
              updateEmbeddedConfig((current) => ({
                ...current,
                rows: [...rows, createEmbeddedFormRow(nextEmbeddedItemId(rows, "form-row"))],
              }), true)
            }
          >
            Zeile hinzufügen
          </button>
        </div>
      </div>
    );
  }

  if (elementTypeId === 7) {
    const tagFilter = String(embeddedConfig.event_tag_filter ?? "").trim().toLowerCase();
    const columnTagFilter = embeddedConfig.event_use_column_tag_filter === true
      ? String(matrixColumn?.event_tag_filter || matrixColumn?.title || "").trim().toLowerCase() : "";
    const matchingEvents = sortedEvents.filter((eventRow) => {
      const effectiveEndDate = eventRow.event_end_date || eventRow.event_date;
      const matchesTag =
        (!tagFilter || (eventRow.tag ?? "").toLowerCase().includes(tagFilter)) &&
        (!columnTagFilter || (eventRow.tag ?? "").toLowerCase().includes(columnTagFilter));
      const matchesDate = embeddedConfig.event_only_from_protocol_date === false || !protocol.protocol_date || effectiveEndDate >= protocol.protocol_date;
      return matchesTag && matchesDate;
    });
    const embeddedEventDraftValue = (eventRow: EventSummary) => ({
      ...eventRow,
      ...(embeddedEventDrafts[eventRow.id] ?? {}),
    });
    return (
      <div className={embeddedBlockClassName}>
        {matchingEvents.length || editable || showNewEmbeddedEventRow ? (
          <div className="event-table-wrap">
            <table className="data-table event-table event-table-compact">
              <thead>
                <tr>
                  {embeddedEventColumns.showDate ? <th>Dat.</th> : null}
                  {embeddedEventColumns.showTag ? <th>Tag</th> : null}
                  {embeddedEventColumns.showTitle ? <th>Titel</th> : null}
                  {embeddedEventColumns.showDescription ? <th>Beschreibung</th> : null}
                  {embeddedEventColumns.showParticipantCount ? <th className="event-column-count">TN</th> : null}
                  {editable ? (
                    <th className="event-column-actions" aria-label="Aktionen">
                      <button
                        type="button"
                        className="button-ghost button-icon"
                        title="Terminzeile hinzufügen"
                        disabled={showNewEmbeddedEventRow || creatingEmbeddedEvent}
                        onClick={() => {
                          setShowNewEmbeddedEventRow(true);
                          setNewEmbeddedEventDraft((current) => {
                            const hasManualContent =
                              Boolean(current.title.trim()) ||
                              Boolean(current.description.trim()) ||
                              Boolean(current.event_end_date.trim()) ||
                              Number(current.participant_count || "0") > 0;
                            return hasManualContent
                              ? current
                              : createInlineProtocolEventDraft(protocol.protocol_date, forcedEmbeddedTag, embeddedEventColumns.showTitle);
                          });
                        }}
                      >
                        +
                      </button>
                    </th>
                  ) : null}
                </tr>
              </thead>
              <tbody>
                {showNewEmbeddedEventRow ? (
                  <tr className="event-row-new">
                    {embeddedEventColumns.showDate ? (
                      <td>
                        <div className={`event-date-fields${allowEmbeddedEndDate ? " event-date-fields-range" : ""}`}>
                          <input
                            type="date"
                            className="event-field-date"
                            value={newEmbeddedEventDraft.event_date}
                            disabled={creatingEmbeddedEvent}
                            onChange={(event) => patchNewEmbeddedEventDraft({ event_date: event.target.value })}
                          />
                          {allowEmbeddedEndDate ? (
                            <input
                              type="date"
                              className="event-field-date"
                              value={newEmbeddedEventDraft.event_end_date}
                              disabled={creatingEmbeddedEvent}
                              onChange={(event) => patchNewEmbeddedEventDraft({ event_end_date: event.target.value })}
                            />
                          ) : null}
                        </div>
                      </td>
                    ) : null}
                    {embeddedEventColumns.showTag ? (
                      <td>
                        <input
                          className="event-field-tag"
                          value={forcedEmbeddedTag || newEmbeddedEventDraft.tag}
                          readOnly={Boolean(forcedEmbeddedTag)}
                          disabled={creatingEmbeddedEvent}
                          onChange={(event) => patchNewEmbeddedEventDraft({ tag: event.target.value })}
                          placeholder="Tag"
                        />
                      </td>
                    ) : null}
                    {embeddedEventColumns.showTitle ? (
                      <td>
                        <input
                          className="event-field-title"
                          value={newEmbeddedEventDraft.title}
                          disabled={creatingEmbeddedEvent}
                          onChange={(event) => patchNewEmbeddedEventDraft({ title: event.target.value })}
                          placeholder="Titel"
                        />
                      </td>
                    ) : null}
                    {embeddedEventColumns.showDescription ? (
                      <td>
                        <input
                          className="event-field-description"
                          value={newEmbeddedEventDraft.description}
                          disabled={creatingEmbeddedEvent}
                          onChange={(event) => patchNewEmbeddedEventDraft({ description: event.target.value })}
                          placeholder="Beschreibung"
                        />
                      </td>
                    ) : null}
                    {embeddedEventColumns.showParticipantCount ? (
                      <td className="event-column-count">
                        <input
                          type="number"
                          className="event-field-count"
                          min="0"
                          value={newEmbeddedEventDraft.participant_count}
                          disabled={creatingEmbeddedEvent}
                          onChange={(event) => patchNewEmbeddedEventDraft({ participant_count: event.target.value })}
                          placeholder="TN"
                        />
                      </td>
                    ) : null}
                    {editable ? (
                      <td>
                        <div className="event-row-actions">
                          <button
                            type="button"
                            className="button-ghost button-icon button-icon-danger"
                            title="Neue Terminzeile verwerfen"
                            disabled={creatingEmbeddedEvent}
                            onClick={resetNewEmbeddedEventRow}
                          >
                            x
                          </button>
                        </div>
                      </td>
                    ) : null}
                  </tr>
                ) : null}
                {matchingEvents.map((eventRow) => {
                  const effectiveEndDate = eventRow.event_end_date || eventRow.event_date;
                  const isPast = !!protocol.protocol_date && effectiveEndDate < protocol.protocol_date;
                  const editableEventRow = embeddedEventDraftValue(eventRow);
                  return (
                    <tr key={eventRow.id} className={isPast && embeddedConfig.event_gray_past !== false ? "event-row-past" : ""}>
                      {embeddedEventColumns.showDate ? (
                        <td>
                          {editable ? (
                            <div className={`event-date-fields${allowEmbeddedEndDate ? " event-date-fields-range" : ""}`}>
                              <input
                                type="date"
                                className="event-field-date"
                                value={editableEventRow.event_date}
                                onChange={(event) => queueEmbeddedEventSave(eventRow, { event_date: event.target.value })}
                              />
                              {allowEmbeddedEndDate ? (
                                <input
                                  type="date"
                                  className="event-field-date"
                                  value={editableEventRow.event_end_date ?? ""}
                                  onChange={(event) => queueEmbeddedEventSave(eventRow, { event_end_date: event.target.value || null })}
                                />
                              ) : null}
                            </div>
                          ) : (
                            formatDateRange(eventRow.event_date, eventRow.event_end_date)
                          )}
                        </td>
                      ) : null}
                      {embeddedEventColumns.showTag ? (
                        <td>
                          {editable ? (
                            <input
                              className="event-field-tag"
                              value={editableEventRow.tag ?? forcedEmbeddedTag}
                              readOnly={Boolean(forcedEmbeddedTag)}
                              onChange={(event) => queueEmbeddedEventSave(eventRow, { tag: event.target.value || null })}
                            />
                          ) : (
                            eventRow.tag || "—"
                          )}
                        </td>
                      ) : null}
                      {embeddedEventColumns.showTitle ? (
                        <td>
                          {editable ? (
                            <input
                              className="event-field-title"
                              value={editableEventRow.title}
                              onChange={(event) => queueEmbeddedEventSave(eventRow, { title: event.target.value })}
                            />
                          ) : (
                            eventRow.title
                          )}
                        </td>
                      ) : null}
                      {embeddedEventColumns.showDescription ? (
                        <td>
                          {editable ? (
                            <input
                              className="event-field-description"
                              value={editableEventRow.description ?? ""}
                              onChange={(event) => queueEmbeddedEventSave(eventRow, { description: event.target.value || null })}
                            />
                          ) : (
                            eventRow.description || "—"
                          )}
                        </td>
                      ) : null}
                      {embeddedEventColumns.showParticipantCount ? (
                        <td className="event-column-count">
                          {editable ? (
                            <input
                              type="number"
                              className="event-field-count"
                              min="0"
                              value={editableEventRow.participant_count ?? 0}
                              onChange={(event) => queueEmbeddedEventSave(eventRow, { participant_count: Math.max(0, Number(event.target.value || "0")) })}
                            />
                          ) : (
                            eventRow.participant_count ?? 0
                          )}
                        </td>
                      ) : null}
                      {editable ? (
                        <td>
                          <div className="event-row-actions">
                            <button
                              type="button"
                              className="button-ghost button-icon button-icon-danger"
                              title="Termin löschen"
                              onClick={() => void deleteEvent(eventRow.id)}
                            >
                              x
                            </button>
                          </div>
                        </td>
                      ) : null}
                    </tr>
                  );
                })}
                {!matchingEvents.length && !showNewEmbeddedEventRow ? (
                  <tr>
                    <td
                      colSpan={
                        Number(embeddedEventColumns.showDate) +
                        Number(embeddedEventColumns.showTag) +
                        Number(embeddedEventColumns.showTitle) +
                        Number(embeddedEventColumns.showDescription) +
                        Number(embeddedEventColumns.showParticipantCount) +
                        Number(editable)
                      }
                    >
                      <span className="muted">Keine passenden Termine.</span>
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        ) : (
          <span className="muted">Keine passenden Termine</span>
        )}
      </div>
    );
  }

  if (elementTypeId === 8) {
    const bulletItems = (Array.isArray(embeddedConfig.bullet_items) ? embeddedConfig.bullet_items : []) as string[];
    if (!editable) {
      return (
        <div className={embeddedBlockClassName}>
          {bulletItems.length ? (
            <div className="matrix-static-list">
              {bulletItems.map((item, index) => (
                <div className="matrix-static-list-item" key={`embedded-bullet-${index}`}>{item || "Leerer Punkt"}</div>
              ))}
            </div>
          ) : (
            <div className="matrix-static-value">Keine Punkte</div>
          )}
        </div>
      );
    }
    return (
      <div className={embeddedBlockClassName}>
        <div className="todo-list">
          {bulletItems.map((item, index) => (
            <article className="todo-card todo-card-compact" key={`embedded-bullet-${index}`}>
              <div className="todo-toggle todo-toggle-done">•</div>
              <div className="todo-main todo-main-compact">
                <textarea
                  rows={1}
                  className="todo-input"
                  value={item}
                  onChange={(event) =>
                    updateEmbeddedConfig((current) => ({
                      ...current,
                      bullet_items: bulletItems.map((entry, entryIndex) => (entryIndex === index ? event.target.value : entry)),
                    }))
                  }
                  onBlur={() => updateEmbeddedBlock((current) => current, true)}
                />
              </div>
              <button
                type="button"
                className="button-inline button-danger todo-delete"
                onClick={() =>
                  updateEmbeddedConfig((current) => ({
                    ...current,
                    bullet_items: bulletItems.filter((_, entryIndex) => entryIndex !== index),
                  }), true)
                }
              >
                Delete
              </button>
            </article>
          ))}
        </div>
        <div className="todo-create todo-create-inline">
          <input value="" readOnly placeholder="Neuen Punkt hinzufügen" />
          <button
            type="button"
            onClick={() =>
              updateEmbeddedConfig((current) => ({
                ...current,
                bullet_items: [...bulletItems, ""],
              }), true)
            }
          >
            + Punkt
          </button>
        </div>
      </div>
    );
  }

  if (elementTypeId === 9) {
    const attendanceEntries = (Array.isArray(embeddedConfig.attendance_entries) ? embeddedConfig.attendance_entries : []) as Array<Record<string, any>>;
    if (!editable) {
      return (
        <div className={embeddedBlockClassName}>
          <div className="matrix-static-list">
            {availableParticipants.map((participant) => {
              const currentEntry = attendanceEntries.find((entry) => Number(entry.participant_id) === participant.id);
              return (
                <div className="matrix-static-list-item" key={`embedded-attendance-${participant.id}`}>
                  <strong>{participant.display_name}</strong>: {attendanceStatusLabel(String(currentEntry?.status ?? "absent"))}
                </div>
              );
            })}
          </div>
        </div>
      );
    }
    return (
      <div className={embeddedBlockClassName}>
        <div className="attendance-list">
          {availableParticipants.map((participant) => {
            const currentEntry = attendanceEntries.find((entry) => Number(entry.participant_id) === participant.id);
            const selectedStatus = String(currentEntry?.status ?? "absent");
            return (
              <div className="attendance-row" key={`embedded-attendance-${participant.id}`}>
                <strong>{participant.display_name}</strong>
                <div className="segment-control attendance-segment-control">
                  {ATTENDANCE_OPTIONS.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      className={`segment-button attendance-segment-button${selectedStatus === option.value ? " segment-button-active" : ""}`}
                      onClick={() =>
                        updateEmbeddedConfig((current) => ({
                          ...current,
                          attendance_entries: [
                            ...attendanceEntries.filter((entry) => Number(entry.participant_id) !== participant.id),
                            {
                              participant_id: participant.id,
                              participant_name: participant.display_name,
                              status: option.value,
                            },
                          ],
                        }), true)
                      }
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  if (elementTypeId === 10) {
    if (!editable) {
      return (
        <div className={embeddedBlockClassName}>
          <div className="matrix-static-value">
            {String(embeddedConfig.session_label ?? "").trim() || "Naechste Sitzung"}
            {String(embeddedConfig.selected_date ?? "").trim() ? `: ${formatShortDate(String(embeddedConfig.selected_date))}` : ""}
          </div>
        </div>
      );
    }
    return (
      <div className={embeddedBlockClassName}>
        <div className="two-col">
          <label className="field-stack">
            <span className="field-label">Bezeichnung</span>
            <input
              value={String(embeddedConfig.session_label ?? "")}
              onChange={(event) =>
                updateEmbeddedConfig((current) => ({
                  ...current,
                  session_label: event.target.value,
                }))
              }
              onBlur={() => updateEmbeddedBlock((current) => current, true)}
              placeholder="Naechste Sitzung"
            />
          </label>
          <label className="field-stack">
            <span className="field-label">Datum</span>
            <input
              type="date"
              value={String(embeddedConfig.selected_date ?? "")}
              onChange={(event) =>
                updateEmbeddedConfig((current) => ({
                  ...current,
                  selected_date: event.target.value || null,
                }), true)
              }
            />
          </label>
        </div>
      </div>
    );
  }

  return <span className="muted">Dieser Zell-Blocktyp ist noch nicht verfügbar.</span>;
}

export function ProtocolEditor({
  protocol,
  initialElements,
  initialTodos,
  initialImages,
  availableParticipants,
  availableEvents,
  availableLists,
  initialListEntries,
  availableTemplates,
}: ProtocolEditorProps) {
  const [elements, setElements] = useState(initialElements);
  const [events, setEvents] = useState(availableEvents);
  const [listEntriesByDefinition, setListEntriesByDefinition] = useState<Record<number, StructuredListEntry[]>>(initialListEntries);
  const [todosByBlock, setTodosByBlock] = useState<Record<number, ProtocolTodo[]>>(initialTodos);
  const [imagesByBlock, setImagesByBlock] = useState<Record<number, ProtocolImage[]>>(initialImages);
  const [textDrafts, setTextDrafts] = useState<Record<number, string>>(
    Object.fromEntries(
      initialElements.flatMap((element) =>
        element.blocks
          .filter((block) => block.element_type_code === "text" || block.element_type_code === "static_text")
          .map((block) => [block.id, block.text_content ?? ""])
      )
    )
  );
  const [newTodoTask, setNewTodoTask] = useState<Record<number, string>>({});
  const [newEventDrafts, setNewEventDrafts] = useState<Record<number, ProtocolEventDraft>>({});
  const [selectedFiles, setSelectedFiles] = useState<Record<number, File | null>>({});
  const [blockStatus, setBlockStatus] = useState<Record<number, SaveState>>({});
  const [selectedElementId, setSelectedElementId] = useState<number | null>(initialElements[0]?.id ?? null);
  const [draggedElementId, setDraggedElementId] = useState<number | null>(null);
  const timers = useRef<Record<number, number>>({});
  const shouldScrollToElementRef = useRef(false);
  const navRef = useRef<HTMLElement | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    return () => {
      Object.values(timers.current).forEach((timerId) => window.clearTimeout(timerId));
    };
  }, []);

  const visibleElements = useMemo(
    () =>
      [...elements]
        .filter((element) => element.is_visible_snapshot)
        .map((element) => ({
          ...element,
          blocks: [...element.blocks]
            .filter((block) => block.is_visible_snapshot && block.element_type_code !== "display")
            .sort((left, right) => left.sort_index - right.sort_index)
        }))
        .filter((element) => element.blocks.length > 0)
        .sort((left, right) => left.sort_index - right.sort_index),
    [elements]
  );

  const selectedElement = useMemo(
    () => visibleElements.find((element) => element.id === selectedElementId) ?? null,
    [selectedElementId, visibleElements]
  );
  const listDefinitionsById = useMemo(
    () => new Map(availableLists.map((listDefinition) => [listDefinition.id, listDefinition])),
    [availableLists]
  );
  const selectedElementIndex = useMemo(
    () => visibleElements.findIndex((element) => element.id === selectedElementId),
    [selectedElementId, visibleElements]
  );

  function setStatus(protocolElementBlockId: number, status: SaveState) {
    setBlockStatus((current) => ({ ...current, [protocolElementBlockId]: status }));
  }

  function focusElement(protocolElementId: number) {
    shouldScrollToElementRef.current = true;
    setSelectedElementId(protocolElementId);
  }

  useEffect(() => {
    if (!selectedElementId && visibleElements[0]) {
      setSelectedElementId(visibleElements[0].id);
      return;
    }
    if (selectedElementId && !visibleElements.some((element) => element.id === selectedElementId)) {
      setSelectedElementId(visibleElements[0]?.id ?? null);
    }
  }, [selectedElementId, visibleElements]);

  useEffect(() => {
    if (!selectedElementId || !shouldScrollToElementRef.current) {
      return;
    }

    shouldScrollToElementRef.current = false;

    window.requestAnimationFrame(() => {
      // Scroll panel to top (new element replaces old one)
      const panel = panelRef.current;
      if (panel) {
        panel.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
      } else {
        const section = document.getElementById(`protocol-element-${selectedElementId}`);
        section?.scrollIntoView({ behavior: "smooth", block: "start" });
      }

      // Center active nav item
      const nav = navRef.current;
      if (nav) {
        const activeItem = nav.querySelector<HTMLElement>(".editor-nav-item-active");
        if (activeItem) {
          const navRect = nav.getBoundingClientRect();
          const itemRect = activeItem.getBoundingClientRect();
          const target = nav.scrollTop + itemRect.top - navRect.top - (nav.clientHeight - activeItem.clientHeight) / 2;
          nav.scrollTo({ top: target, behavior: "smooth" });
        }
      }

      window.setTimeout(() => {
        const section = document.getElementById(`protocol-element-${selectedElementId}`);
        if (!section) return;
        const firstEditable = section.querySelector<HTMLElement>(
          'textarea:not([readonly]), input:not([readonly]):not([type="file"])'
        );
        firstEditable?.focus();
      }, 120);
    });
  }, [selectedElementId]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) {
        return;
      }
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") {
        return;
      }
      if (!visibleElements.length) {
        return;
      }
      const currentIndex = visibleElements.findIndex((element) => element.id === selectedElementId);
      const safeIndex = currentIndex === -1 ? 0 : currentIndex;
      const nextIndex =
        event.key === "ArrowDown"
          ? Math.min(visibleElements.length - 1, safeIndex + 1)
          : Math.max(0, safeIndex - 1);
      if (nextIndex !== safeIndex) {
        event.preventDefault();
        focusElement(visibleElements[nextIndex].id);
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedElementId, visibleElements]);

  async function reorderElements(sourceId: number, targetId: number) {
    if (sourceId === targetId) return;
    const ordered = [...elements].sort((left, right) => left.sort_index - right.sort_index);
    const sourceIndex = ordered.findIndex((item) => item.id === sourceId);
    const targetIndex = ordered.findIndex((item) => item.id === targetId);
    if (sourceIndex === -1 || targetIndex === -1) {
      return;
    }
    const [moved] = ordered.splice(sourceIndex, 1);
    ordered.splice(targetIndex, 0, moved);
    const resequenced = resequenceProtocolElements(ordered);
    const nextStatus: Record<number, SaveState> = {};
    resequenced.forEach((element) => {
      element.blocks.forEach((block) => {
        nextStatus[block.id] = "saving";
      });
    });
    setBlockStatus((current) => ({ ...current, ...nextStatus }));
    try {
      const updated = await Promise.all(
        resequenced.map((element) =>
          browserApiFetch<ProtocolElement>(`/api/protocol-elements/${element.id}`, {
            method: "PATCH",
            body: JSON.stringify({ sort_index: element.sort_index, section_order_snapshot: element.sort_index })
          })
        )
      );
      const updatedById = new Map(updated.map((element) => [element.id, element]));
      setElements((current) =>
        current
          .map((element) => {
            const patch = updatedById.get(element.id);
            return patch ? { ...element, sort_index: patch.sort_index, section_order_snapshot: patch.section_order_snapshot } : element;
          })
          .sort((left, right) => left.sort_index - right.sort_index)
      );
      setBlockStatus((current) => {
        const next = { ...current };
        resequenced.forEach((element) => {
          element.blocks.forEach((block) => {
            next[block.id] = "saved";
          });
        });
        return next;
      });
    } catch {
      setBlockStatus((current) => {
        const next = { ...current };
        resequenced.forEach((element) => {
          element.blocks.forEach((block) => {
            next[block.id] = "error";
          });
        });
        return next;
      });
    }
  }

  function updateBlockInState(blockId: number, updater: (current: ProtocolElement["blocks"][number]) => ProtocolElement["blocks"][number]) {
    setElements((current) =>
      current.map((element) => ({
        ...element,
        blocks: element.blocks.map((block) => (block.id === blockId ? updater(block) : block))
      }))
    );
  }

  async function saveBlockConfiguration(blockId: number, configurationSnapshotJson: Record<string, unknown>) {
    setStatus(blockId, "saving");
    updateBlockInState(blockId, (block) => ({ ...block, configuration_snapshot_json: configurationSnapshotJson }));
    try {
      const updated = await browserApiFetch<ProtocolElement["blocks"][number]>(`/api/protocol-element-blocks/${blockId}`, {
        method: "PATCH",
        body: JSON.stringify({ configuration_snapshot_json: configurationSnapshotJson }),
      });
      updateBlockInState(blockId, (block) => ({
        ...block,
        configuration_snapshot_json: updated.configuration_snapshot_json,
      }));
      setStatus(blockId, "saved");
    } catch {
      setStatus(blockId, "error");
    }
  }

  function handleTextChange(protocolElementBlockId: number, content: string) {
    setTextDrafts((current) => ({ ...current, [protocolElementBlockId]: content }));
    setStatus(protocolElementBlockId, "saving");

    if (timers.current[protocolElementBlockId]) {
      window.clearTimeout(timers.current[protocolElementBlockId]);
    }

    timers.current[protocolElementBlockId] = window.setTimeout(async () => {
      try {
        await browserApiFetch(`/api/protocol-element-blocks/${protocolElementBlockId}/text`, {
          method: "PUT",
          body: JSON.stringify({ content })
        });
        updateBlockInState(protocolElementBlockId, (block) => ({ ...block, text_content: content }));
        setStatus(protocolElementBlockId, "saved");
      } catch {
        setStatus(protocolElementBlockId, "error");
      }
    }, 700);
  }

  async function addTodo(protocolElementBlockId: number) {
    const task = newTodoTask[protocolElementBlockId]?.trim();
    if (!task) return;
    setStatus(protocolElementBlockId, "saving");
    try {
      const created = await browserApiFetch<ProtocolTodo>(`/api/protocol-element-blocks/${protocolElementBlockId}/todos`, {
        method: "POST",
        body: JSON.stringify({ task, todo_status_id: TODO_STATUS.open, created_by: null })
      });
      setTodosByBlock((current) => ({
        ...current,
        [protocolElementBlockId]: [...(current[protocolElementBlockId] ?? []), created].sort((left, right) => left.sort_index - right.sort_index)
      }));
      setNewTodoTask((current) => ({ ...current, [protocolElementBlockId]: "" }));
      setStatus(protocolElementBlockId, "saved");
    } catch {
      setStatus(protocolElementBlockId, "error");
    }
  }

  async function updateTodo(protocolElementBlockId: number, todoId: number, patch: Partial<ProtocolTodo>) {
    setStatus(protocolElementBlockId, "saving");
    try {
      const updated = await browserApiFetch<ProtocolTodo>(`/api/protocol-todos/${todoId}`, {
        method: "PATCH",
        body: JSON.stringify(patch)
      });
      setTodosByBlock((current) => ({
        ...current,
        [protocolElementBlockId]: (current[protocolElementBlockId] ?? []).map((todo) => (todo.id === todoId ? updated : todo))
      }));
      setStatus(protocolElementBlockId, "saved");
    } catch {
      setStatus(protocolElementBlockId, "error");
    }
  }

  async function deleteTodo(protocolElementBlockId: number, todoId: number) {
    setStatus(protocolElementBlockId, "saving");
    try {
      await browserApiFetch(`/api/protocol-todos/${todoId}`, { method: "DELETE" });
      setTodosByBlock((current) => ({
        ...current,
        [protocolElementBlockId]: (current[protocolElementBlockId] ?? []).filter((todo) => todo.id !== todoId)
      }));
      setStatus(protocolElementBlockId, "saved");
    } catch {
      setStatus(protocolElementBlockId, "error");
    }
  }

  async function uploadImage(protocolElementBlockId: number) {
    const file = selectedFiles[protocolElementBlockId];
    if (!file) return;
    setStatus(protocolElementBlockId, "saving");
    try {
      const body = new FormData();
      body.append("file", file);
      const created = await browserApiFetch<ProtocolImage>(`/api/protocol-element-blocks/${protocolElementBlockId}/images`, {
        method: "POST",
        body
      });
      setImagesByBlock((current) => ({
        ...current,
        [protocolElementBlockId]: [...(current[protocolElementBlockId] ?? []), created].sort((left, right) => left.sort_index - right.sort_index)
      }));
      setSelectedFiles((current) => ({ ...current, [protocolElementBlockId]: null }));
      setStatus(protocolElementBlockId, "saved");
    } catch {
      setStatus(protocolElementBlockId, "error");
    }
  }

  async function deleteImage(protocolElementBlockId: number, imageId: number) {
    setStatus(protocolElementBlockId, "saving");
    try {
      await browserApiFetch(`/api/protocol-images/${imageId}`, { method: "DELETE" });
      setImagesByBlock((current) => ({
        ...current,
        [protocolElementBlockId]: (current[protocolElementBlockId] ?? []).filter((image) => image.id !== imageId)
      }));
      setStatus(protocolElementBlockId, "saved");
    } catch {
      setStatus(protocolElementBlockId, "error");
    }
  }

  async function createEventFromBlock(protocolElementBlockId: number, blockConfig: Record<string, any>, draftOverride?: ProtocolEventDraft) {
    const configuredTag = String(blockConfig.event_tag_filter ?? "").trim();
    const allowEndDate = blockConfig.event_allow_end_date === true;
    const draft = draftOverride ?? newEventDrafts[protocolElementBlockId] ?? createProtocolEventDraft(protocol.protocol_date, configuredTag);
    if (!draft.event_date.trim() || !draft.title.trim()) {
      setStatus(protocolElementBlockId, "error");
      return false;
    }
    setStatus(protocolElementBlockId, "saving");
    try {
      const created = await browserApiFetch<EventSummary>("/api/events", {
        method: "POST",
        body: JSON.stringify({
          event_date: draft.event_date,
          event_end_date: allowEndDate ? draft.event_end_date || null : null,
          tag: configuredTag || draft.tag || null,
          title: draft.title,
          description: draft.description || null,
          participant_count: Math.max(0, Number(draft.participant_count || "0")),
        }),
      });
      setEvents((current) => [...current, created]);
      if (!draftOverride) {
        setNewEventDrafts((current) => ({
          ...current,
          [protocolElementBlockId]: createProtocolEventDraft(protocol.protocol_date, configuredTag),
        }));
      }
      setStatus(protocolElementBlockId, "saved");
      return true;
    } catch {
      setStatus(protocolElementBlockId, "error");
      return false;
    }
  }

  async function updateEventFromBlock(protocolElementBlockId: number, eventId: number, patch: Partial<EventSummary>) {
    setStatus(protocolElementBlockId, "saving");
    try {
      const updated = await browserApiFetch<EventSummary>(`/api/events/${eventId}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      setEvents((current) => current.map((event) => (event.id === eventId ? updated : event)));
      setStatus(protocolElementBlockId, "saved");
      return true;
    } catch {
      setStatus(protocolElementBlockId, "error");
      return false;
    }
  }

  async function deleteEventFromBlock(protocolElementBlockId: number, eventId: number) {
    setStatus(protocolElementBlockId, "saving");
    try {
      await browserApiFetch(`/api/events/${eventId}`, { method: "DELETE" });
      setEvents((current) => current.filter((event) => event.id !== eventId));
      setStatus(protocolElementBlockId, "saved");
    } catch {
      setStatus(protocolElementBlockId, "error");
    }
  }

  async function createListEntryFromBlock(
    protocolElementBlockId: number,
    listDefinitionId: number,
    payload: { sort_index: number; column_one_value: Record<string, unknown>; column_two_value: Record<string, unknown> }
  ) {
    setStatus(protocolElementBlockId, "saving");
    try {
      const created = await browserApiFetch<StructuredListEntry>(`/api/lists/${listDefinitionId}/entries`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setListEntriesByDefinition((current) => ({
        ...current,
        [listDefinitionId]: [...(current[listDefinitionId] ?? []), created].sort(
          (left, right) => left.sort_index - right.sort_index || left.id - right.id
        ),
      }));
      setStatus(protocolElementBlockId, "saved");
      return true;
    } catch {
      setStatus(protocolElementBlockId, "error");
      return false;
    }
  }

  async function updateListEntryFromBlock(
    protocolElementBlockId: number,
    listDefinitionId: number,
    entryId: number,
    payload: Partial<{
      sort_index: number;
      column_one_value: Record<string, unknown>;
      column_two_value: Record<string, unknown>;
    }>
  ) {
    setStatus(protocolElementBlockId, "saving");
    try {
      const updated = await browserApiFetch<StructuredListEntry>(`/api/list-entries/${entryId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      setListEntriesByDefinition((current) => ({
        ...current,
        [listDefinitionId]: (current[listDefinitionId] ?? []).map((entry) => (entry.id === entryId ? updated : entry)),
      }));
      setStatus(protocolElementBlockId, "saved");
      return true;
    } catch {
      setStatus(protocolElementBlockId, "error");
      return false;
    }
  }

  async function deleteListEntryFromBlock(protocolElementBlockId: number, listDefinitionId: number, entryId: number) {
    setStatus(protocolElementBlockId, "saving");
    try {
      await browserApiFetch(`/api/list-entries/${entryId}`, { method: "DELETE" });
      setListEntriesByDefinition((current) => ({
        ...current,
        [listDefinitionId]: (current[listDefinitionId] ?? []).filter((entry) => entry.id !== entryId),
      }));
      setStatus(protocolElementBlockId, "saved");
    } catch {
      setStatus(protocolElementBlockId, "error");
    }
  }

  return (
    <div className="grid">
      <div className="status-row">
        <span className="pill">{protocol.protocol_number}</span>
        <span className="pill">Protocol status: {protocolStatusLabel(protocol.status)}</span>
        <span className="pill">Autosave per block</span>
      </div>

      <div className="editor-shell">
        <aside className="editor-nav" ref={navRef}>
          <DataToolbar title="Protocol navigator" description="Choose a complete point, then edit all blocks inside it together. Arrow up/down jumps to the next point." />
          {visibleElements.map((element) => (
            <div
              className={`editor-nav-section${draggedElementId === element.id ? " editor-nav-section-dragging" : ""}`}
              key={element.id}
              draggable
              onDragStart={() => setDraggedElementId(element.id)}
              onDragEnd={() => setDraggedElementId(null)}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                const sourceId = draggedElementId;
                setDraggedElementId(null);
                if (sourceId) {
                  void reorderElements(sourceId, element.id);
                }
              }}
            >
              <button
                type="button"
                className={`editor-nav-item editor-nav-item-group${selectedElementId === element.id ? " editor-nav-item-active" : ""}`}
                onClick={() => focusElement(element.id)}
                title={element.section_name_snapshot}
              >
                <span className="editor-nav-index">{visibleElements.findIndex((item) => item.id === element.id) + 1}</span>
                <strong className="editor-nav-label">{element.section_name_snapshot}</strong>
                <span className="muted editor-nav-subtitle">
                  {element.blocks.map((block) => visibleBlockTitle(block)).filter(Boolean).join(" · ")}
                </span>
                <span className="muted editor-nav-count">
                  {element.blocks.length} Block{element.blocks.length === 1 ? "" : "e"}
                </span>
                <div className="table-pill-wrap editor-nav-pill-wrap">
                  {element.blocks.map((block) => (
                    <span className="pill" key={block.id}>
                      {visibleBlockTitle(block) ?? "Ohne eigenen Titel"}
                    </span>
                  ))}
                </div>
                <div className="status-row">
                  <span className="pill">{elementSaveState(element, blockStatus)}</span>
                </div>
              </button>
            </div>
          ))}
        </aside>

        <article className="editor-panel" ref={panelRef}>
          {selectedElement ? (
            <FocusedElementEditor
              element={selectedElement}
              elementIndex={selectedElementIndex}
              blockStatus={blockStatus}
              textDrafts={textDrafts}
              todosByBlock={todosByBlock}
              imagesByBlock={imagesByBlock}
              newTodoTask={newTodoTask}
              browserApiBaseUrl={browserApiBaseUrl}
              protocol={protocol}
              availableParticipants={availableParticipants}
              availableEvents={events}
              availableTemplates={availableTemplates}
              newEventDrafts={newEventDrafts}
              selectedFiles={selectedFiles}
              setTodosByBlock={setTodosByBlock}
              setNewEventDrafts={setNewEventDrafts}
              setSelectedFiles={setSelectedFiles}
              setNewTodoTask={setNewTodoTask}
              saveBlockConfiguration={saveBlockConfiguration}
              updateBlockInState={updateBlockInState}
              handleTextChange={handleTextChange}
              hasNextElement={selectedElementIndex >= 0 && selectedElementIndex < visibleElements.length - 1}
              onNextElement={() => {
                const nextElement = visibleElements[selectedElementIndex + 1];
                if (nextElement) {
                  focusElement(nextElement.id);
                }
              }}
              addTodo={addTodo}
              updateTodo={updateTodo}
              deleteTodo={deleteTodo}
              createEventFromBlock={createEventFromBlock}
              updateEventFromBlock={updateEventFromBlock}
              deleteEventFromBlock={deleteEventFromBlock}
              uploadImage={uploadImage}
              deleteImage={deleteImage}
              listDefinitionsById={listDefinitionsById}
              listEntriesByDefinition={listEntriesByDefinition}
              createListEntryFromBlock={createListEntryFromBlock}
              updateListEntryFromBlock={updateListEntryFromBlock}
              deleteListEntryFromBlock={deleteListEntryFromBlock}
            />
          ) : (
            <div className="editor-panel-empty">
              <div>
                <div className="eyebrow">No point selected</div>
                <h3>Choose a point from the navigator</h3>
                <p>Each point groups all blocks from one element, so text, todos and images stay together.</p>
              </div>
            </div>
          )}
        </article>
      </div>
    </div>
  );
}

function FocusedElementEditor({
  element,
  elementIndex,
  blockStatus,
  textDrafts,
  todosByBlock,
  imagesByBlock,
  newTodoTask,
  browserApiBaseUrl,
  protocol,
  availableParticipants,
  availableEvents,
  availableTemplates,
  newEventDrafts,
  selectedFiles,
  setTodosByBlock,
  setNewEventDrafts,
  setSelectedFiles,
  setNewTodoTask,
  saveBlockConfiguration,
  updateBlockInState,
  handleTextChange,
  hasNextElement,
  onNextElement,
  addTodo,
  updateTodo,
  deleteTodo,
  createEventFromBlock,
  updateEventFromBlock,
  deleteEventFromBlock,
  uploadImage,
  deleteImage,
  listDefinitionsById,
  listEntriesByDefinition,
  createListEntryFromBlock,
  updateListEntryFromBlock,
  deleteListEntryFromBlock
}: {
  element: ProtocolElement;
  elementIndex: number;
  blockStatus: Record<number, SaveState>;
  textDrafts: Record<number, string>;
  todosByBlock: Record<number, ProtocolTodo[]>;
  imagesByBlock: Record<number, ProtocolImage[]>;
  newTodoTask: Record<number, string>;
  browserApiBaseUrl: string;
  protocol: ProtocolSummary;
  availableParticipants: ParticipantSummary[];
  availableEvents: EventSummary[];
  availableTemplates: TemplateSummary[];
  newEventDrafts: Record<number, ProtocolEventDraft>;
  selectedFiles: Record<number, File | null>;
  setTodosByBlock: Dispatch<SetStateAction<Record<number, ProtocolTodo[]>>>;
  setNewEventDrafts: Dispatch<SetStateAction<Record<number, ProtocolEventDraft>>>;
  setSelectedFiles: Dispatch<SetStateAction<Record<number, File | null>>>;
  setNewTodoTask: Dispatch<SetStateAction<Record<number, string>>>;
  saveBlockConfiguration: (blockId: number, configurationSnapshotJson: Record<string, unknown>) => Promise<void>;
  updateBlockInState: (blockId: number, updater: (current: ProtocolElement["blocks"][number]) => ProtocolElement["blocks"][number]) => void;
  handleTextChange: (protocolElementBlockId: number, content: string) => void;
  hasNextElement: boolean;
  onNextElement: () => void;
  addTodo: (protocolElementBlockId: number) => Promise<void>;
  updateTodo: (protocolElementBlockId: number, todoId: number, patch: Partial<ProtocolTodo>) => Promise<void>;
  deleteTodo: (protocolElementBlockId: number, todoId: number) => Promise<void>;
  createEventFromBlock: (protocolElementBlockId: number, blockConfig: Record<string, any>, draftOverride?: ProtocolEventDraft) => Promise<boolean>;
  updateEventFromBlock: (protocolElementBlockId: number, eventId: number, patch: Partial<EventSummary>) => Promise<boolean>;
  deleteEventFromBlock: (protocolElementBlockId: number, eventId: number) => Promise<void>;
  uploadImage: (protocolElementBlockId: number) => Promise<void>;
  deleteImage: (protocolElementBlockId: number, imageId: number) => Promise<void>;
  listDefinitionsById: Map<number, StructuredListDefinition>;
  listEntriesByDefinition: Record<number, StructuredListEntry[]>;
  createListEntryFromBlock: (protocolElementBlockId: number, listDefinitionId: number, payload: { sort_index: number; column_one_value: Record<string, unknown>; column_two_value: Record<string, unknown> }) => Promise<boolean>;
  updateListEntryFromBlock: (protocolElementBlockId: number, listDefinitionId: number, entryId: number, payload: Partial<{ sort_index: number; column_one_value: Record<string, unknown>; column_two_value: Record<string, unknown> }>) => Promise<boolean>;
  deleteListEntryFromBlock: (protocolElementBlockId: number, listDefinitionId: number, entryId: number) => Promise<void>;
}) {
  const router = useRouter();
  const sectionRef = useRef<HTMLElement | null>(null);
  const [multiParticipantPicker, setMultiParticipantPicker] = useState<{
    kind: "form" | "matrix" | "embedded_form";
    blockId: number;
    rowId: string;
    rowLabel: string;
    selectedIds: number[];
    columnId?: string;
    embeddedRowId?: string;
  } | null>(null);
  const [multiParticipantSearch, setMultiParticipantSearch] = useState("");
  const [eventDrafts, setEventDrafts] = useState<Record<number, Partial<EventSummary>>>({});
  const [openNewEventRows, setOpenNewEventRows] = useState<Record<number, boolean>>({});
  const [creatingNewEventRows, setCreatingNewEventRows] = useState<Record<number, boolean>>({});
  const eventAutosaveTimers = useRef<Record<number, number>>({});
  const newEventCreateTimers = useRef<Record<number, number>>({});
  const upcomingEvents = useMemo(
    () => [...availableEvents].sort((left, right) => left.event_date.localeCompare(right.event_date)).slice(0, 8),
    [availableEvents]
  );
  const sortedAvailableEvents = useMemo(
    () => [...availableEvents].sort((left, right) => compareIsoDate(left.event_date, right.event_date)),
    [availableEvents]
  );
  const filteredParticipants = useMemo(() => {
    const query = multiParticipantSearch.trim().toLowerCase();
    if (!query) {
      return availableParticipants;
    }
    return availableParticipants.filter((participant) => {
      const haystack = [
        participant.display_name,
        participant.first_name ?? "",
        participant.last_name ?? "",
        participant.email ?? "",
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    });
  }, [availableParticipants, multiParticipantSearch]);

  useEffect(() => {
    return () => {
      Object.values(eventAutosaveTimers.current).forEach((timerId) => window.clearTimeout(timerId));
      Object.values(newEventCreateTimers.current).forEach((timerId) => window.clearTimeout(timerId));
    };
  }, []);

  function dueMenuLabel(todo: ProtocolTodo) {
    if (todo.due_marker === "next_session") {
      return todo.resolved_due_date ? `${formatShortDate(todo.resolved_due_date)} (Naechste Sitzung)` : "Naechste Sitzung";
    }
    if (todo.due_event_id) {
      const label = todo.resolved_due_label ?? "Termin";
      return todo.resolved_due_date ? `${formatShortDate(todo.resolved_due_date)} (${label})` : label;
    }
    if (todo.due_date) {
      return formatShortDate(todo.due_date);
    }
    return "Kein Enddatum";
  }

  function autoResizeTodoField(target: HTMLTextAreaElement) {
    target.style.height = "0px";
    target.style.height = `${Math.max(40, target.scrollHeight)}px`;
  }

  function setBlockConfigLocal(blockId: number, nextConfig: Record<string, unknown>) {
    updateBlockInState(blockId, (current) => ({ ...current, configuration_snapshot_json: nextConfig }));
  }

  function patchBlockConfigValue(blockId: number, key: string, value: unknown, currentConfig: Record<string, unknown>) {
    const nextConfig = { ...currentConfig, [key]: value };
    setBlockConfigLocal(blockId, nextConfig);
    void saveBlockConfiguration(blockId, nextConfig);
  }

  function openMultiParticipantPicker(blockId: number, rowIndex: number, row: Record<string, any>) {
    setMultiParticipantSearch("");
    setMultiParticipantPicker({
      kind: "form",
      blockId,
      rowId: String(row.id ?? rowIndex),
      rowLabel: String(row.label ?? `Feld ${rowIndex + 1}`),
      selectedIds: Array.isArray(row.participant_ids) ? row.participant_ids.map(Number) : [],
    });
  }

  function openMatrixParticipantPicker(
    blockId: number,
    columnId: string,
    row: Record<string, any>
  ) {
    const selectedIds = Array.isArray(row.participant_ids) ? row.participant_ids.map(Number) : [];
    setMultiParticipantSearch("");
    setMultiParticipantPicker({
      kind: "matrix",
      blockId,
      rowId: String(row.row_id ?? row.id ?? ""),
      rowLabel: String(row.label ?? "Teilnehmer"),
      selectedIds,
      columnId,
    });
  }

  function openEmbeddedFormParticipantPicker(
    blockId: number,
    columnId: string,
    matrixRowId: string,
    matrixRowLabel: string,
    embeddedRow: Record<string, any>
  ) {
    setMultiParticipantSearch("");
    setMultiParticipantPicker({
      kind: "embedded_form",
      blockId,
      rowId: matrixRowId,
      rowLabel: `${matrixRowLabel} · ${String(embeddedRow.label ?? "Teilnehmer")}`,
      selectedIds: Array.isArray(embeddedRow.participant_ids) ? embeddedRow.participant_ids.map(Number) : [],
      columnId,
      embeddedRowId: String(embeddedRow.id ?? ""),
    });
  }

  function toggleMultiParticipantSelection(participantId: number) {
    setMultiParticipantPicker((current) => {
      if (!current) {
        return current;
      }
      return {
        ...current,
        selectedIds: current.selectedIds.includes(participantId)
          ? current.selectedIds.filter((id) => id !== participantId)
          : [...current.selectedIds, participantId],
      };
    });
  }

  function multiParticipantSummary(row: Record<string, any>) {
    const selectedIds = Array.isArray(row.participant_ids) ? row.participant_ids.map(Number) : [];
    if (!selectedIds.length) {
      return "Teilnehmer waehlen";
    }
    const selectedParticipants = availableParticipants.filter((participant) => selectedIds.includes(participant.id));
    if (!selectedParticipants.length) {
      return `${selectedIds.length} ausgewaehlt`;
    }
    if (selectedParticipants.length === 1) {
      return selectedParticipants[0].display_name;
    }
    if (selectedParticipants.length === 2) {
      return `${selectedParticipants[0].display_name}, ${selectedParticipants[1].display_name}`;
    }
    return `${selectedParticipants[0].display_name} + ${selectedParticipants.length - 1}`;
  }

  function applyMultiParticipantSelection(currentBlockId: number, currentConfig: Record<string, unknown>) {
    if (!multiParticipantPicker || multiParticipantPicker.blockId !== currentBlockId) {
      return;
    }
    if (multiParticipantPicker.kind === "form") {
      const nextRows = [...((Array.isArray(currentConfig.rows) ? currentConfig.rows : []) as Array<Record<string, any>>)];
      const targetIndex = nextRows.findIndex((row) => String(row.id ?? "") === multiParticipantPicker.rowId);
      if (targetIndex === -1) {
        return;
      }
      nextRows[targetIndex] = {
        ...nextRows[targetIndex],
        participant_ids: [...multiParticipantPicker.selectedIds],
      };
      void saveBlockConfiguration(currentBlockId, { ...currentConfig, rows: nextRows });
    } else if (multiParticipantPicker.kind === "matrix") {
      const nextColumns = [...((Array.isArray(currentConfig.columns) ? currentConfig.columns : []) as Array<Record<string, any>>)];
      const targetColumnIndex = nextColumns.findIndex((column) => String(column.id ?? "") === String(multiParticipantPicker.columnId ?? ""));
      if (targetColumnIndex === -1) {
        return;
      }
      const targetColumn = nextColumns[targetColumnIndex];
      const currentValues = asObject(targetColumn.values);
      nextColumns[targetColumnIndex] = {
        ...targetColumn,
        values: {
          ...currentValues,
          [multiParticipantPicker.rowId]: {
            ...asObject(currentValues[multiParticipantPicker.rowId]),
            participant_ids: [...multiParticipantPicker.selectedIds],
          },
        },
      };
      void saveBlockConfiguration(currentBlockId, { ...currentConfig, columns: nextColumns });
    } else {
      const nextColumns = [...((Array.isArray(currentConfig.columns) ? currentConfig.columns : []) as Array<Record<string, any>>)];
      const targetColumnIndex = nextColumns.findIndex((column) => String(column.id ?? "") === String(multiParticipantPicker.columnId ?? ""));
      if (targetColumnIndex === -1) {
        return;
      }
      const targetColumn = nextColumns[targetColumnIndex];
      const currentValues = asObject(targetColumn.values);
      const targetCell = asObject(currentValues[multiParticipantPicker.rowId]);
      const embeddedBlock = readMatrixEmbeddedBlock(targetCell);
      if (!embeddedBlock) {
        return;
      }
      const embeddedConfig = asObject(embeddedBlock.configuration_snapshot_json);
      const embeddedRows = [...((Array.isArray(embeddedConfig.rows) ? embeddedConfig.rows : []) as Array<Record<string, any>>)];
      const targetEmbeddedRowIndex = embeddedRows.findIndex((row) => String(row.id ?? "") === String(multiParticipantPicker.embeddedRowId ?? ""));
      if (targetEmbeddedRowIndex === -1) {
        return;
      }
      embeddedRows[targetEmbeddedRowIndex] = {
        ...embeddedRows[targetEmbeddedRowIndex],
        participant_ids: [...multiParticipantPicker.selectedIds],
      };
      nextColumns[targetColumnIndex] = {
        ...targetColumn,
        values: {
          ...currentValues,
          [multiParticipantPicker.rowId]: {
            ...targetCell,
            embedded_block: {
              ...embeddedBlock,
              configuration_snapshot_json: {
                ...embeddedConfig,
                rows: embeddedRows,
              },
            },
          },
        },
      };
      void saveBlockConfiguration(currentBlockId, { ...currentConfig, columns: nextColumns });
    }
    setMultiParticipantPicker(null);
    setMultiParticipantSearch("");
  }

  function eventRowsForBlock(blockConfig: Record<string, any>) {
    return [...availableEvents]
      .filter((eventRow) => {
        const tagFilter = String(blockConfig.event_tag_filter ?? "").trim().toLowerCase();
        const matchesTag = !tagFilter || (eventRow.tag ?? "").toLowerCase().includes(tagFilter);
        const effectiveEndDate = eventRow.event_end_date || eventRow.event_date;
        const matchesDate = blockConfig.event_only_from_protocol_date === false || !protocol.protocol_date || effectiveEndDate >= protocol.protocol_date;
        return matchesTag && matchesDate;
      })
      .sort((left, right) => compareIsoDate(left.event_date, right.event_date));
  }

  function eventColumnVisibility(blockConfig: Record<string, any>) {
    const columns = {
      showDate: blockConfig.event_show_date !== false,
      showTag: blockConfig.event_show_tag !== false,
      showTitle: blockConfig.event_show_title !== false,
      showDescription: blockConfig.event_show_description !== false,
      showParticipantCount: blockConfig.event_show_participant_count === true,
    };
    if (!columns.showDate && !columns.showTag && !columns.showTitle && !columns.showDescription && !columns.showParticipantCount) {
      columns.showTitle = true;
    }
    return columns;
  }

  function eventDraftValue(eventRow: EventSummary) {
    return {
      ...eventRow,
      ...(eventDrafts[eventRow.id] ?? {}),
    };
  }

  function updateEventDraft(eventId: number, patch: Partial<EventSummary>) {
    setEventDrafts((current) => ({
      ...current,
      [eventId]: {
        ...(current[eventId] ?? {}),
        ...patch,
      },
    }));
  }

  function resetEventDraft(eventId: number) {
    setEventDrafts((current) => {
      if (!current[eventId]) {
        return current;
      }
      const next = { ...current };
      delete next[eventId];
      return next;
    });
  }

  function eventPayloadFromDraft(
    eventRow: EventSummary,
    draft: Partial<EventSummary>,
    forcedTag: string,
    allowEndDate: boolean
  ) {
    const nextEventRow = {
      ...eventRow,
      ...draft,
    };
    return {
      event_date: nextEventRow.event_date,
      event_end_date: allowEndDate ? nextEventRow.event_end_date || null : null,
      tag: forcedTag || nextEventRow.tag || null,
      title: nextEventRow.title,
      description: nextEventRow.description || null,
      participant_count: Math.max(0, Number(nextEventRow.participant_count ?? 0)),
    };
  }

  function queueEventRowSave(
    protocolElementBlockId: number,
    eventRow: EventSummary,
    patch: Partial<EventSummary>,
    options: { forcedTag: string; allowEndDate: boolean }
  ) {
    const nextDraft = {
      ...(eventDrafts[eventRow.id] ?? {}),
      ...patch,
    };
    updateEventDraft(eventRow.id, patch);
    if (eventAutosaveTimers.current[eventRow.id]) {
      window.clearTimeout(eventAutosaveTimers.current[eventRow.id]);
    }
    eventAutosaveTimers.current[eventRow.id] = window.setTimeout(async () => {
      const saved = await updateEventFromBlock(
        protocolElementBlockId,
        eventRow.id,
        eventPayloadFromDraft(eventRow, nextDraft, options.forcedTag, options.allowEndDate)
      );
      if (saved) {
        resetEventDraft(eventRow.id);
      }
    }, 500);
  }

  function newEventRowDraft(blockConfig: Record<string, any>) {
    const forcedTag = String(blockConfig.event_tag_filter ?? "").trim();
    const columns = eventColumnVisibility(blockConfig);
    return createInlineProtocolEventDraft(protocol.protocol_date, forcedTag, columns.showTitle);
  }

  function resetNewEventRow(blockId: number) {
    if (newEventCreateTimers.current[blockId]) {
      window.clearTimeout(newEventCreateTimers.current[blockId]);
      delete newEventCreateTimers.current[blockId];
    }
    setCreatingNewEventRows((current) => {
      if (!current[blockId]) {
        return current;
      }
      const next = { ...current };
      delete next[blockId];
      return next;
    });
    setOpenNewEventRows((current) => {
      if (!current[blockId]) {
        return current;
      }
      const next = { ...current };
      delete next[blockId];
      return next;
    });
    setNewEventDrafts((current) => {
      if (!current[blockId]) {
        return current;
      }
      const next = { ...current };
      delete next[blockId];
      return next;
    });
  }

  function scheduleNewEventCreate(blockId: number, blockConfig: Record<string, any>, nextDraft: ProtocolEventDraft) {
    if (newEventCreateTimers.current[blockId]) {
      window.clearTimeout(newEventCreateTimers.current[blockId]);
      delete newEventCreateTimers.current[blockId];
    }
    if (!canCreateProtocolEventDraft(nextDraft)) {
      return;
    }
    newEventCreateTimers.current[blockId] = window.setTimeout(async () => {
      setCreatingNewEventRows((current) => ({ ...current, [blockId]: true }));
      const saved = await createEventFromBlock(blockId, blockConfig, nextDraft);
      setCreatingNewEventRows((current) => {
        if (!current[blockId]) {
          return current;
        }
        const next = { ...current };
        delete next[blockId];
        return next;
      });
      if (saved) {
        resetNewEventRow(blockId);
      }
    }, 500);
  }

  function patchNewEventDraft(blockId: number, blockConfig: Record<string, any>, patch: Partial<ProtocolEventDraft>) {
    setNewEventDrafts((current) => {
      const base = current[blockId] ?? newEventRowDraft(blockConfig);
      const nextDraft = { ...base, ...patch };
      scheduleNewEventCreate(blockId, blockConfig, nextDraft);
      return {
        ...current,
        [blockId]: nextDraft,
      };
    });
  }

  function matrixEventsForRow(row: Record<string, any>, column: Record<string, any>) {
    // New schema: event filters in row_config; old schema: directly on row
    const rc = (row.row_config && typeof row.row_config === "object" ? row.row_config : {}) as Record<string, any>;
    const tagFilter = String(row.event_tag_filter ?? rc.event_tag_filter ?? "").trim().toLowerCase();
    const columnTagFilter = String(column.event_tag_filter ?? "").trim().toLowerCase();
    const titleFilter = String(row.event_title_filter ?? rc.event_title_filter ?? "").trim().toLowerCase();
    const useColumnTitleAsTag = (row.use_column_title_as_tag ?? rc.use_column_title_as_tag) !== false;
    const hidePastEvents = (row.hide_past_events ?? rc.hide_past_events) !== false;
    const columnTitle = String(column.title ?? "");
    return [...availableEvents]
      .filter((event) => {
        const effectiveEndDate = event.event_end_date || event.event_date;
        const matchesPast = !hidePastEvents || !protocol.protocol_date || effectiveEndDate >= protocol.protocol_date;
        const matchesTag =
          (!tagFilter || (event.tag ?? "").toLowerCase().includes(tagFilter)) &&
          (!columnTagFilter || (event.tag ?? "").toLowerCase().includes(columnTagFilter)) &&
          (!useColumnTitleAsTag || !columnTitle.trim() || (event.tag ?? "").toLowerCase().includes(columnTitle.trim().toLowerCase()));
        const matchesTitle = !titleFilter || event.title.toLowerCase().includes(titleFilter);
        return matchesPast && matchesTag && matchesTitle;
      })
      .sort((left, right) => compareIsoDate(left.event_date, right.event_date));
  }

  function matrixRows(blockConfig: Record<string, any>) {
    return ((Array.isArray(blockConfig.rows) ? blockConfig.rows : []) as Array<Record<string, any>>).sort(
      (left, right) => Number(left.sort_index ?? 0) - Number(right.sort_index ?? 0)
    );
  }

  function matrixRowEditable(row: Record<string, any>) {
    // New schema: locked_in_protocol; old schema: protocol_editable
    if ("locked_in_protocol" in row) return !Boolean(row.locked_in_protocol);
    return row.protocol_editable !== false;
  }

  function matrixColumns(blockConfig: Record<string, any>) {
    return (Array.isArray(blockConfig.columns) ? blockConfig.columns : []) as Array<Record<string, any>>;
  }

  function matrixRowType(row: Record<string, any>): string {
    // New schema: row_type; old schema: embedded_element_type_id or value_type
    if (row.row_type) return String(row.row_type);
    if (row.embedded_element_type_id) return String(row.embedded_element_type_id);
    return String(row.value_type ?? "text");
  }

  function matrixDefaultCellValue(row: Record<string, any>) {
    const rowType = matrixRowType(row);
    const _namedTypes = ["text", "participant", "participants", "event", "events"];
    if (!_namedTypes.includes(rowType)) {
      // Embedded block type — no default cell value
      return {};
    }
    if (rowType === "participant") {
      return row.template_participant_id ? { participant_id: Number(row.template_participant_id) } : {};
    }
    if (rowType === "participants") {
      return Array.isArray(row.template_participant_ids) && row.template_participant_ids.length
        ? { participant_ids: row.template_participant_ids.map(Number).filter(Boolean) }
        : {};
    }
    if (rowType === "event") {
      return row.template_event_id ? { event_id: Number(row.template_event_id) } : {};
    }
    return String(row.template_value ?? "").trim() ? { text_value: String(row.template_value) } : {};
  }

  function matrixCellValue(column: Record<string, any>, row: Record<string, any>, rowId: string) {
    // New schema: row_values; old schema: values
    const cellMap = asObject(column.row_values ?? column.values);
    return {
      ...matrixDefaultCellValue(row),
      ...asObject(cellMap[rowId]),
    };
  }

  function matrixEmbeddedBlockForRow(row: Record<string, any>, cell: Record<string, any>) {
    const existingEmbeddedBlock = readMatrixEmbeddedBlock(cell);
    if (existingEmbeddedBlock) {
      return existingEmbeddedBlock;
    }
    const rowType = matrixRowType(row);
    const _namedTypes = ["text", "participant", "participants", "event", "events"];
    if (_namedTypes.includes(rowType)) {
      return null;
    }
    const configuredElementTypeId = Number(rowType);
    if (!configuredElementTypeId) {
      return null;
    }
    // row_config contains embedded block config (new schema); embedded_configuration_json is old schema
    const embeddedConfig = asObject(row.row_config ?? row.embedded_configuration_json);
    return createMatrixEmbeddedBlock(
      configuredElementTypeId,
      String(row.label ?? "Zeile"),
      protocol,
      availableParticipants,
      embeddedConfig
    );
  }

  function setMatrixColumnsLocal(blockId: number, blockConfig: Record<string, any>, nextColumns: Array<Record<string, any>>) {
    setBlockConfigLocal(blockId, { ...blockConfig, columns: nextColumns });
  }

  function saveMatrixColumns(blockId: number, blockConfig: Record<string, any>, nextColumns: Array<Record<string, any>>) {
    void saveBlockConfiguration(blockId, { ...blockConfig, columns: nextColumns });
  }

  function updateMatrixColumn(
    blockId: number,
    blockConfig: Record<string, any>,
    columnId: string,
    updater: (column: Record<string, any>) => Record<string, any>,
    persist = false
  ) {
    const nextColumns = matrixColumns(blockConfig).map((column) =>
      String(column.id ?? "") === columnId ? updater(column) : column
    );
    if (persist) {
      saveMatrixColumns(blockId, blockConfig, nextColumns);
    } else {
      setMatrixColumnsLocal(blockId, blockConfig, nextColumns);
    }
  }

  function updateMatrixCell(
    blockId: number,
    blockConfig: Record<string, any>,
    columnId: string,
    rowId: string,
    patch: Record<string, unknown>,
    persist = false
  ) {
    updateMatrixColumn(
      blockId,
      blockConfig,
      columnId,
      (column) => {
        // New schema: row_values; old schema: values
        const currentValues = asObject(column.row_values ?? column.values);
        const currentCell = asObject(currentValues[rowId]);
        return {
          ...column,
          row_values: {
            ...currentValues,
            [rowId]: {
              ...currentCell,
              ...patch,
            },
          },
        };
      },
      persist
    );
  }

  function updateMatrixEmbeddedBlock(
    blockId: number,
    blockConfig: Record<string, any>,
    columnId: string,
    row: Record<string, any>,
    rowId: string,
    updater: (current: MatrixEmbeddedBlock) => MatrixEmbeddedBlock,
    persist = false
  ) {
    const currentColumn = matrixColumns(blockConfig).find((column) => String(column.id ?? "") === columnId);
    const currentCell = currentColumn ? matrixCellValue(currentColumn, row, rowId) : matrixDefaultCellValue(row);
    const currentEmbeddedBlock = matrixEmbeddedBlockForRow(row, currentCell);
    if (!currentEmbeddedBlock) {
      return;
    }
    updateMatrixCell(blockId, blockConfig, columnId, rowId, { embedded_block: updater(currentEmbeddedBlock) }, persist);
  }

  function matrixValueSummary(row: Record<string, any>, value: Record<string, any>) {
    const rowType = matrixRowType(row);
    if (rowType === "participants") {
      return multiParticipantSummary(value);
    }
    if (rowType === "participant") {
      const participant = availableParticipants.find((entry) => entry.id === Number(value.participant_id ?? 0));
      return participant?.display_name ?? "Teilnehmer waehlen";
    }
    if (rowType === "event") {
      const eventRow = sortedAvailableEvents.find((entry) => entry.id === Number(value.event_id ?? 0));
      return eventRow ? `${formatDateRange(eventRow.event_date, eventRow.event_end_date)} · ${eventRow.title}` : "Termin waehlen";
    }
    return String(value.text_value ?? row.template_value ?? "").trim() || "Kein Inhalt";
  }

  function nextMatrixColumnId(currentColumns: Array<Record<string, any>>) {
    const maxValue = currentColumns.reduce((highest, column) => {
      const match = String(column.id ?? "").match(/^matrix-column-(\d+)$/);
      const candidate = match ? Number(match[1]) : 0;
      return Math.max(highest, candidate);
    }, 0);
    return `matrix-column-${maxValue + 1}`;
  }

  function generateMatrixColumns(blockId: number, blockConfig: Record<string, any>) {
    // Support both new auto_source object and old matrix_column_source* fields
    const autoSrc = blockConfig.auto_source;
    const source = String(
      (autoSrc && typeof autoSrc === "object" ? autoSrc.type : null) ?? blockConfig.matrix_column_source ?? ""
    );
    const rows = matrixRows(blockConfig);

    function rowCellValue(row: Record<string, any>, textValue: string): Record<string, unknown> {
      const rowType = matrixRowType(row);
      if (!textValue && rowType === "participant") return {};
      if (!textValue && rowType === "event") return {};
      return textValue ? { text_value: textValue } : {};
    }

    // auto_source_field: new schema; source_field_*: old schema
    function getSourceField(row: Record<string, any>): string {
      if (row.auto_source_field) return String(row.auto_source_field);
      if (source === "participants") return String(row.source_field_participant ?? "");
      if (source === "events") return String(row.source_field_event ?? "");
      if (source === "list") return String(row.source_field_list ?? "");
      return "";
    }

    let nextColumns: Array<Record<string, any>> = [];

    if (source === "participants") {
      nextColumns = availableParticipants.map((participant) => {
        const row_values: Record<string, Record<string, unknown>> = {};
        rows.forEach((row) => {
          const rowId = String(row.id ?? row.sort_index ?? rows.indexOf(row));
          const sourceField = getSourceField(row);
          const rowType = matrixRowType(row);
          if (sourceField) {
            let text = "";
            if (sourceField === "display_name") text = participant.display_name;
            else if (sourceField === "first_name") text = String(participant.first_name ?? "");
            else if (sourceField === "last_name") text = String(participant.last_name ?? "");
            else if (sourceField === "email") text = String(participant.email ?? "");
            row_values[rowId] = rowCellValue(row, text);
          } else if (rowType === "participant") {
            row_values[rowId] = { participant_id: participant.id };
          } else if (rowType === "participants") {
            row_values[rowId] = { participant_ids: [participant.id] };
          }
        });
        return { id: `gen-p-${participant.id}`, title: participant.display_name, row_values };
      });
    } else if (source === "events") {
      const tagFilter = String(
        (autoSrc && typeof autoSrc === "object" ? autoSrc.event_tag_filter : null) ??
        blockConfig.matrix_column_source_event_tag ?? ""
      ).trim().toLowerCase();
      const filtered = tagFilter
        ? availableEvents.filter((e) => String(e.tag ?? "").toLowerCase() === tagFilter)
        : availableEvents;
      nextColumns = filtered.map((event) => {
        const row_values: Record<string, Record<string, unknown>> = {};
        rows.forEach((row) => {
          const rowId = String(row.id ?? row.sort_index ?? rows.indexOf(row));
          const sourceField = getSourceField(row);
          const rowType = matrixRowType(row);
          if (sourceField) {
            let text = "";
            if (sourceField === "title") text = event.title;
            else if (sourceField === "event_date") text = event.event_date;
            else if (sourceField === "tag") text = String(event.tag ?? "");
            else if (sourceField === "participant_count") text = String((event as any).participant_count ?? "");
            row_values[rowId] = rowCellValue(row, text);
          } else if (rowType === "event") {
            row_values[rowId] = { event_id: event.id };
          }
        });
        return { id: `gen-e-${event.id}`, title: event.title, row_values };
      });
    } else if (source === "list") {
      const listDefId = Number(
        (autoSrc && typeof autoSrc === "object" ? autoSrc.list_id : null) ??
        blockConfig.matrix_column_source_list_id ?? 0
      );
      const entries = listDefId ? (listEntriesByDefinition[listDefId] ?? []) : [];
      nextColumns = entries.map((entry) => {
        const titleText =
          String((entry.column_one_value as any)?.text_value ?? "").trim() ||
          String((entry.column_two_value as any)?.text_value ?? "").trim() ||
          `Eintrag ${entry.id}`;
        const row_values: Record<string, Record<string, unknown>> = {};
        rows.forEach((row) => {
          const rowId = String(row.id ?? row.sort_index ?? rows.indexOf(row));
          const sourceField = getSourceField(row);
          if (!sourceField) return;
          const colVal: Record<string, unknown> =
            sourceField === "column_one" ? (entry.column_one_value as Record<string, unknown>) ?? {} :
            sourceField === "column_two" ? (entry.column_two_value as Record<string, unknown>) ?? {} : {};
          const rowType = matrixRowType(row);
          // Participant(s) values from list entry
          if (Array.isArray(colVal.participant_ids)) {
            const ids = colVal.participant_ids as number[];
            if (rowType === "participants") row_values[rowId] = { participant_ids: ids };
            else if (rowType === "participant") row_values[rowId] = ids.length ? { participant_id: ids[0] } : {};
          } else if (colVal.participant_id != null) {
            const id = colVal.participant_id as number;
            if (rowType === "participants") row_values[rowId] = { participant_ids: [id] };
            else row_values[rowId] = { participant_id: id };
          } else if (colVal.event_id != null) {
            row_values[rowId] = { event_id: colVal.event_id };
          } else {
            // Text value
            row_values[rowId] = rowCellValue(row, String(colVal.text_value ?? "").trim());
          }
        });
        return { id: `gen-l-${entry.id}`, title: titleText, row_values };
      });
    }

    if (!nextColumns.length) return;
    saveMatrixColumns(blockId, blockConfig, nextColumns);
  }

  useEffect(() => {
    const fields = sectionRef.current?.querySelectorAll<HTMLTextAreaElement>(".todo-main-compact .todo-input") ?? [];
    fields.forEach((field) => autoResizeTodoField(field));
  }, [element.id, todosByBlock]);

  return (
    <>
    <section className="block block-active" id={`protocol-element-${element.id}`} ref={sectionRef}>
      <div className="editor-panel-header">
        <div>
          <div className="eyebrow">Protokollpunkt</div>
          <h2>{element.section_name_snapshot}</h2>
          <p className="muted">
            Alle Bloecke dieses Elements werden zusammen bearbeitet. Pfeiltasten oben/unten springen direkt zum naechsten Punkt.
          </p>
        </div>
        <div className="status-row">
          <span className="pill">Punkt {elementIndex + 1}</span>
          <span className="pill">{element.blocks.length} Block{element.blocks.length === 1 ? "" : "e"}</span>
          <span className="pill">{elementSaveState(element, blockStatus)}</span>
        </div>
      </div>
      <div className="element-block-stack">
        {element.blocks.map((block) => {
          const blockTitle = visibleBlockTitle(block);
          const elementType = block.element_type_code ?? "unknown";
          const blockConfig = asObject(block.configuration_snapshot_json);
          const editableEventRows = elementType === "event_list" ? eventRowsForBlock(blockConfig) : [];
          const editableEventColumns = elementType === "event_list" ? eventColumnVisibility(blockConfig) : null;
          const forcedEventTag = elementType === "event_list" ? String(blockConfig.event_tag_filter ?? "").trim() : "";
          const allowEventEndDate = elementType === "event_list" ? blockConfig.event_allow_end_date === true : false;
          const newEventDraft =
            elementType === "event_list" ? newEventDrafts[block.id] ?? newEventRowDraft(blockConfig) : null;
          const showNewEventRow = elementType === "event_list" ? openNewEventRows[block.id] === true : false;
          const creatingNewEventRow = elementType === "event_list" ? creatingNewEventRows[block.id] === true : false;
          const allowMatrixColumnManagement =
            elementType === "matrix" ? block.is_editable_snapshot && (blockConfig.allow_column_management === true || blockConfig.matrix_allow_column_management === true) : false;
          return (
            <section className="card editor-block-card" key={block.id}>
              <div className="editor-panel-header">
                <div>
                  <div className="eyebrow">{elementType}</div>
                  {blockTitle ? <h3>{blockTitle}</h3> : null}
                  {block.description_snapshot ? <p className="muted">{block.description_snapshot}</p> : null}
                </div>
                <div className="status-row">
                  <span className="pill">{blockStatus[block.id] ?? "saved"}</span>
                </div>
              </div>

              {(elementType === "text" || elementType === "static_text") && (
                <RichTextEditor
                  value={textDrafts[block.id] ?? ""}
                  onChange={(md) => handleTextChange(block.id, md)}
                  readOnly={!block.is_editable_snapshot}
                  placeholder="Text schreiben… Fett mit **text**, kursiv mit *text*, Liste mit - oder 1."
                />
              )}

              {elementType === "todo" && (
                <div className="grid">
                  <div className="todo-list">
                    {(todosByBlock[block.id] ?? []).map((todo) => {
                      const isDone = todo.todo_status_code === "done";
                      return (
                        <article className={`todo-card todo-card-compact${isDone ? " todo-card-done" : ""}`} key={todo.id}>
                          <button
                            type="button"
                            className={`todo-toggle${isDone ? " todo-toggle-done" : ""}`}
                            onClick={() =>
                              updateTodo(block.id, todo.id, {
                                todo_status_id: isDone ? TODO_STATUS.open : TODO_STATUS.done,
                                completed_at: isDone ? null : new Date().toISOString(),
                              })
                            }
                            aria-label={isDone ? "Reopen todo" : "Mark todo done"}
                          >
                            {isDone ? "✓" : "○"}
                          </button>
                          <div className="todo-main todo-main-compact">
                            <textarea
                              className="todo-input"
                              rows={1}
                              value={todo.task}
                              onInput={(event) => autoResizeTodoField(event.currentTarget)}
                              onChange={(event) => {
                                const task = event.target.value;
                                setTodosByBlock((current) => ({
                                  ...current,
                                  [block.id]: (current[block.id] ?? []).map((item) =>
                                    item.id === todo.id ? { ...item, task } : item
                                  ),
                                }));
                                void updateTodo(block.id, todo.id, { task });
                              }}
                            />
                          </div>
                          <div className="todo-inline-meta">
                            <TodoMiniMenu label={todo.assigned_participant_name ?? "Niemand"} compact>
                              {(closeMenu) => (
                              <div className="mini-menu-section">
                                <TodoMenuOption
                                  label="Niemand"
                                  active={!todo.assigned_participant_id}
                                  onClick={() => {
                                    setTodosByBlock((current) => ({
                                      ...current,
                                      [block.id]: (current[block.id] ?? []).map((item) =>
                                        item.id === todo.id
                                          ? { ...item, assigned_participant_id: null, assigned_participant_name: null }
                                          : item
                                        ),
                                    }));
                                    void updateTodo(block.id, todo.id, { assigned_participant_id: null });
                                    closeMenu();
                                  }}
                                />
                                {availableParticipants.map((participant) => (
                                  <TodoMenuOption
                                    key={participant.id}
                                    label={participant.display_name}
                                    active={todo.assigned_participant_id === participant.id}
                                    onClick={() => {
                                      setTodosByBlock((current) => ({
                                        ...current,
                                        [block.id]: (current[block.id] ?? []).map((item) =>
                                          item.id === todo.id
                                            ? {
                                                ...item,
                                                assigned_participant_id: participant.id,
                                                assigned_participant_name: participant.display_name,
                                              }
                                            : item
                                        ),
                                      }));
                                      void updateTodo(block.id, todo.id, { assigned_participant_id: participant.id });
                                      closeMenu();
                                    }}
                                  />
                                ))}
                              </div>
                              )}
                            </TodoMiniMenu>
                            <TodoMiniMenu label={dueMenuLabel(todo)} compact align="end">
                              {(closeMenu) => (
                              <>
                              <div className="mini-menu-section">
                                <TodoMenuOption
                                  label="Kein Enddatum"
                                  active={!todo.due_date && !todo.due_event_id && !todo.due_marker}
                                  onClick={() => {
                                    void updateTodo(block.id, todo.id, { due_date: null, due_event_id: null, due_marker: null });
                                    closeMenu();
                                  }}
                                />
                                <TodoMenuOption
                                  label="Freies Datum"
                                  active={!!todo.due_date && !todo.due_event_id && !todo.due_marker}
                                  onClick={() => {
                                    const nextDate = todo.due_date ?? protocol.protocol_date;
                                    void updateTodo(block.id, todo.id, { due_date: nextDate, due_event_id: null, due_marker: null });
                                    closeMenu();
                                  }}
                                />
                                <TodoMenuOption
                                  label="Naechste Sitzung"
                                  active={todo.due_marker === "next_session"}
                                  onClick={() => {
                                    void updateTodo(block.id, todo.id, { due_date: null, due_event_id: null, due_marker: "next_session" });
                                    closeMenu();
                                  }}
                                />
                              </div>
                              {upcomingEvents.length ? (
                                <div className="mini-menu-section">
                                  <div className="mini-menu-section-title">Naechste Termine</div>
                                  {upcomingEvents.map((event) => (
                                    <TodoMenuOption
                                      key={event.id}
                                      label={event.title}
                                      subtle={formatDateRange(event.event_date, event.event_end_date)}
                                      active={todo.due_event_id === event.id}
                                      onClick={() => {
                                        void updateTodo(block.id, todo.id, {
                                          due_date: null,
                                          due_event_id: event.id,
                                          due_marker: null,
                                        });
                                        closeMenu();
                                      }}
                                    />
                                  ))}
                                </div>
                              ) : null}
                              </>
                              )}
                            </TodoMiniMenu>
                            {(todo.due_marker || todo.due_event_id || todo.due_date) ? (
                              <div className="todo-due-inline">
                                {todo.due_date && !todo.due_event_id && !todo.due_marker ? (
                                  <input
                                    type="date"
                                    value={todo.due_date}
                                    onChange={(event) => {
                                      void updateTodo(block.id, todo.id, {
                                        due_date: event.target.value || null,
                                        due_event_id: null,
                                        due_marker: null,
                                      });
                                    }}
                                  />
                                ) : (
                                  <span className="pill">
                                    {todo.resolved_due_date ?? todo.due_date ?? ""}{todo.resolved_due_label ? ` (${todo.resolved_due_label})` : ""}
                                  </span>
                                )}
                              </div>
                            ) : null}
                          </div>
                          <button
                            type="button"
                            className="button-inline button-danger todo-delete"
                            onClick={() => deleteTodo(block.id, todo.id)}
                          >
                            Delete
                          </button>
                        </article>
                      );
                    })}
                  </div>
                  <div className="todo-create todo-create-inline">
                    <input
                      value={newTodoTask[block.id] ?? ""}
                      onChange={(event) => setNewTodoTask((current) => ({ ...current, [block.id]: event.target.value }))}
                      placeholder="Neue Aufgabe"
                    />
                    <button type="button" onClick={() => addTodo(block.id)}>
                      + Todo
                    </button>
                  </div>
                </div>
              )}

              {elementType === "bullet_list" && (
                <div className="grid">
                  <div className="todo-list">
                    {((Array.isArray(blockConfig.bullet_items) ? blockConfig.bullet_items : []) as string[]).map((item, index) => (
                      <article className="todo-card todo-card-compact" key={`${block.id}-bullet-${index}`}>
                        <div className="todo-toggle todo-toggle-done">•</div>
                        <div className="todo-main todo-main-compact">
                          <textarea
                            className="todo-input"
                            rows={1}
                            value={item}
                            onInput={(event) => autoResizeTodoField(event.currentTarget)}
                            onChange={(event) => {
                              const nextItems = [...((Array.isArray(blockConfig.bullet_items) ? blockConfig.bullet_items : []) as string[])];
                              nextItems[index] = event.target.value;
                              setBlockConfigLocal(block.id, { ...blockConfig, bullet_items: nextItems });
                            }}
                            onBlur={() => {
                              void saveBlockConfiguration(block.id, {
                                ...blockConfig,
                                bullet_items: ((Array.isArray(blockConfig.bullet_items) ? blockConfig.bullet_items : []) ?? []) as string[],
                              });
                            }}
                          />
                        </div>
                        <button
                          type="button"
                          className="button-inline button-danger todo-delete"
                          onClick={() => {
                            const nextItems = ((Array.isArray(blockConfig.bullet_items) ? blockConfig.bullet_items : []) as string[]).filter((_, itemIndex) => itemIndex !== index);
                            void saveBlockConfiguration(block.id, { ...blockConfig, bullet_items: nextItems });
                          }}
                        >
                          Delete
                        </button>
                      </article>
                    ))}
                  </div>
                  <div className="todo-create todo-create-inline">
                    <input
                      value=""
                      readOnly
                      placeholder="Neuen Bulletpoint mit dem Button hinzufügen"
                    />
                    <button
                      type="button"
                      onClick={() => {
                        const nextItems = [...((Array.isArray(blockConfig.bullet_items) ? blockConfig.bullet_items : []) as string[]), ""];
                        void saveBlockConfiguration(block.id, { ...blockConfig, bullet_items: nextItems });
                      }}
                    >
                      + Punkt
                    </button>
                  </div>
                </div>
              )}

              {elementType === "form" && (
                (() => {
                  const linkedListId = Number(blockConfig.linked_list_id ?? 0);
                  const linkedListDefinition = listDefinitionsById.get(linkedListId);
                  if (linkedListId && linkedListDefinition) {
                    return (
                      <StructuredListTable
                        definition={linkedListDefinition}
                        entries={listEntriesByDefinition[linkedListId] ?? []}
                        availableParticipants={availableParticipants}
                        availableEvents={availableEvents}
                        editable={block.is_editable_snapshot}
                        emptyMessage="Noch keine Eintraege in dieser Liste."
                        onCreateEntry={(payload) => createListEntryFromBlock(block.id, linkedListId, payload)}
                        onUpdateEntry={(entryId, payload) => updateListEntryFromBlock(block.id, linkedListId, entryId, payload)}
                        onDeleteEntry={(entryId) => deleteListEntryFromBlock(block.id, linkedListId, entryId)}
                      />
                    );
                  }
                  return (
                    <div className="grid">
                      {String(blockConfig.left_column_heading ?? "").trim() || String(blockConfig.value_column_heading ?? "").trim() ? (
                        <div className="form-block-row form-block-row-head">
                          <div className="field-label-inline">{String(blockConfig.left_column_heading ?? "").trim()}</div>
                          <div className="field-label-inline">{String(blockConfig.value_column_heading ?? "").trim()}</div>
                          <div />
                        </div>
                      ) : null}
                      <div className="form-block-list">
                        {((Array.isArray(blockConfig.rows) ? blockConfig.rows : []) as Array<Record<string, any>>).map((row, index) => (
                          <div className="form-block-row" key={`${block.id}-form-${index}`}>
                            <div className="field-label-inline">{row.label ?? `Feld ${index + 1}`}</div>
                            {row.value_type === "participant" ? (
                              <select
                                value={row.participant_id ?? ""}
                                onChange={(event) => {
                                  const nextRows = [...((Array.isArray(blockConfig.rows) ? blockConfig.rows : []) as Array<Record<string, any>>)];
                                  nextRows[index] = { ...nextRows[index], participant_id: event.target.value ? Number(event.target.value) : null };
                                  void saveBlockConfiguration(block.id, { ...blockConfig, rows: nextRows });
                                }}
                              >
                                <option value="">Teilnehmer wählen</option>
                                {availableParticipants.map((participant) => (
                                  <option key={participant.id} value={participant.id}>
                                    {participant.display_name}
                                  </option>
                                ))}
                              </select>
                            ) : row.value_type === "participants" ? (
                              <button
                                type="button"
                                className="button-ghost form-participant-picker-button"
                                onClick={() => openMultiParticipantPicker(block.id, index, row)}
                              >
                                {multiParticipantSummary(row)}
                              </button>
                            ) : row.value_type === "event" ? (
                              <select
                                value={row.event_id ?? ""}
                                onChange={(event) => {
                                  const nextRows = [...((Array.isArray(blockConfig.rows) ? blockConfig.rows : []) as Array<Record<string, any>>)];
                                  nextRows[index] = { ...nextRows[index], event_id: event.target.value ? Number(event.target.value) : null };
                                  void saveBlockConfiguration(block.id, { ...blockConfig, rows: nextRows });
                                }}
                              >
                                <option value="">Termin wählen</option>
                                {[...availableEvents].sort((left, right) => compareIsoDate(left.event_date, right.event_date)).map((eventRow) => (
                                  <option key={eventRow.id} value={eventRow.id}>
                                    {formatDateRange(eventRow.event_date, eventRow.event_end_date)} · {eventRow.title}
                                  </option>
                                ))}
                              </select>
                            ) : (
                              <textarea
                                rows={1}
                                className="todo-input"
                                value={row.text_value ?? ""}
                                onInput={(event) => autoResizeTodoField(event.currentTarget)}
                                onChange={(event) => {
                                  const nextRows = [...((Array.isArray(blockConfig.rows) ? blockConfig.rows : []) as Array<Record<string, any>>)];
                                  nextRows[index] = { ...nextRows[index], text_value: event.target.value };
                                  setBlockConfigLocal(block.id, { ...blockConfig, rows: nextRows });
                                }}
                                onBlur={() => {
                                  const nextRows = [...((Array.isArray(blockConfig.rows) ? blockConfig.rows : []) as Array<Record<string, any>>)];
                                  void saveBlockConfiguration(block.id, { ...blockConfig, rows: nextRows });
                                }}
                              />
                            )}
                            <button
                              type="button"
                              className="button-inline button-danger todo-delete"
                              onClick={() => {
                                const nextRows = ((Array.isArray(blockConfig.rows) ? blockConfig.rows : []) as Array<Record<string, any>>).filter((_, rowIndex) => rowIndex !== index);
                                void saveBlockConfiguration(block.id, { ...blockConfig, rows: nextRows });
                              }}
                            >
                              Delete
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })()
              )}

              {elementType === "matrix" && (
                <div className="grid">
                  {allowMatrixColumnManagement ? (
                    <div className="matrix-block-toolbar">
                      <button
                        type="button"
                        className="button-inline"
                        onClick={() => {
                          const nextColumns = [
                            ...matrixColumns(blockConfig),
                            {
                              id: nextMatrixColumnId(matrixColumns(blockConfig)),
                              title: "",
                              row_values: Object.fromEntries(
                                matrixRows(blockConfig).map((row, rowIndex) => [
                                  String(row.id ?? rowIndex),
                                  matrixDefaultCellValue(row),
                                ])
                              ),
                            },
                          ];
                          saveMatrixColumns(block.id, blockConfig, nextColumns);
                        }}
                      >
                        + Spalte
                      </button>
                      {(blockConfig.auto_source?.type || blockConfig.matrix_column_source) ? (
                        <button
                          type="button"
                          className="button-inline"
                          onClick={() => generateMatrixColumns(block.id, blockConfig)}
                        >
                          Generieren
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                  {/* Wrapping card layout: one card per column, rows stacked inside */}
                  {(() => {
                    const cols = matrixColumns(blockConfig);
                    const rows = matrixRows(blockConfig);
                    const displayCols = cols.length ? cols : [null, null, null]; // 3 placeholders
                    return (
                      <div className="matrix-cards">
                        {displayCols.map((column, columnIndex) => {
                          const isPlaceholder = column === null;
                          const columnId = isPlaceholder ? null : String(column!.id ?? columnIndex);
                          return (
                            <div key={isPlaceholder ? `ph-${columnIndex}` : String(column!.id ?? columnIndex)}
                              className={`matrix-card${isPlaceholder ? " matrix-card-placeholder" : ""}`}>
                              {/* Column header */}
                              <div className="matrix-card-header">
                                {isPlaceholder ? (
                                  <span className="muted">Spalte {columnIndex + 1}</span>
                                ) : allowMatrixColumnManagement ? (
                                  <>
                                    <input
                                      className="matrix-col-title-input"
                                      value={String(column!.title ?? "")}
                                      onChange={(e) => updateMatrixColumn(block.id, blockConfig, columnId!,
                                        (cur) => ({ ...cur, title: e.target.value }))}
                                      onBlur={() => updateMatrixColumn(block.id, blockConfig, columnId!,
                                        (cur) => cur, true)}
                                      placeholder={String(column!.title_placeholder ?? `Spalte ${columnIndex + 1}`)}
                                    />
                                    <button type="button" className="matrix-col-remove"
                                      onClick={() => saveMatrixColumns(block.id, blockConfig,
                                        matrixColumns(blockConfig).filter(e => String(e.id ?? "") !== columnId!))}>
                                      ×
                                    </button>
                                  </>
                                ) : (
                                  <span className="matrix-card-title">
                                    {String(column!.title ?? "").trim() || `Spalte ${columnIndex + 1}`}
                                  </span>
                                )}
                              </div>

                              {/* Row sections */}
                              {rows.map((row, rowIndex) => {
                                const rowId = String(row.id ?? rowIndex);
                                const value = isPlaceholder ? {} : matrixCellValue(column!, row, rowId);
                                const embeddedBlock = isPlaceholder ? null : matrixEmbeddedBlockForRow(row, value);
                                const cellEditable = !isPlaceholder && block.is_editable_snapshot && matrixRowEditable(row);
                                const autoEvents = (!isPlaceholder && !embeddedBlock && matrixRowType(row) === "events")
                                  ? matrixEventsForRow(row, column!) : [];
                                return (
                                  <div key={`${rowId}-${columnIndex}`} className="matrix-card-row">
                                    <div className={`matrix-card-row-label${!matrixRowEditable(row) ? " matrix-row-locked" : ""}`}>
                                      {row.label ?? `Zeile ${rowIndex + 1}`}
                                      {!matrixRowEditable(row) ? <span className="matrix-lock-icon"> 🔒</span> : null}
                                    </div>
                                    <div className="matrix-card-row-cell">
                                      {isPlaceholder ? (
                                        <div className="matrix-table-placeholder" style={{ height: 40, borderRadius: 8 }} />
                                      ) : embeddedBlock ? (
                                        <>
                                          <MatrixEmbeddedBlockEditor
                                            embeddedBlock={embeddedBlock}
                                            protocol={protocol}
                                            availableParticipants={availableParticipants}
                                            availableEvents={availableEvents}
                                            matrixColumn={column!}
                                            editable={cellEditable}
                                            updateEmbeddedBlock={(updater, persist = false) =>
                                              updateMatrixEmbeddedBlock(block.id, blockConfig, columnId!, row, rowId, updater, persist)}
                                            openMultiParticipantPicker={(embeddedRow) =>
                                              openEmbeddedFormParticipantPicker(block.id, columnId!, rowId,
                                                String(row.label ?? `Zeile ${rowIndex + 1}`), embeddedRow)}
                                            createEvent={(forcedTag, draft) =>
                                              createEventFromBlock(block.id, {
                                                event_tag_filter: forcedTag,
                                                event_allow_end_date:
                                                  asObject(embeddedBlock.configuration_snapshot_json).event_allow_end_date === true,
                                              }, draft)}
                                            updateEvent={(eventId, patch) => updateEventFromBlock(block.id, eventId, patch)}
                                            deleteEvent={(eventId) => deleteEventFromBlock(block.id, eventId)}
                                          />
                                          {cellEditable ? (
                                            <div className="matrix-row-summary muted">
                                              {embeddedBlockSummary(embeddedBlock, availableParticipants, availableEvents, protocol, column!)}
                                            </div>
                                          ) : null}
                                        </>
                                      ) : matrixRowType(row) === "events" ? (
                                        autoEvents.length ? (
                                          <div className="matrix-event-list">
                                            {autoEvents.map((eventRow) => {
                                              const isPast = !!protocol.protocol_date &&
                                                (eventRow.event_end_date || eventRow.event_date) < protocol.protocol_date;
                                              return (
                                                <div className={`matrix-event-item${isPast ? " matrix-event-item-past" : ""}`}
                                                  key={`${columnIndex}-${rowId}-${eventRow.id}`}>
                                                  <span>{formatDateRange(eventRow.event_date, eventRow.event_end_date)}</span>
                                                  {eventRow.description ? <span className="muted">({eventRow.description})</span> : null}
                                                </div>
                                              );
                                            })}
                                          </div>
                                        ) : <span className="muted">Keine passenden Termine</span>
                                      ) : (
                                        <div className="matrix-cell-value">
                                          {!cellEditable ? (
                                            <div className="matrix-static-value">{matrixValueSummary(row, value)}</div>
                                          ) : matrixRowType(row) === "participant" ? (
                                            <select value={value.participant_id ?? ""}
                                              onChange={(e) => updateMatrixCell(block.id, blockConfig, columnId!, rowId,
                                                { participant_id: e.target.value ? Number(e.target.value) : null }, true)}>
                                              <option value="">Teilnehmer waehlen</option>
                                              {availableParticipants.map((p) => (
                                                <option key={p.id} value={p.id}>{p.display_name}</option>
                                              ))}
                                            </select>
                                          ) : matrixRowType(row) === "participants" ? (
                                            <button type="button" className="button-ghost form-participant-picker-button"
                                              onClick={() => openMatrixParticipantPicker(block.id, columnId!, {
                                                row_id: rowId, label: row.label, ...value })}>
                                              {multiParticipantSummary(value)}
                                            </button>
                                          ) : matrixRowType(row) === "event" ? (
                                            <select value={value.event_id ?? ""}
                                              onChange={(e) => updateMatrixCell(block.id, blockConfig, columnId!, rowId,
                                                { event_id: e.target.value ? Number(e.target.value) : null }, true)}>
                                              <option value="">Termin waehlen</option>
                                              {sortedAvailableEvents.map((ev) => (
                                                <option key={ev.id} value={ev.id}>
                                                  {formatDateRange(ev.event_date, ev.event_end_date)} · {ev.title}
                                                </option>
                                              ))}
                                            </select>
                                          ) : (
                                            <textarea rows={1} className="todo-input"
                                              value={String(value.text_value ?? row.template_value ?? "")}
                                              onInput={(e) => autoResizeTodoField(e.currentTarget)}
                                              onChange={(e) => updateMatrixCell(block.id, blockConfig, columnId!, rowId,
                                                { text_value: e.target.value })}
                                              onBlur={() => updateMatrixCell(block.id, blockConfig, columnId!, rowId, {}, true)}
                                            />
                                          )}
                                          {cellEditable ? (
                                            <div className="matrix-row-summary muted">{matrixValueSummary(row, value)}</div>
                                          ) : null}
                                        </div>
                                      )}
                                    </div>
                                  </div>
                                );
                              })}
                              {!rows.length ? (
                                <div className="matrix-table-empty">Keine Zeilen konfiguriert.</div>
                              ) : null}
                            </div>
                          );
                        })}
                      </div>
                    );
                  })()}
                </div>
              )}

              {elementType === "event_list" && (
                <div className="grid">
                  <div className="event-table-wrap">
                    <table className="data-table event-table event-table-compact">
                      <thead>
                        <tr>
                          {editableEventColumns?.showDate ? <th>Dat.</th> : null}
                          {editableEventColumns?.showTag ? <th>Tag</th> : null}
                          {editableEventColumns?.showTitle ? <th>Titel</th> : null}
                          {editableEventColumns?.showDescription ? <th>Beschreibung</th> : null}
                          {editableEventColumns?.showParticipantCount ? <th className="event-column-count">TN</th> : null}
                          {block.is_editable_snapshot ? (
                            <th className="event-column-actions" aria-label="Aktionen">
                              <button
                                type="button"
                                className="button-ghost button-icon"
                                title="Terminzeile hinzufügen"
                                disabled={showNewEventRow || creatingNewEventRow}
                                onClick={() => {
                                  setOpenNewEventRows((current) => ({ ...current, [block.id]: true }));
                                  setNewEventDrafts((current) => ({
                                    ...current,
                                    [block.id]: current[block.id] ?? newEventRowDraft(blockConfig),
                                  }));
                                }}
                              >
                                +
                              </button>
                            </th>
                          ) : null}
                        </tr>
                      </thead>
                      <tbody>
                        {showNewEventRow && newEventDraft ? (
                          <tr className="event-row-new">
                            {editableEventColumns?.showDate ? (
                              <td>
                                <div className={`event-date-fields${allowEventEndDate ? " event-date-fields-range" : ""}`}>
                                  <input
                                    type="date"
                                    className="event-field-date"
                                    value={newEventDraft.event_date}
                                    disabled={creatingNewEventRow}
                                    onChange={(event) => patchNewEventDraft(block.id, blockConfig, { event_date: event.target.value })}
                                  />
                                  {allowEventEndDate ? (
                                    <input
                                      type="date"
                                      className="event-field-date"
                                      value={newEventDraft.event_end_date}
                                      disabled={creatingNewEventRow}
                                      onChange={(event) => patchNewEventDraft(block.id, blockConfig, { event_end_date: event.target.value })}
                                    />
                                  ) : null}
                                </div>
                              </td>
                            ) : null}
                            {editableEventColumns?.showTag ? (
                              <td>
                                <input
                                  className="event-field-tag"
                                  value={forcedEventTag || newEventDraft.tag}
                                  readOnly={Boolean(forcedEventTag)}
                                  disabled={creatingNewEventRow}
                                  onChange={(event) => patchNewEventDraft(block.id, blockConfig, { tag: event.target.value })}
                                  placeholder="Tag"
                                />
                              </td>
                            ) : null}
                            {editableEventColumns?.showTitle ? (
                              <td>
                                <input
                                  className="event-field-title"
                                  value={newEventDraft.title}
                                  disabled={creatingNewEventRow}
                                  onChange={(event) => patchNewEventDraft(block.id, blockConfig, { title: event.target.value })}
                                  placeholder="Titel"
                                />
                              </td>
                            ) : null}
                            {editableEventColumns?.showDescription ? (
                              <td>
                                <input
                                  className="event-field-description"
                                  value={newEventDraft.description}
                                  disabled={creatingNewEventRow}
                                  onChange={(event) => patchNewEventDraft(block.id, blockConfig, { description: event.target.value })}
                                  placeholder="Beschreibung"
                                />
                              </td>
                            ) : null}
                            {editableEventColumns?.showParticipantCount ? (
                              <td className="event-column-count">
                                <input
                                  type="number"
                                  className="event-field-count"
                                  min="0"
                                  value={newEventDraft.participant_count}
                                  disabled={creatingNewEventRow}
                                  onChange={(event) => patchNewEventDraft(block.id, blockConfig, { participant_count: event.target.value })}
                                  placeholder="TN"
                                />
                              </td>
                            ) : null}
                            {block.is_editable_snapshot ? (
                              <td>
                                <div className="event-row-actions">
                                  <button
                                    type="button"
                                    className="button-ghost button-icon button-icon-danger"
                                    title="Neue Terminzeile verwerfen"
                                    disabled={creatingNewEventRow}
                                    onClick={() => resetNewEventRow(block.id)}
                                  >
                                    x
                                  </button>
                                </div>
                              </td>
                            ) : null}
                          </tr>
                        ) : null}
                        {editableEventRows.length ? (
                          editableEventRows.map((eventRow) => {
                            const effectiveEndDate = eventRow.event_end_date || eventRow.event_date;
                            const isPast = !!protocol.protocol_date && effectiveEndDate < protocol.protocol_date;
                            const editableEventRow = eventDraftValue(eventRow);
                            return (
                              <tr key={eventRow.id} className={isPast && blockConfig.event_gray_past !== false ? "event-row-past" : ""}>
                                {editableEventColumns?.showDate ? (
                                  <td>
                                    {block.is_editable_snapshot ? (
                                      <div className={`event-date-fields${allowEventEndDate ? " event-date-fields-range" : ""}`}>
                                        <input
                                          type="date"
                                          className="event-field-date"
                                          value={editableEventRow.event_date}
                                          onChange={(event) =>
                                            queueEventRowSave(block.id, eventRow, { event_date: event.target.value }, {
                                              forcedTag: forcedEventTag,
                                              allowEndDate: allowEventEndDate,
                                            })
                                          }
                                        />
                                        {allowEventEndDate ? (
                                          <input
                                            type="date"
                                            className="event-field-date"
                                            value={editableEventRow.event_end_date ?? ""}
                                            onChange={(event) =>
                                              queueEventRowSave(block.id, eventRow, { event_end_date: event.target.value || null }, {
                                                forcedTag: forcedEventTag,
                                                allowEndDate: allowEventEndDate,
                                              })
                                            }
                                          />
                                        ) : null}
                                      </div>
                                    ) : (
                                      formatDateRange(eventRow.event_date, eventRow.event_end_date)
                                    )}
                                  </td>
                                ) : null}
                                {editableEventColumns?.showTag ? (
                                  <td>
                                    {block.is_editable_snapshot ? (
                                      <input
                                        className="event-field-tag"
                                        value={editableEventRow.tag ?? forcedEventTag}
                                        readOnly={Boolean(forcedEventTag)}
                                        onChange={(event) =>
                                          queueEventRowSave(block.id, eventRow, { tag: event.target.value || null }, {
                                            forcedTag: forcedEventTag,
                                            allowEndDate: allowEventEndDate,
                                          })
                                        }
                                      />
                                    ) : (
                                      eventRow.tag || "—"
                                    )}
                                  </td>
                                ) : null}
                                {editableEventColumns?.showTitle ? (
                                  <td>
                                    {block.is_editable_snapshot ? (
                                      <input
                                        className="event-field-title"
                                        value={editableEventRow.title}
                                        onChange={(event) =>
                                          queueEventRowSave(block.id, eventRow, { title: event.target.value }, {
                                            forcedTag: forcedEventTag,
                                            allowEndDate: allowEventEndDate,
                                          })
                                        }
                                      />
                                    ) : (
                                      eventRow.title
                                    )}
                                  </td>
                                ) : null}
                                {editableEventColumns?.showDescription ? (
                                  <td>
                                    {block.is_editable_snapshot ? (
                                      <input
                                        className="event-field-description"
                                        value={editableEventRow.description ?? ""}
                                        onChange={(event) =>
                                          queueEventRowSave(block.id, eventRow, { description: event.target.value || null }, {
                                            forcedTag: forcedEventTag,
                                            allowEndDate: allowEventEndDate,
                                          })
                                        }
                                      />
                                    ) : (
                                      eventRow.description || "—"
                                    )}
                                  </td>
                                ) : null}
                                {editableEventColumns?.showParticipantCount ? (
                                  <td className="event-column-count">
                                    {block.is_editable_snapshot ? (
                                      <input
                                        type="number"
                                        className="event-field-count"
                                        min="0"
                                        value={editableEventRow.participant_count ?? 0}
                                        onChange={(event) =>
                                          queueEventRowSave(block.id, eventRow, {
                                            participant_count: Math.max(0, Number(event.target.value || "0")),
                                          }, {
                                            forcedTag: forcedEventTag,
                                            allowEndDate: allowEventEndDate,
                                          })
                                        }
                                      />
                                    ) : (
                                      eventRow.participant_count ?? 0
                                    )}
                                  </td>
                                ) : null}
                                {block.is_editable_snapshot ? (
                                  <td>
                                    <div className="event-row-actions">
                                      <button
                                        type="button"
                                        className="button-ghost button-icon button-icon-danger"
                                        title="Termin löschen"
                                        onClick={() => void deleteEventFromBlock(block.id, eventRow.id)}
                                      >
                                        x
                                      </button>
                                    </div>
                                  </td>
                                ) : null}
                              </tr>
                            );
                          })
                        ) : !showNewEventRow ? (
                          <tr>
                            <td colSpan={Number(editableEventColumns?.showDate) + Number(editableEventColumns?.showTag) + Number(editableEventColumns?.showTitle) + Number(editableEventColumns?.showDescription) + Number(editableEventColumns?.showParticipantCount) + Number(block.is_editable_snapshot)}>
                              <span className="muted">Keine passenden Termine.</span>
                            </td>
                          </tr>
                        ) : null}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {elementType === "attendance" && (
                <div className="attendance-list">
                  {availableParticipants.map((participant) => {
                    const currentEntries = Array.isArray(blockConfig.attendance_entries) ? (blockConfig.attendance_entries as Array<Record<string, any>>) : [];
                    const currentEntry = currentEntries.find((entry) => Number(entry.participant_id) === participant.id);
                    const selectedStatus = String(currentEntry?.status ?? "absent");
                    return (
                      <div className="attendance-row" key={`${block.id}-${participant.id}`}>
                        <strong>{participant.display_name}</strong>
                        <div className="segment-control attendance-segment-control">
                          {ATTENDANCE_OPTIONS.map((option) => (
                            <button
                              key={option.value}
                              type="button"
                              className={`segment-button attendance-segment-button${selectedStatus === option.value ? " segment-button-active" : ""}`}
                              onClick={() => {
                                const nextEntries = currentEntries.filter((entry) => Number(entry.participant_id) !== participant.id);
                                nextEntries.push({
                                  participant_id: participant.id,
                                  participant_name: participant.display_name,
                                  status: option.value,
                                });
                                void saveBlockConfiguration(block.id, { ...blockConfig, attendance_entries: nextEntries });
                              }}
                            >
                              {option.label}
                            </button>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {elementType === "session_date" && (
                <div className="two-col">
                  <label className="field-stack">
                    <span className="field-label">Nächste Sitzung</span>
                    <input
                      type="date"
                      value={String(blockConfig.selected_date ?? "")}
                      onChange={(event) => patchBlockConfigValue(block.id, "selected_date", event.target.value || null, blockConfig)}
                    />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">Template fuer naechstes Protokoll</span>
                    <select
                      value={String(blockConfig.followup_template_id ?? protocol.template_id ?? "")}
                      onChange={(event) => {
                        const nextTemplateId = Number(event.target.value);
                        const normalizedValue =
                          !nextTemplateId || nextTemplateId === protocol.template_id ? null : nextTemplateId;
                        patchBlockConfigValue(block.id, "followup_template_id", normalizedValue, blockConfig);
                      }}
                    >
                      <option value={protocol.template_id ?? ""}>Gleiches Template wie dieses Protokoll</option>
                      {availableTemplates
                        .filter((template) => template.id !== protocol.template_id && template.status !== "archived")
                        .map((template) => (
                          <option key={template.id} value={template.id}>
                            {template.name}
                          </option>
                        ))}
                    </select>
                    <span className="field-help">Standardmaessig wird wieder dieses Template verwendet. Hier kannst du fuer das automatisch erzeugte Folgeprotokoll aber ein anderes waehlen.</span>
                  </label>
                </div>
              )}

              {elementType === "image" && (
                <div className="grid">
                  <div className="two-col">
                    <input
                      type="file"
                      accept="image/*"
                      onChange={(event) =>
                        setSelectedFiles((current) => ({ ...current, [block.id]: event.target.files?.[0] ?? null }))
                      }
                    />
                    <button type="button" onClick={() => uploadImage(block.id)} disabled={!selectedFiles[block.id]}>
                      Upload image
                    </button>
                  </div>
                  <div className="image-grid">
                    {(imagesByBlock[block.id] ?? []).map((image) => (
                      <div className="card image-card" key={image.id}>
                        <img alt={image.title ?? image.original_name} src={`${browserApiBaseUrl}${image.content_url}`} />
                        <p className="muted">{image.original_name}</p>
                        <button type="button" onClick={() => deleteImage(block.id, image.id)}>
                          Delete image
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </section>
          );
        })}
      </div>
      <div className={`editor-panel-footer${hasNextElement ? " editor-panel-footer-split" : ""}`}>
        <button type="button" className="button-ghost" onClick={() => router.push("/protocols")}>
          Zur Protokoll-Liste
        </button>
        {hasNextElement ? (
          <button type="button" className="button-inline" onClick={onNextElement}>
            Weiter
          </button>
        ) : null}
      </div>
    </section>
    <Modal
      open={Boolean(multiParticipantPicker)}
      onClose={() => {
        setMultiParticipantPicker(null);
        setMultiParticipantSearch("");
      }}
      title={multiParticipantPicker ? `Teilnehmer waehlen: ${multiParticipantPicker.rowLabel}` : "Teilnehmer waehlen"}
      description="Suche nach Teilnehmern und markiere mehrere Eintraege mit Haken."
    >
      <div className="grid">
        <label className="field-stack">
          <span className="field-label">Suche</span>
          <input
            value={multiParticipantSearch}
            onChange={(event) => setMultiParticipantSearch(event.target.value)}
            placeholder="Teilnehmer suchen"
          />
        </label>
        <div className="status-row">
          <span className="pill">{multiParticipantPicker?.selectedIds.length ?? 0} ausgewaehlt</span>
          <span className="pill">{filteredParticipants.length} sichtbar</span>
        </div>
        <div className="selection-list">
          {filteredParticipants.map((participant) => {
            const checked = multiParticipantPicker?.selectedIds.includes(participant.id) ?? false;
            return (
              <label key={participant.id} className={`selection-card selection-card-checkbox${checked ? " selection-card-active" : ""}`}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggleMultiParticipantSelection(participant.id)}
                />
                <div>
                  <strong>{participant.display_name}</strong>
                  <div className="muted">
                    {[participant.first_name, participant.last_name].filter(Boolean).join(" ") || participant.email || "Teilnehmer"}
                  </div>
                </div>
              </label>
            );
          })}
        </div>
        <div className="table-toolbar-actions table-actions-end">
          <button
            type="button"
            className="button-inline"
            onClick={() => {
              if (multiParticipantPicker) {
                const currentBlock = element.blocks.find((block) => block.id === multiParticipantPicker.blockId);
                if (currentBlock) {
                  applyMultiParticipantSelection(currentBlock.id, asObject(currentBlock.configuration_snapshot_json));
                }
              }
            }}
          >
            Auswahl uebernehmen
          </button>
        </div>
      </div>
    </Modal>
    </>
  );
}
