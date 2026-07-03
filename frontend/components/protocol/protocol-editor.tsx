"use client";

import { Dispatch, Fragment, ReactNode, SetStateAction, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { useToast } from "@/contexts/toast-context";

import { SessionPanel, SessionPanelHandle } from "@/components/protocol/session-panel";
import { TodoAssigneeMenu } from "@/components/todos/todo-assignee-menu";
import { StructuredListTable } from "@/components/lists/structured-list-table";
import { DataToolbar } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { RichTextEditor } from "@/components/ui/rich-text-editor";
import { Modal } from "@/components/ui/modal";
import { TagInput } from "@/components/ui/tag-input";
import { useTagConfig } from "@/lib/hooks/use-tag-config";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { formatDate, formatDateRange } from "@/lib/utils/format";
import {
  AttendanceFine,
  AttendanceFineListItem,
  EventSummary,
  FinanceAccount,
  FinanceTransaction,
  ParticipantSummary,
  ProtocolElement,
  ProtocolImage,
  ProtocolSummary,
  ProtocolTodo,
  SaveState,
  StructuredListDefinition,
  StructuredListEntry,
  TemplateSummary,
  TodoListItem,
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
  availableAccounts: FinanceAccount[];
  initialFinanceTransactions: Record<number, FinanceTransaction[]>;
  initialPendingTodos?: TodoListItem[];
  forceReadOnly?: boolean;
  canViewFines?: boolean;
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

/** Strip trailing "(…)" from section names, e.g. "Gliähwurm (Enea, Archie)" → "Gliähwurm" */
function trimSectionName(name: string): string {
  return name.replace(/\s*\(.*\)$/, "").trim();
}


function formatShortDate(value: string | null | undefined) {
  return formatDate(value);
}

function formatFinanceAmount(amount: number, currency: string): string {
  const formatted = Math.abs(amount).toLocaleString("de-CH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${amount < 0 ? "−" : ""}${formatted} ${currency}`;
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

function attendanceParticipants(participants: ParticipantSummary[]) {
  return participants.filter((participant) => !participant.exclude_from_attendance);
}

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
    "11": "matrix",
    "12": "finance_balance",
    "13": "finance_transactions",
    "14": "fine_list",
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
    const eligibleParticipants = attendanceParticipants(availableParticipants);
    return {
      element_type_id: elementTypeId,
      title: rowLabel || embeddedBlockTypeLabel(elementTypeId),
      block_kind: blockKind,
      configuration_snapshot_json: {
        block_kind: blockKind,
        attendance_entries: eligibleParticipants.map((participant) => ({
          participant_id: participant.id,
          participant_name: participant.display_name,
          status: null,
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
    const tagFilters = String(config.event_tag_filter ?? "").split(",").map((t) => t.trim().toLowerCase()).filter(Boolean);
    const columnTagFilters = config.event_use_column_tag_filter === true
      ? String(matrixColumn?.event_tag_filter || matrixColumn?.title || "").split(",").map((t) => t.trim().toLowerCase()).filter(Boolean) : [];
    const matchingEvents = availableEvents.filter((event) => {
      const effectiveEndDate = event.event_end_date || event.event_date;
      const matchesDate = !protocol.protocol_date ? true : config.event_only_before_protocol_date === true ? effectiveEndDate < protocol.protocol_date : config.event_only_from_protocol_date === false ? true : effectiveEndDate >= protocol.protocol_date;
      const eventTag = (event.tag ?? "").toLowerCase();
      const matchesTag = (!tagFilters.length || tagFilters.some((t) => eventTag.includes(t))) &&
        (!columnTagFilters.length || columnTagFilters.some((t) => eventTag.includes(t)));
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
    const eligibleParticipants = attendanceParticipants(availableParticipants);
    const presentCount = eligibleParticipants.filter((participant) => {
      const entry = entries.find((currentEntry) => Number(currentEntry.participant_id) === participant.id);
      return String(entry?.status ?? "") === "present";
    }).length;
    return eligibleParticipants.length ? `${presentCount}/${eligibleParticipants.length} anwesend` : "0 Teilnehmer";
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
  const [popoverStyle, setPopoverStyle] = useState<React.CSSProperties>({});
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) return;
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setPopoverStyle({
        position: "fixed",
        top: rect.bottom + 6,
        ...(align === "end"
          ? { right: window.innerWidth - rect.right }
          : { left: rect.left }),
        minWidth: Math.max(rect.width, 220),
        zIndex: 9999,
      });
    }
  }, [open, align]);

  useEffect(() => {
    function onPointerDown(event: MouseEvent) {
      const target = event.target as Node;
      if (!triggerRef.current?.contains(target) && !(document.getElementById("due-date-portal")?.contains(target))) {
        setOpen(false);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  const popover = open && typeof document !== "undefined" ? createPortal(
    <div id="due-date-portal" className="mini-menu-popover-portal" style={popoverStyle} role="menu">
      {children(() => setOpen(false))}
    </div>,
    document.body
  ) : null;

  return (
    <div className={`mini-menu${compact ? " mini-menu-compact" : ""}`}>
      <button
        ref={triggerRef}
        type="button"
        className={`mini-menu-trigger${open ? " mini-menu-trigger-open" : ""}`}
        onClick={() => setOpen((current) => !current)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="mini-menu-trigger-label">{label}</span>
        <span className="mini-menu-trigger-icon">⌄</span>
      </button>
      {popover}
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
  const eligibleAttendanceParticipants = useMemo(
    () => attendanceParticipants(availableParticipants),
    [availableParticipants]
  );
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
                const rowType = String(row.value_type ?? row.row_type ?? "text");
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
    const tagFilters = String(embeddedConfig.event_tag_filter ?? "").split(",").map((t) => t.trim().toLowerCase()).filter(Boolean);
    const columnTagFilters = embeddedConfig.event_use_column_tag_filter === true
      ? String(matrixColumn?.event_tag_filter || matrixColumn?.title || "").split(",").map((t) => t.trim().toLowerCase()).filter(Boolean) : [];
    const matchingEvents = sortedEvents.filter((eventRow) => {
      const effectiveEndDate = eventRow.event_end_date || eventRow.event_date;
      const eventTag = (eventRow.tag ?? "").toLowerCase();
      const matchesTag =
        (!tagFilters.length || tagFilters.some((t) => eventTag.includes(t))) &&
        (!columnTagFilters.length || columnTagFilters.some((t) => eventTag.includes(t)));
      const matchesDate = !protocol.protocol_date ? true : embeddedConfig.event_only_before_protocol_date === true ? effectiveEndDate < protocol.protocol_date : embeddedConfig.event_only_from_protocol_date === false ? true : effectiveEndDate >= protocol.protocol_date;
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
                          <DateInput
                            className="event-field-date"
                            value={newEmbeddedEventDraft.event_date}
                            disabled={creatingEmbeddedEvent}
                            onChange={(value) => patchNewEmbeddedEventDraft({ event_date: value })}
                          />
                          {allowEmbeddedEndDate ? (
                            <DateInput
                              className="event-field-date"
                              value={newEmbeddedEventDraft.event_end_date}
                              disabled={creatingEmbeddedEvent}
                              onChange={(value) => patchNewEmbeddedEventDraft({ event_end_date: value })}
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
                          onFocus={(e) => e.target.select()}
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
                              <DateInput
                                className="event-field-date"
                                value={editableEventRow.event_date}
                                onChange={(value) => queueEmbeddedEventSave(eventRow, { event_date: value })}
                              />
                              {allowEmbeddedEndDate ? (
                                <DateInput
                                  className="event-field-date"
                                  value={editableEventRow.event_end_date ?? ""}
                                  onChange={(value) => queueEmbeddedEventSave(eventRow, { event_end_date: value || null })}
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
                              onFocus={(e) => e.target.select()}
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
            {eligibleAttendanceParticipants.map((participant) => {
              const currentEntry = attendanceEntries.find((entry) => Number(entry.participant_id) === participant.id);
              return (
                <div className="matrix-static-list-item" key={`embedded-attendance-${participant.id}`}>
                  <strong>{participant.display_name}</strong>: {currentEntry?.status ? attendanceStatusLabel(currentEntry.status) : "—"}
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
          {eligibleAttendanceParticipants.map((participant) => {
            const currentEntry = attendanceEntries.find((entry) => Number(entry.participant_id) === participant.id);
            const selectedStatus = currentEntry?.status ?? null;
            return (
              <div className="attendance-row" key={`embedded-attendance-${participant.id}`}>
                <span className="attendance-name">{participant.display_name}</span>
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
            <DateInput
              value={String(embeddedConfig.selected_date ?? "")}
              onChange={(value) =>
                updateEmbeddedConfig((current) => ({
                  ...current,
                  selected_date: value || null,
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
  availableAccounts,
  initialFinanceTransactions,
  initialPendingTodos = [],
  forceReadOnly = false,
  canViewFines = true,
}: ProtocolEditorProps) {
  const router = useRouter();
  const [elements, setElements] = useState(initialElements);
  const [events, setEvents] = useState(availableEvents);
  const [listEntriesByDefinition, setListEntriesByDefinition] = useState<Record<number, StructuredListEntry[]>>(initialListEntries);
  const [todosByBlock, setTodosByBlock] = useState<Record<number, ProtocolTodo[]>>(initialTodos);
  const [pendingTodos, setPendingTodos] = useState<TodoListItem[]>(initialPendingTodos);
  const [imagesByBlock, setImagesByBlock] = useState<Record<number, ProtocolImage[]>>(initialImages);
  const [financeTransactions, setFinanceTransactions] = useState<Record<number, FinanceTransaction[]>>(initialFinanceTransactions);
  const [protocolFines, setProtocolFines] = useState<AttendanceFine[]>([]);
  const [pendingFines, setPendingFines] = useState<AttendanceFineListItem[]>([]);
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
  const [newTodoTags, setNewTodoTags] = useState<Record<number, string>>({});
  const [todoTagFilter, setTodoTagFilter] = useState<Record<number, string | null>>({});
  const [newEventDrafts, setNewEventDrafts] = useState<Record<number, ProtocolEventDraft>>({});
  const [selectedFiles, setSelectedFiles] = useState<Record<number, File | null>>({});
  const [blockStatus, setBlockStatus] = useState<Record<number, SaveState>>({});
  const [selectedElementId, setSelectedElementId] = useState<number | null>(initialElements[0]?.id ?? null);
  const [draggedElementId, setDraggedElementId] = useState<number | null>(null);
  const [protocolStatus, setProtocolStatus] = useState(protocol.status);
  const [sessionNotes, setSessionNotes] = useState(protocol.session_notes ?? "");
  const [transitioningStatus, setTransitioningStatus] = useState(false);
  const showToast = useToast();
  const elementSaveTimerRef = useRef<number | null>(null);
  const isRestoringRef = useRef(true);
  const [showSavedIndicator, setShowSavedIndicator] = useState(false);
  const savedIndicatorTimerRef = useRef<number | null>(null);
  const prevBlockStatusRef = useRef<Record<number, SaveState>>({});

  useEffect(() => {
    if (!canViewFines) return;
    browserApiFetch<AttendanceFine[]>(`/api/protocols/${protocol.id}/fines`)
      .then((data) => { if (data) setProtocolFines(data); })
      .catch(() => { /* silently ignore 403 for restricted roles */ });
    browserApiFetch<AttendanceFineListItem[]>(`/api/protocols/${protocol.id}/pending-fines`)
      .then((data) => { if (data) setPendingFines(data); })
      .catch(() => {});
  }, [protocol.id, canViewFines]);

  // Restore last active element from backend
  useEffect(() => {
    browserApiFetch<{ element_id: number | null }>(`/api/protocols/${protocol.id}/scroll-position`)
      .then((data) => {
        isRestoringRef.current = false;
        if (!data?.element_id) return;
        const id = data.element_id;
        if (initialElements.some((e) => e.id === id)) {
          shouldScrollToElementRef.current = true;
          setSelectedElementId(id);
        }
      })
      .catch(() => { isRestoringRef.current = false; });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [protocol.id]);

  // Save active element to backend (debounced, skip during initial restore)
  useEffect(() => {
    if (!selectedElementId || isRestoringRef.current) return;
    if (elementSaveTimerRef.current) window.clearTimeout(elementSaveTimerRef.current);
    elementSaveTimerRef.current = window.setTimeout(() => {
      void browserApiFetch(`/api/protocols/${protocol.id}/scroll-position`, {
        method: "PUT",
        body: JSON.stringify({ element_id: selectedElementId }),
      });
    }, 800);
    return () => {
      if (elementSaveTimerRef.current) window.clearTimeout(elementSaveTimerRef.current);
    };
  }, [selectedElementId, protocol.id]);

  // Editing mode derived from status and role
  const forceEditable = !forceReadOnly && (protocolStatus === "geplant" || protocolStatus === "durchgeführt");
  const isReadOnly = forceReadOnly || protocolStatus === "abgeschlossen";
  const isPrepareMode = (protocolStatus === "geplant" || protocolStatus === "durchgeführt") && !forceReadOnly;

  const workflowMeta: Record<string, { modeLabel: string; ctaLabel: string; nextStatus: string }> = {
    geplant:       { modeLabel: "Vorbereitungsmodus",   ctaLabel: "Vorbereitung abschliessen", nextStatus: "vorbereitet" },
    vorbereitet:   { modeLabel: "Sitzungsmodus",         ctaLabel: "Sitzung abschliessen",      nextStatus: "durchgeführt" },
    durchgeführt:  { modeLabel: "Nachbearbeitungsmodus", ctaLabel: "Protokoll abschliessen",    nextStatus: "abgeschlossen" },
    abgeschlossen: { modeLabel: "Abgeschlossen",         ctaLabel: "",                          nextStatus: "" },
  };


  const transitionStatus = async () => {
    const next = workflowMeta[protocolStatus]?.nextStatus;
    if (!next) return;

    if (next === "abgeschlossen") {
      const hasRealContent = (s: string | null | undefined) => /[\p{L}\p{N}]/u.test(s ?? "");
      const missingComment = (f: { status: string; delete_comment: string | null }) =>
        f.status === "deleted" && !hasRealContent(f.delete_comment);
      const missing = [
        ...protocolFines.filter(missingComment),
        ...pendingFines.filter(missingComment),
      ];
      if (missing.length > 0) {
        const fineTypeLabel = (t: string) => t === "late" ? "Verspätet" : "Unentschuldigt";
        const names = missing.map((f) => `${f.participant_name_snapshot} (${fineTypeLabel(f.fine_type)})`).join(", ");
        const firstId = missing[0].id;
        showToast(`Fehlender Kommentar bei gelöschten Bussen: ${names} – klicken zum Hinspringen`, "error", {
          onMessageClick: () => {
            const el = document.getElementById(`fine-row-${firstId}`);
            if (el) {
              el.scrollIntoView({ behavior: "smooth", block: "center" });
              el.classList.add("fine-row-highlight");
              setTimeout(() => el.classList.remove("fine-row-highlight"), 1800);
            }
          },
        });
        return;
      }
    }

    setTransitioningStatus(true);
    try {
      await browserApiFetch(`/api/protocols/${protocol.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: next }),
      });
      setProtocolStatus(next);
      router.refresh();
      router.push("/protocols");
    } catch (err: unknown) {
      if (err instanceof Error) showToast(err.message);
    } finally {
      setTransitioningStatus(false);
    }
  };
  const timers = useRef<Record<number, number>>({});
  const shouldScrollToElementRef = useRef(false);
  const navRef = useRef<HTMLElement | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const sessionPanelRef = useRef<SessionPanelHandle | null>(null);
  const editorRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = editorRef.current;
    if (!el) return;
    // Slight delay lets the browser finish layout before scrolling
    const t = window.setTimeout(() => {
      const top = el.getBoundingClientRect().top + window.scrollY - 24;
      window.scrollTo({ top, behavior: "smooth" });
    }, 120);
    return () => window.clearTimeout(t);
  }, []);

  useEffect(() => {
    return () => {
      Object.values(timers.current).forEach((timerId) => window.clearTimeout(timerId));
    };
  }, []);

  useEffect(() => {
    const prev = prevBlockStatusRef.current;
    const justSaved = Object.entries(blockStatus).some(
      ([id, state]) => state === "saved" && prev[Number(id)] === "saving"
    );
    prevBlockStatusRef.current = { ...blockStatus };
    if (justSaved) {
      setShowSavedIndicator(true);
      if (savedIndicatorTimerRef.current) window.clearTimeout(savedIndicatorTimerRef.current);
      savedIndicatorTimerRef.current = window.setTimeout(() => setShowSavedIndicator(false), 2000);
    }
  }, [blockStatus]);

  const visibleElements = useMemo(
    () =>
      [...elements]
        .filter((element) => element.is_visible_snapshot)
        .map((element) => ({
          ...element,
          blocks: [...element.blocks]
            .filter((block) => (isPrepareMode || block.is_visible_snapshot) && block.element_type_code !== "display")
            .sort((left, right) => left.sort_index - right.sort_index)
        }))
        .filter((element) => element.blocks.length > 0 || element.show_when_empty)
        .sort((left, right) => left.sort_index - right.sort_index),
    [elements, isPrepareMode]
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
      const inFormField = target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);

      // Ctrl+Alt+T → open session panel and focus todo input
      if (event.key === "t" && (event.ctrlKey || event.metaKey) && event.altKey) {
        event.preventDefault();
        sessionPanelRef.current?.openAndFocusTodo();
        return;
      }

      // Ctrl+Alt+N → open session panel and focus notes
      if (event.key === "n" && (event.ctrlKey || event.metaKey) && event.altKey) {
        event.preventDefault();
        sessionPanelRef.current?.openAndFocusNotes();
        return;
      }

      // Ctrl+Shift+Enter → go to previous element
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && event.shiftKey) {
        if (!visibleElements.length) return;
        const currentIndex = visibleElements.findIndex((el) => el.id === selectedElementId);
        const prevIndex = currentIndex <= 0 ? 0 : currentIndex - 1;
        if (currentIndex > 0) {
          event.preventDefault();
          focusElement(visibleElements[prevIndex].id);
        }
        return;
      }

      // Ctrl+Enter → advance to next element (works everywhere, including form fields)
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        if (!visibleElements.length) return;
        const currentIndex = visibleElements.findIndex((el) => el.id === selectedElementId);
        const nextIndex = currentIndex === -1 ? 0 : currentIndex + 1;
        if (nextIndex < visibleElements.length) {
          event.preventDefault();
          focusElement(visibleElements[nextIndex].id);
        } else if (workflowMeta[protocolStatus]?.ctaLabel) {
          event.preventDefault();
          void transitionStatus();
        }
        return;
      }

      if (inFormField) return;
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      if (!visibleElements.length) return;

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
      const tagsStr = newTodoTags[protocolElementBlockId] ?? "";
      const activeFilter = todoTagFilter[protocolElementBlockId] ?? null;
      const parsedTags = tagsStr ? tagsStr.split(",").map((t) => t.trim()).filter(Boolean) : [];
      if (activeFilter && !parsedTags.includes(activeFilter)) parsedTags.push(activeFilter);
      const created = await browserApiFetch<ProtocolTodo>(`/api/protocol-element-blocks/${protocolElementBlockId}/todos`, {
        method: "POST",
        body: JSON.stringify({ task, tags: parsedTags, todo_status_id: TODO_STATUS.open, created_by: null })
      });
      setTodosByBlock((current) => ({
        ...current,
        [protocolElementBlockId]: [...(current[protocolElementBlockId] ?? []), created].sort((left, right) => left.sort_index - right.sort_index)
      }));
      setNewTodoTask((current) => ({ ...current, [protocolElementBlockId]: "" }));
      setNewTodoTags((current) => ({ ...current, [protocolElementBlockId]: "" }));
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

  async function hideEventBlock(blockId: number) {
    const block = elements.flatMap((e) => e.blocks).find((b) => b.id === blockId);
    if (!block) return;
    const newConfig = { ...(block.configuration_snapshot_json ?? {}), manually_hidden: true };
    updateBlockInState(blockId, (b) => ({ ...b, is_visible_snapshot: false, configuration_snapshot_json: newConfig }));
    try {
      await browserApiFetch(`/api/protocol-element-blocks/${blockId}`, {
        method: "PATCH",
        body: JSON.stringify({ is_visible_snapshot: false, configuration_snapshot_json: newConfig }),
      });
    } catch {
      // revert on error
      updateBlockInState(blockId, (b) => ({ ...b, is_visible_snapshot: true, configuration_snapshot_json: block.configuration_snapshot_json }));
    }
  }

  async function unhideEventBlock(blockId: number) {
    const block = elements.flatMap((e) => e.blocks).find((b) => b.id === blockId);
    if (!block) return;
    const newConfig = { ...(block.configuration_snapshot_json ?? {}), manually_hidden: false };
    updateBlockInState(blockId, (b) => ({ ...b, is_visible_snapshot: true, configuration_snapshot_json: newConfig }));
    try {
      await browserApiFetch(`/api/protocol-element-blocks/${blockId}`, {
        method: "PATCH",
        body: JSON.stringify({ is_visible_snapshot: true, configuration_snapshot_json: newConfig }),
      });
    } catch {
      updateBlockInState(blockId, (b) => ({ ...b, is_visible_snapshot: false, configuration_snapshot_json: block.configuration_snapshot_json }));
    }
  }

  async function removeEventBlock(blockId: number) {
    setElements((current) =>
      current.map((element) => ({
        ...element,
        blocks: element.blocks.filter((b) => b.id !== blockId),
      }))
    );
    try {
      await browserApiFetch(`/api/protocol-element-blocks/${blockId}`, { method: "DELETE" });
    } catch {
      // block stays removed in UI — not critical to revert
    }
  }

  async function handleQuickTodoCreated(blockId: number, _todoId: number, elementId: number) {
    // Fetch updated element (may be newly created session element)
    try {
      const updatedElements = await browserApiFetch<ProtocolElement[]>(`/api/protocols/${protocol.id}/elements`);
      if (updatedElements) {
        const sessionElement = updatedElements.find((e) => e.id === elementId);
        if (sessionElement) {
          setElements((current) => {
            const idx = current.findIndex((e) => e.id === elementId);
            if (idx >= 0) {
              const updated = [...current];
              updated[idx] = sessionElement;
              return updated;
            }
            return [...current, sessionElement];
          });
        }
      }
      const todos = await browserApiFetch<ProtocolTodo[]>(`/api/protocol-element-blocks/${blockId}/todos`);
      if (todos) {
        setTodosByBlock((current) => ({ ...current, [blockId]: todos }));
      }
    } catch {
      // best-effort
    }
  }

  async function addEventBlockToElement(elementId: number, eventId: number): Promise<ProtocolElement["blocks"][number] | null> {
    try {
      const newBlock = await browserApiFetch<ProtocolElement["blocks"][number]>(
        `/api/protocol-elements/${elementId}/blocks/from-event`,
        {
          method: "POST",
          body: JSON.stringify({ event_id: eventId }),
        }
      );
      setElements((current) =>
        current.map((element) =>
          element.id === elementId
            ? { ...element, blocks: [...element.blocks, newBlock] }
            : element
        )
      );
      return newBlock;
    } catch {
      return null;
    }
  }

  return (
    <div className="grid" ref={editorRef}>
      <div className="status-row">
        <span className="pill">{protocol.protocol_number}</span>
        <span className="pill">{workflowMeta[protocolStatus]?.modeLabel ?? protocolStatusLabel(protocolStatus)}</span>
      </div>

      {showSavedIndicator && <div className="save-indicator">✓ Gespeichert</div>}

      <div className="editor-shell">
        <aside className="editor-nav" ref={navRef}>
          {visibleElements.map((element) => (
            <div
              className={`editor-nav-section${draggedElementId === element.id ? " editor-nav-section-dragging" : ""}`}
              key={element.id}
              draggable={!isReadOnly}
              onDragStart={isReadOnly ? undefined : () => setDraggedElementId(element.id)}
              onDragEnd={isReadOnly ? undefined : () => setDraggedElementId(null)}
              onDragOver={isReadOnly ? undefined : (event) => event.preventDefault()}
              onDrop={isReadOnly ? undefined : (event) => {
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
              </button>
            </div>
          ))}
        </aside>

        <article className="editor-panel" ref={panelRef}>
          {selectedElement ? (
            <FocusedElementEditor
              element={selectedElement}
              elementIndex={selectedElementIndex}
              textDrafts={textDrafts}
              todosByBlock={todosByBlock}
              imagesByBlock={imagesByBlock}
              newTodoTask={newTodoTask}
              browserApiBaseUrl={browserApiBaseUrl}
              protocol={protocol}
              availableParticipants={availableParticipants}
              availableEvents={events}
              availableTemplates={availableTemplates}
              availableAccounts={availableAccounts}
              financeTransactions={financeTransactions}
              protocolFines={protocolFines}
              setProtocolFines={setProtocolFines}
              pendingFines={pendingFines}
              setPendingFines={setPendingFines}
              newEventDrafts={newEventDrafts}
              selectedFiles={selectedFiles}
              setTodosByBlock={setTodosByBlock}
              setNewEventDrafts={setNewEventDrafts}
              setSelectedFiles={setSelectedFiles}
              setNewTodoTask={setNewTodoTask}
              saveBlockConfiguration={saveBlockConfiguration}
              updateBlockInState={updateBlockInState}
              handleTextChange={handleTextChange}
              forceEditable={forceEditable}
              isReadOnly={isReadOnly}
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
              todoTagFilter={todoTagFilter}
              setTodoTagFilter={setTodoTagFilter}
              newTodoTags={newTodoTags}
              setNewTodoTags={setNewTodoTags}
              isPrepareMode={isPrepareMode}
              hideEventBlock={hideEventBlock}
              unhideEventBlock={unhideEventBlock}
              removeEventBlock={removeEventBlock}
              addEventBlockToElement={addEventBlockToElement}
              onQuickTodoCreated={handleQuickTodoCreated}
              pendingTodos={pendingTodos}
              onPendingUpdate={(updated) => setPendingTodos((prev) => prev.map((t) => t.id === updated.id ? { ...t, ...updated } : t))}
              onPendingDone={(todoId) => setPendingTodos((prev) => prev.filter((t) => t.id !== todoId))}
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

      {/* Session notes — visible in post-processing mode */}
      {protocolStatus === "durchgeführt" && sessionNotes && (
        <div className="session-notes-inline">
          <div className="session-notes-inline-label">Sitzungsnotizen</div>
          <div className="session-notes-inline-text">{sessionNotes}</div>
        </div>
      )}

      <div className="editor-fixed-actions">
        {!isReadOnly && selectedElementIndex >= 0 && selectedElementIndex < visibleElements.length - 1 ? (
          <button
            type="button"
            className="button-inline"
            onClick={() => {
              const nextElement = visibleElements[selectedElementIndex + 1];
              if (nextElement) focusElement(nextElement.id);
            }}
          >
            Weiter →
          </button>
        ) : !isReadOnly && workflowMeta[protocolStatus]?.ctaLabel ? (
          <button
            type="button"
            className="button-primary"
            disabled={transitioningStatus}
            onClick={transitionStatus}
          >
            {transitioningStatus ? "…" : workflowMeta[protocolStatus]?.ctaLabel}
          </button>
        ) : (
          <a href="/protocols" className="button-inline">← Zurück zu den Protokollen</a>
        )}
      </div>

      {/* Floating session panel — only during active session */}
      {protocolStatus === "vorbereitet" && !forceReadOnly && (
        <SessionPanel
          ref={sessionPanelRef}
          protocol={protocol}
          participants={availableParticipants}
          dueEvents={(() => {
            const tpl = availableTemplates.find((t) => t.id === protocol.template_id);
            const tag = tpl?.todo_due_event_tag?.trim().toLowerCase();
            const today = new Date().toISOString().slice(0, 10);
            const upcoming = events.filter((e) => e.event_date >= today);
            return tag ? upcoming.filter((e) => (e.tag ?? "").toLowerCase().includes(tag)) : upcoming;
          })()}
          currentSectionName={selectedElement ? trimSectionName(selectedElement.section_name_snapshot) : null}
          onSessionNotesChange={(notes) => setSessionNotes(notes)}
          onQuickTodoCreated={(blockId, todoId, elementId) => void handleQuickTodoCreated(blockId, todoId, elementId)}
        />
      )}

    </div>
  );
}

function FocusedElementEditor({
  element,
  elementIndex,
  textDrafts,
  todosByBlock,
  imagesByBlock,
  newTodoTask,
  browserApiBaseUrl,
  protocol,
  availableParticipants,
  availableEvents,
  availableTemplates,
  availableAccounts,
  financeTransactions,
  protocolFines,
  setProtocolFines,
  pendingFines,
  setPendingFines,
  newEventDrafts,
  selectedFiles,
  setTodosByBlock,
  setNewEventDrafts,
  setSelectedFiles,
  setNewTodoTask,
  saveBlockConfiguration,
  updateBlockInState,
  handleTextChange,
  forceEditable,
  isReadOnly,
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
  deleteListEntryFromBlock,
  todoTagFilter,
  setTodoTagFilter,
  newTodoTags,
  setNewTodoTags,
  isPrepareMode,
  hideEventBlock,
  unhideEventBlock,
  removeEventBlock,
  addEventBlockToElement,
  onQuickTodoCreated,
  pendingTodos,
  onPendingUpdate,
  onPendingDone,
}: {
  element: ProtocolElement;
  elementIndex: number;
  textDrafts: Record<number, string>;
  todosByBlock: Record<number, ProtocolTodo[]>;
  imagesByBlock: Record<number, ProtocolImage[]>;
  newTodoTask: Record<number, string>;
  browserApiBaseUrl: string;
  protocol: ProtocolSummary;
  availableParticipants: ParticipantSummary[];
  availableEvents: EventSummary[];
  availableTemplates: TemplateSummary[];
  availableAccounts: FinanceAccount[];
  financeTransactions: Record<number, FinanceTransaction[]>;
  protocolFines: AttendanceFine[];
  setProtocolFines: Dispatch<SetStateAction<AttendanceFine[]>>;
  pendingFines: AttendanceFineListItem[];
  setPendingFines: Dispatch<SetStateAction<AttendanceFineListItem[]>>;
  newEventDrafts: Record<number, ProtocolEventDraft>;
  selectedFiles: Record<number, File | null>;
  setTodosByBlock: Dispatch<SetStateAction<Record<number, ProtocolTodo[]>>>;
  setNewEventDrafts: Dispatch<SetStateAction<Record<number, ProtocolEventDraft>>>;
  setSelectedFiles: Dispatch<SetStateAction<Record<number, File | null>>>;
  setNewTodoTask: Dispatch<SetStateAction<Record<number, string>>>;
  saveBlockConfiguration: (blockId: number, configurationSnapshotJson: Record<string, unknown>) => Promise<void>;
  updateBlockInState: (blockId: number, updater: (current: ProtocolElement["blocks"][number]) => ProtocolElement["blocks"][number]) => void;
  handleTextChange: (protocolElementBlockId: number, content: string) => void;
  forceEditable: boolean;
  isReadOnly: boolean;
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
  todoTagFilter: Record<number, string | null>;
  setTodoTagFilter: Dispatch<SetStateAction<Record<number, string | null>>>;
  newTodoTags: Record<number, string>;
  setNewTodoTags: Dispatch<SetStateAction<Record<number, string>>>;
  isPrepareMode: boolean;
  hideEventBlock: (blockId: number) => Promise<void>;
  unhideEventBlock: (blockId: number) => Promise<void>;
  removeEventBlock: (blockId: number) => Promise<void>;
  addEventBlockToElement: (elementId: number, eventId: number) => Promise<ProtocolElement["blocks"][number] | null>;
  onQuickTodoCreated: (blockId: number, todoId: number, elementId: number) => void | Promise<void>;
  pendingTodos: TodoListItem[];
  onPendingUpdate: (updated: Partial<TodoListItem> & { id: number }) => void;
  onPendingDone: (todoId: number) => void;
}) {
  const sectionRef = useRef<HTMLElement | null>(null);
  const [openBlockMenu, setOpenBlockMenu] = useState<number | null>(null);
  const blockMenuRef = useRef<HTMLDivElement | null>(null);
  const [showEventPicker, setShowEventPicker] = useState(false);
  const [eventPickerSearch, setEventPickerSearch] = useState("");
  const [deleteFineModal, setDeleteFineModal] = useState<{ fineId: number; fromPending: boolean; comment: string } | null>(null);
  const [addingEventBlock, setAddingEventBlock] = useState(false);
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
  const knownEventTags = useMemo(
    () => Array.from(new Set(availableEvents.map((e) => (e.tag ?? "").trim()).filter(Boolean))).sort(),
    [availableEvents]
  );
  const { tagConfig, updateTagColor, renameTag } = useTagConfig();
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
  const eligibleAttendanceParticipants = useMemo(
    () => attendanceParticipants(availableParticipants),
    [availableParticipants]
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
      return todo.resolved_due_date ? `${formatShortDate(todo.resolved_due_date)} (Nächste Sitzung)` : "Nächste Sitzung";
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
        const tagFilters = String(blockConfig.event_tag_filter ?? "").split(",").map((t) => t.trim().toLowerCase()).filter(Boolean);
        const matchesTag = !tagFilters.length || tagFilters.some((t) => (eventRow.tag ?? "").toLowerCase().includes(t));
        const effectiveEndDate = eventRow.event_end_date || eventRow.event_date;
        const matchesDate = !protocol.protocol_date ? true : blockConfig.event_only_before_protocol_date === true ? effectiveEndDate < protocol.protocol_date : blockConfig.event_only_from_protocol_date === false ? true : effectiveEndDate >= protocol.protocol_date;
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
    const tagFilters = String(row.event_tag_filter ?? rc.event_tag_filter ?? "").split(",").map((t) => t.trim().toLowerCase()).filter(Boolean);
    const columnTagFilters = String(column.event_tag_filter ?? "").split(",").map((t) => t.trim().toLowerCase()).filter(Boolean);
    const titleFilter = String(row.event_title_filter ?? rc.event_title_filter ?? "").trim().toLowerCase();
    const useColumnTitleAsTag = (row.use_column_title_as_tag ?? rc.use_column_title_as_tag) !== false;
    const hidePastEvents = (row.hide_past_events ?? rc.hide_past_events) !== false;
    const columnTitle = String(column.title ?? "").trim().toLowerCase();
    return [...availableEvents]
      .filter((event) => {
        const effectiveEndDate = event.event_end_date || event.event_date;
        const matchesPast = !hidePastEvents || !protocol.protocol_date || effectiveEndDate >= protocol.protocol_date;
        const eventTag = (event.tag ?? "").toLowerCase();
        const matchesTag =
          (!tagFilters.length || tagFilters.some((t) => eventTag.includes(t))) &&
          (!columnTagFilters.length || columnTagFilters.some((t) => eventTag.includes(t))) &&
          (!useColumnTitleAsTag || !columnTitle || eventTag.includes(columnTitle));
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
            else if (sourceField === "event_date") text = formatDate(event.event_date);
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
    if (!openBlockMenu) return;
    function handleDocClick(e: MouseEvent) {
      if (blockMenuRef.current && !blockMenuRef.current.contains(e.target as Node)) {
        setOpenBlockMenu(null);
      }
    }
    document.addEventListener("mousedown", handleDocClick);
    return () => document.removeEventListener("mousedown", handleDocClick);
  }, [openBlockMenu]);

  useEffect(() => {
    const fields = sectionRef.current?.querySelectorAll<HTMLTextAreaElement>(".todo-main-compact .todo-input") ?? [];
    fields.forEach((field) => autoResizeTodoField(field));
  }, [element.id, todosByBlock]);

  useEffect(() => {
    const section = sectionRef.current;
    if (!section) return;
    const wraps = section.querySelectorAll<HTMLElement>(".event-table-wrap-scrollable");
    wraps.forEach((wrap) => {
      const upcomingRow = wrap.querySelector<HTMLElement>("tr[data-upcoming]");
      if (!upcomingRow) return;
      const theadH = wrap.querySelector<HTMLElement>("thead")?.offsetHeight ?? 0;
      wrap.scrollTop = upcomingRow.offsetTop - theadH;
    });
  }, [element.id]);

  return (
    <>
    <section id={`protocol-element-${element.id}`} ref={sectionRef}>
      <div className="editor-panel-header">
        <div>
          <div className="eyebrow">Punkt {elementIndex + 1}</div>
          <h2>{element.section_name_snapshot}</h2>
        </div>
      </div>
      <div className="element-block-stack">
        {element.blocks.length === 0 && element.show_when_empty && (
          <div className="element-block-empty-hint">Keine Termine in diesem Zeitraum.</div>
        )}
        {element.blocks.map((block) => {
          const blockTitle = visibleBlockTitle(block);
          const elementType = block.element_type_code ?? "unknown";
          const blockConfig = asObject(block.configuration_snapshot_json);
          // Effective editability: forced open in geplant/durchgeführt, locked in abgeschlossen
          const blockEditable = !isReadOnly && (forceEditable || block.is_editable_snapshot);
          const editableEventRows = elementType === "event_list" ? eventRowsForBlock(blockConfig) : [];
          const editableEventColumns = elementType === "event_list" ? eventColumnVisibility(blockConfig) : null;
          const forcedEventTag = elementType === "event_list" ? String(blockConfig.event_tag_filter ?? "").trim() : "";
          const allowEventEndDate = elementType === "event_list" ? blockConfig.event_allow_end_date === true : false;
          const firstUpcomingIndex = elementType === "event_list" ? editableEventRows.findIndex((row) => {
            const endDate = row.event_end_date || row.event_date;
            return !(protocol.protocol_date && endDate < protocol.protocol_date);
          }) : -1;
          const hasPastEvents = elementType === "event_list" && editableEventRows.some((row) => {
            const endDate = row.event_end_date || row.event_date;
            return !!(protocol.protocol_date && endDate < protocol.protocol_date);
          });
          const newEventDraft =
            elementType === "event_list" ? newEventDrafts[block.id] ?? newEventRowDraft(blockConfig) : null;
          const showNewEventRow = elementType === "event_list" ? openNewEventRows[block.id] === true : false;
          const creatingNewEventRow = elementType === "event_list" ? creatingNewEventRows[block.id] === true : false;
          const allowMatrixColumnManagement =
            elementType === "matrix" ? blockEditable && (blockConfig.allow_column_management === true || blockConfig.matrix_allow_column_management === true) : false;
          const todoDueTagFilters = elementType === "todo"
            ? String(blockConfig.todo_due_tag_filter ?? "").split(",").map((t) => t.trim().toLowerCase()).filter(Boolean)
            : [];
          const todoDueEvents = elementType === "todo"
            ? [...availableEvents]
                .filter((e) => !todoDueTagFilters.length || todoDueTagFilters.some((f) => (e.tag ?? "").toLowerCase().includes(f)))
                .sort((a, b) => a.event_date.localeCompare(b.event_date))
            : [];
          const isAutoEventBlock = blockConfig.repeat_source_type === "event" && blockConfig.repeat_source_id != null;
          const isHidden = !block.is_visible_snapshot;
          return (
            <section className={`card editor-block-card${elementType === "event_list" ? " editor-block-card-event-list" : ""}${isHidden ? " editor-block-card-hidden" : ""}`} key={block.id}>
              <div className="editor-panel-header">
                <div>
                  <div className="eyebrow">{elementType}{isHidden ? " · ausgeblendet" : ""}</div>
                  {blockTitle ? <h3>{blockTitle}</h3> : null}
                  {block.description_snapshot ? <p className="muted">{block.description_snapshot}</p> : null}
                </div>
                {isPrepareMode && isAutoEventBlock && (
                  <div className="block-menu-wrap" ref={openBlockMenu === block.id ? blockMenuRef : undefined}>
                    <button
                      type="button"
                      className="btn-icon-sm block-menu-trigger"
                      title="Optionen"
                      onClick={() => setOpenBlockMenu((prev) => prev === block.id ? null : block.id)}
                    >
                      ⋮
                    </button>
                    {openBlockMenu === block.id && (
                      <div className="block-menu-dropdown">
                        {isHidden ? (
                          <button
                            type="button"
                            className="block-menu-item"
                            onClick={() => { setOpenBlockMenu(null); void unhideEventBlock(block.id); }}
                          >
                            Einblenden
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="block-menu-item"
                            onClick={() => { setOpenBlockMenu(null); void hideEventBlock(block.id); }}
                          >
                            Ausblenden
                          </button>
                        )}
                        <button
                          type="button"
                          className="block-menu-item block-menu-item-danger"
                          onClick={() => { setOpenBlockMenu(null); void removeEventBlock(block.id); }}
                        >
                          Entfernen
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {(elementType === "text" || elementType === "static_text") && (
                <RichTextEditor
                  value={textDrafts[block.id] ?? ""}
                  onChange={(md) => handleTextChange(block.id, md)}
                  readOnly={!blockEditable}
                  placeholder="Text schreiben… Fett mit **text**, kursiv mit *text*, Liste mit - oder 1."
                />
              )}

              {elementType === "todo" && (() => {
                const blockTodos = todosByBlock[block.id] ?? [];
                const allBlockTags = Array.from(new Set(blockTodos.flatMap((t) => t.tags ?? []))).sort();
                const activeTag = todoTagFilter[block.id] ?? null;
                const visibleTodos = activeTag ? blockTodos.filter((t) => (t.tags ?? []).includes(activeTag)) : blockTodos;
                return (
                <div className="grid">
                  {allBlockTags.length > 0 && (
                    <div className="tag-filter-bar">
                      <button
                        type="button"
                        className={`tag-filter-chip${activeTag === null ? " tag-filter-chip-active" : ""}`}
                        onClick={() => setTodoTagFilter((c) => ({ ...c, [block.id]: null }))}
                      >
                        Alle
                      </button>
                      {allBlockTags.map((tag) => (
                        <button
                          key={tag}
                          type="button"
                          className={`tag-filter-chip${activeTag === tag ? " tag-filter-chip-active" : ""}`}
                          onClick={() => setTodoTagFilter((c) => ({ ...c, [block.id]: c[block.id] === tag ? null : tag }))}
                        >
                          {tag}
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="todo-list">
                    {visibleTodos.map((todo) => {
                      const isDone = todo.todo_status_code === "done";
                      return (
                        <article className={`todo-card todo-card-compact${isDone ? " todo-card-done" : ""}`} key={todo.id}>
                          <button
                            type="button"
                            className={`todo-toggle${isDone ? " todo-toggle-done" : ""}`}
                            disabled={!blockEditable}
                            onClick={() =>
                              blockEditable && updateTodo(block.id, todo.id, {
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
                              readOnly={!blockEditable}
                              onInput={(event) => autoResizeTodoField(event.currentTarget)}
                              onChange={(event) => {
                                if (!blockEditable) return;
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
                          {blockEditable && (
                          <div className="todo-inline-meta">
                            <TodoAssigneeMenu
                              label={todo.assigned_participant_name ?? "Niemand"}
                              participants={availableParticipants}
                              activeId={todo.assigned_participant_id}
                              onChange={(option) => {
                                setTodosByBlock((current) => ({
                                  ...current,
                                  [block.id]: (current[block.id] ?? []).map((item) =>
                                    item.id === todo.id
                                      ? { ...item, assigned_participant_id: option.id, assigned_participant_name: option.id ? option.display_name : null }
                                      : item
                                  ),
                                }));
                                void updateTodo(block.id, todo.id, { assigned_participant_id: option.id });
                              }}
                            />
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
                                  label="Nächste Sitzung"
                                  active={todo.due_marker === "next_session"}
                                  onClick={() => {
                                    void updateTodo(block.id, todo.id, { due_date: null, due_event_id: null, due_marker: "next_session" });
                                    closeMenu();
                                  }}
                                />
                              </div>
                              {todoDueEvents.length ? (
                                <div className="mini-menu-section">
                                  <div className="mini-menu-section-title">Termine</div>
                                  {todoDueEvents.map((event) => (
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
                                  <DateInput
                                    value={todo.due_date}
                                    readOnly={!blockEditable}
                                    onChange={(value) => {
                                      if (!blockEditable) return;
                                      void updateTodo(block.id, todo.id, {
                                        due_date: value || null,
                                        due_event_id: null,
                                        due_marker: null,
                                      });
                                    }}
                                  />
                                ) : (
                                  <span className="pill">
                                    {formatDate(todo.resolved_due_date ?? todo.due_date) || todo.resolved_due_label || ""}
                                    {formatDate(todo.resolved_due_date ?? todo.due_date) && todo.resolved_due_label ? ` (${todo.resolved_due_label})` : ""}
                                  </span>
                                )}
                              </div>
                            ) : null}
                          </div>
                          )}
                          {(todo.tags ?? []).length > 0 && (
                            <div className="todo-tags-row">
                              {(todo.tags ?? []).map((tag) => (
                                <span key={tag} className="tag-chip tag-chip-sm">{tag}</span>
                              ))}
                            </div>
                          )}
                          {blockEditable && (
                            <button
                              type="button"
                              className="button-inline button-danger todo-delete"
                              onClick={() => deleteTodo(block.id, todo.id)}
                            >
                              Delete
                            </button>
                          )}
                        </article>
                      );
                    })}
                  </div>
                  {blockEditable && (
                    <div className="todo-create todo-create-inline">
                      <input
                        value={newTodoTask[block.id] ?? ""}
                        onChange={(event) => setNewTodoTask((current) => ({ ...current, [block.id]: event.target.value }))}
                        onKeyDown={(e) => { if (e.key === "Enter") void addTodo(block.id); }}
                        placeholder="Neue Aufgabe"
                      />
                      <TagInput
                        value={newTodoTags[block.id] ?? ""}
                        onChange={(v) => setNewTodoTags((c) => ({ ...c, [block.id]: v }))}
                        suggestions={allBlockTags}
                        placeholder="Tags…"
                      />
                      <button type="button" onClick={() => addTodo(block.id)}>
                        + Todo
                      </button>
                    </div>
                  )}
                </div>
                );
              })()}

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
                    const linkedListGroupBy =
                      blockConfig.linked_list_group_by === "column_one" || blockConfig.linked_list_group_by === "column_two"
                        ? blockConfig.linked_list_group_by
                        : "";
                    const linkedListSortBy =
                      blockConfig.linked_list_sort_by === "column_one" || blockConfig.linked_list_sort_by === "column_two"
                        ? blockConfig.linked_list_sort_by
                        : "";
                    const linkedListSortDirection = blockConfig.linked_list_sort_direction === "desc" ? "desc" : "asc";
                    const listColOptions = [
                      { value: "column_one", label: linkedListDefinition.column_one_title },
                      { value: "column_two", label: linkedListDefinition.column_two_title },
                    ];
                    return (
                      <div className="grid">
                        <div className="list-block-config-bar">
                          <label className="list-block-config-item">
                            <span className="list-block-config-label">Gruppieren</span>
                            <select
                              value={linkedListGroupBy}
                              disabled={!blockEditable}
                              onChange={(e) => void saveBlockConfiguration(block.id, { ...blockConfig, linked_list_group_by: e.target.value || null })}
                            >
                              <option value="">Keine Gruppierung</option>
                              {listColOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                            </select>
                          </label>
                          <label className="list-block-config-item">
                            <span className="list-block-config-label">Sortieren</span>
                            <select
                              value={linkedListSortBy}
                              disabled={!blockEditable}
                              onChange={(e) => void saveBlockConfiguration(block.id, { ...blockConfig, linked_list_sort_by: e.target.value || null, linked_list_sort_direction: e.target.value ? linkedListSortDirection : "asc" })}
                            >
                              <option value="">Manuell</option>
                              {listColOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                            </select>
                          </label>
                          <label className="list-block-config-item">
                            <select
                              value={linkedListSortDirection}
                              disabled={!blockEditable || !linkedListSortBy}
                              onChange={(e) => void saveBlockConfiguration(block.id, { ...blockConfig, linked_list_sort_direction: e.target.value })}
                            >
                              <option value="asc">A–Z</option>
                              <option value="desc">Z–A</option>
                            </select>
                          </label>
                        </div>
                        <StructuredListTable
                          definition={linkedListDefinition}
                          entries={listEntriesByDefinition[linkedListId] ?? []}
                          availableParticipants={availableParticipants}
                          availableEvents={availableEvents}
                          editable={blockEditable}
                          emptyMessage="Noch keine Eintraege in dieser Liste."
                          groupByColumn={linkedListGroupBy}
                          sortByColumn={linkedListSortBy}
                          sortDirection={linkedListSortDirection}
                          onCreateEntry={(payload) => createListEntryFromBlock(block.id, linkedListId, payload)}
                          onUpdateEntry={(entryId, payload) => updateListEntryFromBlock(block.id, linkedListId, entryId, payload)}
                          onDeleteEntry={(entryId) => deleteListEntryFromBlock(block.id, linkedListId, entryId)}
                        />
                      </div>
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
                        {((Array.isArray(blockConfig.rows) ? blockConfig.rows : []) as Array<Record<string, any>>).map((row, index) => {
                          const rowType = String(row.value_type ?? row.row_type ?? "text");
                          return (
                          <div className="form-block-row" key={`${block.id}-form-${index}`}>
                            <div className="field-label-inline">{row.label ?? `Feld ${index + 1}`}</div>
                            {rowType === "participant" ? (
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
                            ) : rowType === "participants" ? (
                              <button
                                type="button"
                                className="button-ghost form-participant-picker-button"
                                onClick={() => openMultiParticipantPicker(block.id, index, row)}
                              >
                                {multiParticipantSummary(row)}
                              </button>
                            ) : rowType === "event" ? (
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
                        );})}
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
                                const cellEditable = !isPlaceholder && blockEditable && (forceEditable || matrixRowEditable(row));
                                const autoEvents = (!isPlaceholder && !embeddedBlock && matrixRowType(row) === "events")
                                  ? matrixEventsForRow(row, column!) : [];
                                return (
                                  <div key={`${rowId}-${columnIndex}`} className="matrix-card-row">
                                    <div className={`matrix-card-row-label${(!forceEditable && !matrixRowEditable(row)) ? " matrix-row-locked" : ""}`}>
                                      {row.label ?? `Zeile ${rowIndex + 1}`}
                                      {(!forceEditable && !matrixRowEditable(row)) ? <span className="matrix-lock-icon"> 🔒</span> : null}
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
                <div className="grid event-list-grid">
                  <div className={`event-table-wrap${hasPastEvents ? " event-table-wrap-scrollable" : ""}`}>
                    <table className="data-table event-table event-table-compact">
                      <thead>
                        <tr>
                          {editableEventColumns?.showDate ? <th>Dat.</th> : null}
                          {editableEventColumns?.showTag ? <th>Tag</th> : null}
                          {editableEventColumns?.showTitle ? <th>Titel</th> : null}
                          {editableEventColumns?.showDescription ? <th>Beschreibung</th> : null}
                          {editableEventColumns?.showParticipantCount ? <th className="event-column-count">TN</th> : null}
                          {blockEditable ? (
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
                        {blockEditable && showNewEventRow && newEventDraft ? (
                          <tr className="event-row-new">
                            {editableEventColumns?.showDate ? (
                              <td>
                                <div className={`event-date-fields${allowEventEndDate ? " event-date-fields-range" : ""}`}>
                                  <DateInput
                                    className="event-field-date"
                                    value={newEventDraft.event_date}
                                    disabled={creatingNewEventRow}
                                    onChange={(value) => patchNewEventDraft(block.id, blockConfig, { event_date: value })}
                                  />
                                  {allowEventEndDate ? (
                                    <DateInput
                                      className="event-field-date"
                                      value={newEventDraft.event_end_date}
                                      disabled={creatingNewEventRow}
                                      onChange={(value) => patchNewEventDraft(block.id, blockConfig, { event_end_date: value })}
                                    />
                                  ) : null}
                                </div>
                              </td>
                            ) : null}
                            {editableEventColumns?.showTag ? (
                              <td>
                                <TagInput
                                  value={forcedEventTag || newEventDraft.tag}
                                  onChange={(v) => patchNewEventDraft(block.id, blockConfig, { tag: v })}
                                  suggestions={knownEventTags}
                                  placeholder="Tag"
                                  multi={false}
                                  readOnly={Boolean(forcedEventTag) || creatingNewEventRow}
                                  tagConfig={tagConfig}
                                  onTagColorChange={updateTagColor}
                                  onTagRename={renameTag}
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
                                  onFocus={(e) => e.target.select()}
                                  placeholder="TN"
                                />
                              </td>
                            ) : null}
                            {blockEditable ? (
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
                          editableEventRows.map((eventRow, rowIndex) => {
                            const effectiveEndDate = eventRow.event_end_date || eventRow.event_date;
                            const isPast = !!protocol.protocol_date && effectiveEndDate < protocol.protocol_date;
                            const editableEventRow = eventDraftValue(eventRow);
                            return (
                              <tr
                                key={eventRow.id}
                                className={isPast && blockConfig.event_gray_past !== false ? "event-row-past" : ""}
                                data-upcoming={rowIndex === firstUpcomingIndex ? "true" : undefined}
                              >
                                {editableEventColumns?.showDate ? (
                                  <td>
                                    {blockEditable ? (
                                      <div className={`event-date-fields${allowEventEndDate ? " event-date-fields-range" : ""}`}>
                                        <DateInput
                                          className="event-field-date"
                                          value={editableEventRow.event_date}
                                          onChange={(value) =>
                                            queueEventRowSave(block.id, eventRow, { event_date: value }, {
                                              forcedTag: forcedEventTag,
                                              allowEndDate: allowEventEndDate,
                                            })
                                          }
                                        />
                                        {allowEventEndDate ? (
                                          <DateInput
                                            className="event-field-date"
                                            value={editableEventRow.event_end_date ?? ""}
                                            onChange={(value) =>
                                              queueEventRowSave(block.id, eventRow, { event_end_date: value || null }, {
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
                                    {blockEditable ? (
                                      <TagInput
                                        value={editableEventRow.tag ?? forcedEventTag ?? ""}
                                        onChange={(v) =>
                                          queueEventRowSave(block.id, eventRow, { tag: v || null }, {
                                            forcedTag: forcedEventTag,
                                            allowEndDate: allowEventEndDate,
                                          })
                                        }
                                        suggestions={knownEventTags}
                                        placeholder="Tag"
                                        multi={false}
                                        readOnly={Boolean(forcedEventTag)}
                                        tagConfig={tagConfig}
                                        onTagColorChange={updateTagColor}
                                        onTagRename={renameTag}
                                      />
                                    ) : blockConfig.event_show_tag_colors && eventRow.tag && tagConfig[eventRow.tag]?.color ? (
                                      <span
                                        className="tag-color-badge"
                                        style={{
                                          backgroundColor: `${tagConfig[eventRow.tag].color}22`,
                                          color: tagConfig[eventRow.tag].color,
                                          borderColor: `${tagConfig[eventRow.tag].color}55`,
                                        }}
                                      >
                                        {eventRow.tag}
                                      </span>
                                    ) : (
                                      eventRow.tag || "—"
                                    )}
                                  </td>
                                ) : null}
                                {editableEventColumns?.showTitle ? (
                                  <td>
                                    {blockEditable ? (
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
                                    {blockEditable ? (
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
                                    {blockEditable ? (
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
                                        onFocus={(e) => e.target.select()}
                                      />
                                    ) : (
                                      eventRow.participant_count ?? 0
                                    )}
                                  </td>
                                ) : null}
                                {blockEditable ? (
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
                            <td colSpan={Number(editableEventColumns?.showDate) + Number(editableEventColumns?.showTag) + Number(editableEventColumns?.showTitle) + Number(editableEventColumns?.showDescription) + Number(editableEventColumns?.showParticipantCount) + Number(blockEditable)}>
                              <span className="muted">Keine passenden Termine.</span>
                            </td>
                          </tr>
                        ) : null}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {elementType === "attendance" && (() => {
                const attendanceEntries = Array.isArray(blockConfig.attendance_entries) ? (blockConfig.attendance_entries as Array<Record<string, any>>) : [];
                const fineAccountId = Number(blockConfig.fine_account_id ?? 0);
                const fineAmountLate = Number(blockConfig.fine_amount_late ?? 0);
                const fineAmountAbsent = Number(blockConfig.fine_amount_absent ?? 0);
                const hasFineConfig = fineAccountId > 0 && (fineAmountLate > 0 || fineAmountAbsent > 0);

                async function handleAttendanceChange(participant: ParticipantSummary, newStatus: string) {
                  const nextEntries = attendanceEntries.filter((entry) => Number(entry.participant_id) !== participant.id);
                  nextEntries.push({ participant_id: participant.id, participant_name: participant.display_name, status: newStatus });
                  await saveBlockConfiguration(block.id, { ...blockConfig, attendance_entries: nextEntries });

                  if (!hasFineConfig) return;

                  const existingFine = protocolFines.find(
                    (f) => f.participant_id === participant.id && (f.fine_type === "late" || f.fine_type === "absent") && f.status === "pending"
                  );

                  if (newStatus === "late" && fineAmountLate > 0) {
                    if (!existingFine || existingFine.fine_type !== "late") {
                      if (existingFine) {
                        await browserApiFetch(`/api/fines/${existingFine.id}`, { method: "DELETE" });
                        setProtocolFines((prev) => prev.filter((f) => f.id !== existingFine.id));
                      }
                      const created = await browserApiFetch<AttendanceFine>("/api/fines", {
                        method: "POST",
                        body: JSON.stringify({ protocol_id: protocol.id, participant_id: participant.id, participant_name_snapshot: participant.display_name, fine_type: "late", amount: fineAmountLate, account_id: fineAccountId }),
                      });
                      if (created) setProtocolFines((prev) => [...prev.filter((f) => !(f.participant_id === participant.id && f.status === "pending")), created]);
                    }
                  } else if (newStatus === "absent" && fineAmountAbsent > 0) {
                    if (!existingFine || existingFine.fine_type !== "absent") {
                      if (existingFine) {
                        await browserApiFetch(`/api/fines/${existingFine.id}`, { method: "DELETE" });
                        setProtocolFines((prev) => prev.filter((f) => f.id !== existingFine.id));
                      }
                      const created = await browserApiFetch<AttendanceFine>("/api/fines", {
                        method: "POST",
                        body: JSON.stringify({ protocol_id: protocol.id, participant_id: participant.id, participant_name_snapshot: participant.display_name, fine_type: "absent", amount: fineAmountAbsent, account_id: fineAccountId }),
                      });
                      if (created) setProtocolFines((prev) => [...prev.filter((f) => !(f.participant_id === participant.id && f.status === "pending")), created]);
                    }
                  } else {
                    if (existingFine) {
                      await browserApiFetch(`/api/fines/${existingFine.id}`, { method: "DELETE" });
                      setProtocolFines((prev) => prev.filter((f) => f.id !== existingFine.id));
                    }
                  }
                }

                const countByStatus = (s: string) => eligibleAttendanceParticipants.filter((p) => {
                  const e = attendanceEntries.find(e => Number(e.participant_id) === p.id);
                  return (e?.status ?? null) === s;
                }).length;
                const nPresent = countByStatus("present");
                const nLate = countByStatus("late");
                const nExcused = countByStatus("excused");
                const nAbsent = countByStatus("absent");
                return (
                  <>
                    <div className="attendance-list">
                      {eligibleAttendanceParticipants.map((participant) => {
                        const currentEntry = attendanceEntries.find((entry) => Number(entry.participant_id) === participant.id);
                        const selectedStatus = currentEntry?.status ?? null;
                        const pendingFine = hasFineConfig ? protocolFines.find((f) => f.participant_id === participant.id && f.status === "pending") : null;
                        return (
                          <div className="attendance-row" key={`${block.id}-${participant.id}`}>
                            <span className="attendance-name">
                              {participant.display_name}
                              {pendingFine ? <span className="fine-badge" title={`Busse: ${pendingFine.amount} (${pendingFine.fine_type === "late" ? "Verspätet" : "Unentschuldigt"})`}> 💰</span> : null}
                            </span>
                            <div className="segment-control attendance-segment-control">
                              {ATTENDANCE_OPTIONS.map((option) => (
                                <button
                                  key={option.value}
                                  type="button"
                                  className={`segment-button attendance-segment-button${selectedStatus === option.value ? " segment-button-active" : ""}`}
                                  disabled={!blockEditable}
                                  onClick={() => blockEditable && void handleAttendanceChange(participant, option.value)}
                                >
                                  {option.label}
                                </button>
                              ))}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                    <div className="attendance-summary">
                      <span>{nPresent} Anwesend</span>
                      <span>·</span>
                      <span>{nLate} Verspätet</span>
                      <span>·</span>
                      <span>{nExcused} Entschuldigt</span>
                      <span>·</span>
                      <span>{nAbsent} Unentschuldigt</span>
                    </div>
                  </>
                );
              })()}

              {elementType === "session_date" && (
                <div className="two-col">
                  <label className="field-stack">
                    <span className="field-label">Nächste Sitzung</span>
                    <DateInput
                      value={String(blockConfig.selected_date ?? "")}
                      readOnly={!blockEditable}
                      onChange={(value) => { if (blockEditable) patchBlockConfigValue(block.id, "selected_date", value || null, blockConfig); }}
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

              {(elementType === "finance_balance" || elementType === "finance_transactions") && (() => {
                const accountId = Number(blockConfig.finance_account_id ?? 0);
                const account = availableAccounts.find((a) => a.id === accountId) ?? null;
                const txAll = accountId > 0 ? (financeTransactions[accountId] ?? []) : [];

                if (!account) {
                  return (
                    <div className="finance-block-empty">
                      <span className="muted">Kein Konto ausgewählt. Konfiguriere diesen Block im Template.</span>
                    </div>
                  );
                }

                if (elementType === "finance_balance") {
                  return (
                    <div className="finance-balance-block">
                      <div className={`finance-balance-amount${account.balance < 0 ? " finance-balance-negative" : ""}`}>
                        {formatFinanceAmount(account.balance, account.currency_label)}
                      </div>
                      <div className="finance-balance-label">{account.name}</div>
                    </div>
                  );
                }

                // finance_transactions
                const filterType = String(blockConfig.finance_filter_type ?? "all");
                const lastN = Number(blockConfig.finance_last_n ?? 10);
                const sinceDate = String(blockConfig.finance_since_date ?? protocol.protocol_date ?? "");
                const thisYear = new Date().getFullYear();

                const filtered = txAll.filter((tx) => {
                  if (filterType === "since_last_session") return !sinceDate || tx.transaction_date >= sinceDate;
                  if (filterType === "this_year") return new Date(tx.transaction_date).getFullYear() === thisYear;
                  return true;
                }).slice(0, filterType === "last_n" ? lastN : undefined);

                if (filtered.length === 0) {
                  return <p className="muted">Keine Transaktionen für den gewählten Zeitraum.</p>;
                }

                let running = 0;
                const withBalance = [...filtered].reverse().map((tx) => { running += tx.amount; return { tx, running }; }).reverse();

                return (
                  <div className="finance-proto-table">
                    <div className="finance-proto-header">
                      <span>Datum</span>
                      <span>Beschreibung</span>
                      <span className="finance-tx-cell-right">Betrag</span>
                      <span className="finance-tx-cell-right">Saldo</span>
                    </div>
                    {withBalance.map(({ tx, running: r }) => (
                      <div key={tx.id} className="finance-proto-row">
                        <span>{formatDate(tx.transaction_date)}</span>
                        <span>{tx.description}</span>
                        <span className={`finance-tx-cell-right${tx.amount < 0 ? " finance-amount-neg" : " finance-amount-pos"}`}>
                          {tx.amount > 0 ? "+" : ""}{formatFinanceAmount(tx.amount, account.currency_label)}
                        </span>
                        <span className={`finance-tx-cell-right${r < 0 ? " finance-balance-negative" : ""}`}>
                          {formatFinanceAmount(r, account.currency_label)}
                        </span>
                      </div>
                    ))}
                  </div>
                );
              })()}

              {elementType === "fine_list" && (() => {
                const fineAccount = (accountId: number) => availableAccounts.find((a) => a.id === accountId);
                return (
                  <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                    {/* Pending fines from earlier protocols */}
                    {pendingFines.length > 0 && (
                      <div className="fine-list-block fine-list-block-pending">
                        <div className="fine-pending-section-header">Offene Bussen aus früheren Protokollen</div>
                        {pendingFines.map((fine) => {
                          const account = fineAccount(fine.account_id);
                          const cur = account?.currency_label ?? fine.currency_label ?? "";
                          const isCollected = fine.status === "collected";
                          const isDeleted = fine.status === "deleted";
                          const isDone = isCollected || isDeleted;
                          return (
                            <div key={fine.id} id={`fine-row-${fine.id}`} className={`fine-list-row${isDone ? " fine-collected" : ""}`}>
                              <div>
                                <span className="fine-participant">{fine.participant_name_snapshot}</span>
                                <span className="fine-pending-origin" style={{ display: "block" }}>
                                  {fine.protocol_number ? `Protokoll ${fine.protocol_number}` : ""}
                                  {fine.protocol_date ? ` · ${formatShortDate(fine.protocol_date)}` : ""}
                                </span>
                              </div>
                              <span className="fine-type-label">{fine.fine_type === "late" ? "Verspätet" : "Unentschuldigt"}</span>
                              <span className="fine-amount">{fine.amount.toFixed(2)} {cur}</span>
                              <span className="fine-status">
                                {isCollected && <span className="todo-pending-resolved">Kassiert</span>}
                                {isDeleted && (
                                  <span className="fine-deleted-badge">
                                    Gelöscht
                                    {fine.delete_comment && <span className="fine-delete-comment"> · {fine.delete_comment}</span>}
                                  </span>
                                )}
                              </span>
                              {isDeleted && !isReadOnly ? (
                                <button
                                  type="button"
                                  className={`fine-action-btn fine-comment-btn${!fine.delete_comment ? " fine-comment-missing" : ""}`}
                                  title={fine.delete_comment ? "Kommentar bearbeiten" : "Kommentar fehlt – hinzufügen"}
                                  onClick={() => setDeleteFineModal({ fineId: fine.id, fromPending: true, comment: fine.delete_comment ?? "" })}
                                >✎</button>
                              ) : !isDone && !isReadOnly ? (
                                <button
                                  type="button"
                                  className="fine-action-btn fine-collect-btn"
                                  title="Busse kassieren"
                                  onClick={async () => {
                                    const updated = await browserApiFetch<AttendanceFine>(
                                      `/api/fines/${fine.id}/collect`,
                                      { method: "POST", body: JSON.stringify({ collecting_protocol_id: protocol.id }) }
                                    );
                                    if (updated) setPendingFines((prev) => prev.map((f) => f.id === updated.id ? { ...f, ...updated } : f));
                                  }}
                                >✓</button>
                              ) : <span />}
                              {!isDone && !isReadOnly ? (
                                <button
                                  type="button"
                                  className="fine-action-btn fine-delete-btn"
                                  title="Busse löschen"
                                  onClick={() => setDeleteFineModal({ fineId: fine.id, fromPending: true, comment: "" })}
                                >✕</button>
                              ) : <span />}
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {/* Own fines (created in this protocol) */}
                    {protocolFines.length === 0 && pendingFines.length === 0 && (
                      <p className="muted">Keine Bussen für dieses Protokoll.</p>
                    )}
                    {protocolFines.length > 0 && <div className="fine-list-block">
                    {protocolFines.map((fine) => {
                      const account = fineAccount(fine.account_id);
                      const cur = account?.currency_label ?? "";
                      const isCollected = fine.status === "collected";
                      const isDeleted = fine.status === "deleted";
                      const isCollectedElsewhere = isCollected && !!fine.closed_in_protocol_id;
                      return (
                        <div key={fine.id} id={`fine-row-${fine.id}`} className={`fine-list-row${isCollected || isDeleted ? " fine-collected" : ""}`}>
                          <span className="fine-participant">{fine.participant_name_snapshot}</span>
                          <span className="fine-type-label">{fine.fine_type === "late" ? "Verspätet" : "Unentschuldigt"}</span>
                          <span className="fine-amount">{fine.amount.toFixed(2)} {cur}</span>
                          <span className="fine-status">
                            {isDeleted ? (
                              <span className="fine-deleted-badge">
                                Gelöscht
                                {fine.delete_comment && <span className="fine-delete-comment"> · {fine.delete_comment}</span>}
                              </span>
                            ) : isCollectedElsewhere ? (
                              <span className="todo-closed-elsewhere-badge">Später beglichen</span>
                            ) : isCollected ? "✓ Kassiert" : "Ausstehend"}
                          </span>
                          {isDeleted && !isReadOnly ? (
                            <button
                              type="button"
                              className={`fine-action-btn fine-comment-btn${!fine.delete_comment ? " fine-comment-missing" : ""}`}
                              title={fine.delete_comment ? "Kommentar bearbeiten" : "Kommentar fehlt – hinzufügen"}
                              onClick={() => setDeleteFineModal({ fineId: fine.id, fromPending: false, comment: fine.delete_comment ?? "" })}
                            >✎</button>
                          ) : !isCollected && !isDeleted && !isReadOnly ? (
                            <button
                              type="button"
                              className="fine-action-btn fine-collect-btn"
                              title="Busse kassieren"
                              onClick={async () => {
                                const updated = await browserApiFetch<AttendanceFine>(`/api/fines/${fine.id}/collect`, { method: "POST" });
                                if (updated) setProtocolFines((prev) => prev.map((f) => f.id === updated.id ? updated : f));
                              }}
                            >✓</button>
                          ) : <span />}
                          {!isCollected && !isDeleted && !isReadOnly ? (
                            <button
                              type="button"
                              className="fine-action-btn fine-delete-btn"
                              title="Busse löschen"
                              onClick={() => setDeleteFineModal({ fineId: fine.id, fromPending: false, comment: "" })}
                            >✕</button>
                          ) : <span />}
                        </div>
                      );
                    })}
                    </div>}

                    {/* Delete-fine modal */}
                    {deleteFineModal && (() => {
                      const isEditComment = (() => {
                        const own = protocolFines.find(f => f.id === deleteFineModal.fineId);
                        if (own) return own.status === "deleted";
                        const pending = pendingFines.find(f => f.id === deleteFineModal.fineId);
                        return (pending?.status ?? "") === "deleted";
                      })();
                      const submitDelete = async () => {
                        const comment = deleteFineModal.comment.trim() || null;
                        if (isEditComment) {
                          if (!comment) return;
                          const updated = await browserApiFetch<AttendanceFine>(
                            `/api/fines/${deleteFineModal.fineId}/delete-comment`,
                            { method: "PATCH", body: JSON.stringify({ delete_comment: comment }) }
                          );
                          if (updated) {
                            if (deleteFineModal.fromPending) {
                              setPendingFines((prev) => prev.map((f) => f.id === updated.id ? { ...f, ...updated } : f));
                            } else {
                              setProtocolFines((prev) => prev.map((f) => f.id === updated.id ? updated : f));
                            }
                          }
                        } else {
                          const body: Record<string, unknown> = { delete_comment: comment };
                          if (deleteFineModal.fromPending) body.closing_protocol_id = protocol.id;
                          const updated = await browserApiFetch<AttendanceFine>(
                            `/api/fines/${deleteFineModal.fineId}/delete`,
                            { method: "POST", body: JSON.stringify(body) }
                          );
                          if (updated) {
                            if (deleteFineModal.fromPending) {
                              setPendingFines((prev) => prev.map((f) => f.id === updated.id ? { ...f, ...updated } : f));
                            } else {
                              setProtocolFines((prev) => prev.map((f) => f.id === updated.id ? updated : f));
                            }
                          }
                        }
                        setDeleteFineModal(null);
                      };
                      return (
                        <Modal
                          open
                          title={isEditComment ? "Kommentar bearbeiten" : "Busse löschen"}
                          description={isEditComment ? "Kommentar für die gelöschte Busse." : "Optionaler Kommentar – kann auch später noch ergänzt werden."}
                          onClose={() => setDeleteFineModal(null)}
                        >
                          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                            <input
                              type="text"
                              className="input"
                              placeholder="Grund für Löschung…"
                              autoFocus
                              value={deleteFineModal.comment}
                              onChange={(e) => setDeleteFineModal((m) => m ? { ...m, comment: e.target.value } : m)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") { e.preventDefault(); void submitDelete(); }
                              }}
                            />
                            <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
                              <button type="button" className="button-ghost" onClick={() => setDeleteFineModal(null)}>Abbrechen</button>
                              <button type="button" className={isEditComment ? "button-primary" : "button-danger"} onClick={submitDelete}>
                                {isEditComment ? "Speichern" : "Löschen"}
                              </button>
                            </div>
                          </div>
                        </Modal>
                      );
                    })()}
                  </div>
                );
              })()}

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
        {isPrepareMode && (element.blocks.some((b) => asObject(b.configuration_snapshot_json).repeat_source_type === "event") || (element.show_when_empty && element.blocks.length === 0)) && (
          <div className="add-event-block-row">
            <button
              type="button"
              className="button-inline"
              onClick={() => { setEventPickerSearch(""); setShowEventPicker(true); }}
            >
              + Termin hinzufügen
            </button>
          </div>
        )}
      </div>
    </section>
    <SessionTodosSection
      sectionTag={trimSectionName(element.section_name_snapshot)}
      todos={Object.values(todosByBlock).flat().filter((t) => (t.tags ?? []).includes(trimSectionName(element.section_name_snapshot).toLowerCase()))}
      pendingTodos={pendingTodos.filter((t) => (t.tags ?? []).includes(trimSectionName(element.section_name_snapshot).toLowerCase()))}
      isReadOnly={isReadOnly}
      participants={availableParticipants}
      dueEvents={[...availableEvents].sort((a, b) => a.event_date.localeCompare(b.event_date))}
      protocol={protocol}
      onUpdate={updateTodo}
      onPendingUpdate={onPendingUpdate}
      onPendingDone={onPendingDone}
      onQuickTodoCreated={onQuickTodoCreated}
    />
    <Modal
      open={showEventPicker}
      onClose={() => setShowEventPicker(false)}
      title="Termin hinzufügen"
      description="Wähle einen Termin, der als Block hinzugefügt werden soll."
    >
      {(() => {
        const existingEventIds = new Set(
          element.blocks
            .map((b) => asObject(b.configuration_snapshot_json).repeat_source_id)
            .filter((id) => id != null)
            .map(Number)
        );
        const query = eventPickerSearch.trim().toLowerCase();
        const filteredEvents = availableEvents.filter((e) => {
          if (existingEventIds.has(e.id)) return false;
          if (!query) return true;
          return (e.title ?? "").toLowerCase().includes(query) || (e.tag ?? "").toLowerCase().includes(query);
        }).sort((a, b) => a.event_date.localeCompare(b.event_date));
        return (
          <div className="grid">
            <label className="field-stack">
              <span className="field-label">Suche</span>
              <input
                value={eventPickerSearch}
                onChange={(e) => setEventPickerSearch(e.target.value)}
                placeholder="Termin suchen…"
                autoFocus
              />
            </label>
            <div className="selection-list">
              {filteredEvents.length === 0 && (
                <p className="muted">Keine Termine gefunden.</p>
              )}
              {filteredEvents.map((evt) => (
                <button
                  key={evt.id}
                  type="button"
                  className="selection-card"
                  disabled={addingEventBlock}
                  onClick={async () => {
                    setAddingEventBlock(true);
                    await addEventBlockToElement(element.id, evt.id);
                    setAddingEventBlock(false);
                    setShowEventPicker(false);
                  }}
                >
                  <div>
                    <strong>{evt.title ?? `Termin ${evt.id}`}</strong>
                    <div className="muted">{formatDate(evt.event_date)}{evt.tag ? ` · ${evt.tag}` : ""}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        );
      })()}
    </Modal>
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
            autoFocus
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

type DueDraft =
  | { type: "none" }
  | { type: "date"; date: string }
  | { type: "next_session" }
  | { type: "event"; eventId: number; eventTitle: string };

function SessionTodosSection({
  sectionTag,
  todos,
  pendingTodos = [],
  isReadOnly,
  participants,
  dueEvents,
  protocol,
  onUpdate,
  onPendingUpdate,
  onPendingDone,
  onQuickTodoCreated,
}: {
  sectionTag: string;
  todos: ProtocolTodo[];
  pendingTodos?: TodoListItem[];
  isReadOnly: boolean;
  participants: ParticipantSummary[];
  dueEvents: EventSummary[];
  protocol: ProtocolSummary;
  onUpdate: (blockId: number, todoId: number, patch: Partial<ProtocolTodo>) => Promise<void>;
  onPendingUpdate: (updated: Partial<TodoListItem> & { id: number }) => void;
  onPendingDone: (todoId: number) => void;
  onQuickTodoCreated: (blockId: number, todoId: number, elementId: number) => void | Promise<void>;
}) {
  const [newTask, setNewTask] = useState("");
  const [newParticipantId, setNewParticipantId] = useState<number | null>(null);
  const [newDue, setNewDue] = useState<DueDraft>({ type: "none" });
  const [creating, setCreating] = useState(false);

  if (todos.length === 0 && pendingTodos.length === 0) return null;
  if (!sectionTag) return null;

  function sessionDueLabel(todo: ProtocolTodo) {
    if (todo.due_marker === "next_session") return todo.resolved_due_date ? `${formatShortDate(todo.resolved_due_date)} (Nächste Sitzung)` : "Nächste Sitzung";
    if (todo.due_event_id) { const lbl = todo.resolved_due_label ?? "Termin"; return todo.resolved_due_date ? `${formatShortDate(todo.resolved_due_date)} (${lbl})` : lbl; }
    if (todo.due_date) return formatShortDate(todo.due_date);
    return "Kein Enddatum";
  }

  function newDueLabel() {
    if (newDue.type === "none") return "Kein Enddatum";
    if (newDue.type === "next_session") return "Nächste Sitzung";
    if (newDue.type === "date") return newDue.date ? formatShortDate(newDue.date) : "Datum wählen";
    if (newDue.type === "event") return newDue.eventTitle;
    return "Kein Enddatum";
  }

  async function handleCreate() {
    const task = newTask.trim();
    if (!task) return;
    setCreating(true);
    try {
      const result = await browserApiFetch<{ block_id: number; todo_id: number; element_id: number }>(
        `/api/protocols/${protocol.id}/quick-todos`,
        { method: "POST", body: JSON.stringify({ task, tag: sectionTag.toLowerCase() }) }
      );
      const patch: Record<string, unknown> = {};
      if (newParticipantId) patch.assigned_participant_id = newParticipantId;
      if (newDue.type === "date") { patch.due_date = newDue.date; patch.due_event_id = null; patch.due_marker = null; }
      else if (newDue.type === "next_session") { patch.due_date = null; patch.due_event_id = null; patch.due_marker = "next_session"; }
      else if (newDue.type === "event") { patch.due_date = null; patch.due_event_id = newDue.eventId; patch.due_marker = null; }
      if (Object.keys(patch).length > 0) {
        await browserApiFetch(`/api/protocol-todos/${result.todo_id}`, { method: "PATCH", body: JSON.stringify(patch) });
      }
      onQuickTodoCreated(result.block_id, result.todo_id, result.element_id);
      setNewTask("");
      setNewParticipantId(null);
      setNewDue({ type: "none" });
    } finally {
      setCreating(false);
    }
  }

  return (
    <section className="card editor-block-card">
      <div className="editor-panel-header">
        <div>
          <div className="eyebrow">Sitzungs-Todos</div>
          <h3>{sectionTag}</h3>
        </div>
      </div>
      {pendingTodos.length > 0 && (
        <div className="todo-list todo-list-pending">
          <div className="todo-pending-header">Pendenzen aus früheren Protokollen</div>
          {pendingTodos.map((todo) => {
            const isClosedElsewhere = !!todo.closed_in_protocol_id;
            const isDirectlyDone = todo.todo_status_code === "done" || todo.todo_status_code === "cancelled";
            const isResolved = isClosedElsewhere || isDirectlyDone;
            return (
              <article className={`todo-card todo-card-compact todo-card-pending${isResolved ? " todo-card-done" : ""}`} key={todo.id}>
                <button
                  type="button"
                  className={`todo-toggle${isResolved ? " todo-toggle-done" : ""}`}
                  disabled={isReadOnly || isResolved}
                  onClick={async () => {
                    if (isReadOnly || isResolved) return;
                    await browserApiFetch(`/api/protocol-todos/${todo.id}`, {
                      method: "PATCH",
                      body: JSON.stringify({ closed_in_protocol_id: protocol.id }),
                    });
                    onPendingUpdate({ id: todo.id, closed_in_protocol_id: protocol.id });
                  }}
                >
                  {isResolved ? "✓" : "○"}
                </button>
                <div className="todo-main todo-main-compact">
                  <span className={`todo-task-text${isResolved ? " todo-task-done" : ""}`}>{todo.task}</span>
                  <div className="todo-pending-meta">
                    <span className="todo-pending-origin">
                      {todo.protocol_number ? `Protokoll ${todo.protocol_number}` : ""}
                      {todo.protocol_date ? ` · ${formatShortDate(todo.protocol_date)}` : ""}
                    </span>
                    {isResolved && <span className="todo-pending-resolved">Erledigt</span>}
                  </div>
                  {!isReadOnly && !isResolved && (
                    <div className="todo-inline-meta">
                      <TodoAssigneeMenu
                        label={todo.assigned_participant_name ?? "Niemand"}
                        participants={participants}
                        activeId={todo.assigned_participant_id}
                        onChange={async (option) => {
                          await browserApiFetch(`/api/protocol-todos/${todo.id}`, {
                            method: "PATCH",
                            body: JSON.stringify({ assigned_participant_id: option.id }),
                          });
                          onPendingUpdate({ id: todo.id, assigned_participant_id: option.id, assigned_participant_name: option.display_name });
                        }}
                      />
                    </div>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}
      <div className="todo-list">
        {todos.map((todo) => {
          const isDone = todo.todo_status_code === "done";
          const isClosedElsewhere = !!todo.closed_in_protocol_id;
          const isLocked = isClosedElsewhere;
          return (
            <article className={`todo-card todo-card-compact${isDone ? " todo-card-done" : ""}${isLocked ? " todo-card-locked" : ""}`} key={todo.id}>
              <button
                type="button"
                className={`todo-toggle${isDone || isLocked ? " todo-toggle-done" : ""}`}
                disabled={isReadOnly || isLocked}
                onClick={() => {
                  if (!isReadOnly && !isLocked) void onUpdate(todo.protocol_element_block_id, todo.id, {
                    todo_status_id: isDone ? TODO_STATUS.open : TODO_STATUS.done,
                    completed_at: isDone ? null : new Date().toISOString(),
                  });
                }}
              >
                {isDone || isLocked ? "✓" : "○"}
              </button>
              <div className="todo-main todo-main-compact">
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span className="todo-task-text">{todo.task}</span>
                  {isLocked && <span className="todo-closed-elsewhere-badge">Später geschlossen</span>}
                </div>
                {!isReadOnly && !isLocked && (
                  <div className="todo-inline-meta">
                    <TodoAssigneeMenu
                      label={todo.assigned_participant_name ?? "Niemand"}
                      participants={participants}
                      activeId={todo.assigned_participant_id}
                      onChange={(option) => void onUpdate(todo.protocol_element_block_id, todo.id, { assigned_participant_id: option.id })}
                    />
                    <TodoMiniMenu label={sessionDueLabel(todo)} compact align="end">
                      {(closeMenu) => (
                        <>
                          <div className="mini-menu-section">
                            <TodoMenuOption label="Kein Enddatum" active={!todo.due_date && !todo.due_event_id && !todo.due_marker}
                              onClick={() => { void onUpdate(todo.protocol_element_block_id, todo.id, { due_date: null, due_event_id: null, due_marker: null }); closeMenu(); }} />
                            <TodoMenuOption label="Freies Datum" active={!!todo.due_date && !todo.due_event_id && !todo.due_marker}
                              onClick={() => { void onUpdate(todo.protocol_element_block_id, todo.id, { due_date: todo.due_date ?? protocol.protocol_date, due_event_id: null, due_marker: null }); closeMenu(); }} />
                            <TodoMenuOption label="Nächste Sitzung" active={todo.due_marker === "next_session"}
                              onClick={() => { void onUpdate(todo.protocol_element_block_id, todo.id, { due_date: null, due_event_id: null, due_marker: "next_session" }); closeMenu(); }} />
                          </div>
                          {dueEvents.length > 0 && (
                            <div className="mini-menu-section">
                              <div className="mini-menu-section-title">Termine</div>
                              {dueEvents.map((event) => (
                                <TodoMenuOption key={event.id} label={event.title} subtle={formatDateRange(event.event_date, event.event_end_date ?? null)}
                                  active={todo.due_event_id === event.id}
                                  onClick={() => { void onUpdate(todo.protocol_element_block_id, todo.id, { due_date: null, due_event_id: event.id, due_marker: null }); closeMenu(); }} />
                              ))}
                            </div>
                          )}
                        </>
                      )}
                    </TodoMiniMenu>
                    {(todo.due_marker || todo.due_event_id || todo.due_date) && (
                      <div className="todo-due-inline">
                        {todo.due_date && !todo.due_event_id && !todo.due_marker ? (
                          <DateInput value={todo.due_date} readOnly={false}
                            onChange={(value) => void onUpdate(todo.protocol_element_block_id, todo.id, { due_date: value || null, due_event_id: null, due_marker: null })} />
                        ) : (
                          <span className="pill">
                            {formatDate(todo.resolved_due_date ?? todo.due_date) || todo.resolved_due_label || ""}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </article>
          );
        })}
      </div>
      {!isReadOnly && (
        <div className="todo-create todo-create-inline">
          <input
            value={newTask}
            onChange={(e) => setNewTask(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void handleCreate(); }}
            placeholder="Neue Aufgabe…"
          />
          <div className="todo-inline-meta">
            <TodoAssigneeMenu
              label={participants.find((p) => p.id === newParticipantId)?.display_name ?? "Niemand"}
              participants={participants}
              activeId={newParticipantId}
              onChange={(option) => setNewParticipantId(option.id)}
            />
            <TodoMiniMenu label={newDueLabel()} compact align="end">
              {(closeMenu) => (
                <>
                  <div className="mini-menu-section">
                    <TodoMenuOption label="Kein Enddatum" active={newDue.type === "none"}
                      onClick={() => { setNewDue({ type: "none" }); closeMenu(); }} />
                    <TodoMenuOption label="Freies Datum" active={newDue.type === "date"}
                      onClick={() => { setNewDue({ type: "date", date: protocol.protocol_date ?? "" }); closeMenu(); }} />
                    <TodoMenuOption label="Nächste Sitzung" active={newDue.type === "next_session"}
                      onClick={() => { setNewDue({ type: "next_session" }); closeMenu(); }} />
                  </div>
                  {dueEvents.length > 0 && (
                    <div className="mini-menu-section">
                      <div className="mini-menu-section-title">Termine</div>
                      {dueEvents.map((event) => (
                        <TodoMenuOption key={event.id} label={event.title} subtle={formatDateRange(event.event_date, event.event_end_date ?? null)}
                          active={newDue.type === "event" && (newDue as { eventId: number }).eventId === event.id}
                          onClick={() => { setNewDue({ type: "event", eventId: event.id, eventTitle: event.title }); closeMenu(); }} />
                      ))}
                    </div>
                  )}
                </>
              )}
            </TodoMiniMenu>
            {newDue.type === "date" && (
              <DateInput value={(newDue as { date: string }).date} readOnly={false}
                onChange={(value) => setNewDue({ type: "date", date: value ?? "" })} />
            )}
          </div>
          <button type="button" disabled={creating || !newTask.trim()} onClick={() => void handleCreate()}>
            + Todo
          </button>
        </div>
      )}
    </section>
  );
}
