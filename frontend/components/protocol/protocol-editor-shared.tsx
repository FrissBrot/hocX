"use client";

import { Dispatch, Fragment, ReactNode, SetStateAction, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { useToast } from "@/contexts/toast-context";

import { SessionPanel, SessionPanelHandle } from "@/components/protocol/session-panel";
import { TodoAssigneeMenu } from "@/components/todos/todo-assignee-menu";
import { StructuredListTable } from "@/components/lists/structured-list-table";
import { TrackedChangeHideButton } from "@/components/ui/tracked-change-hide-button";
import { DataToolbar } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { RichTextEditor } from "@/components/ui/rich-text-editor";
import { Modal } from "@/components/ui/modal";
import { StructuredListEditModal } from "@/components/protocol/planning/structured-list-edit-modal";
import { EventOverviewModal } from "@/components/protocol/planning/event-overview-modal";
import { CheckboxCandidateModal, CandidateItem } from "@/components/protocol/planning/checkbox-candidate-modal";
import { EventDetailForm } from "@/components/protocol/planning/event-detail-form";
import { PlanningIconTrigger } from "@/components/protocol/planning/planning-icon-trigger";
import { usePopoverPosition, usePopoverDismiss } from "@/components/ui/popover";
import { fetchCycleEvents } from "@/lib/api/cycle-events";
import { TagInput } from "@/components/ui/tag-input";
import { ChartBlock, bumpStatsCharts } from "@/components/protocol/chart-block";
import { CollaborationPresenceBar, LockBadge } from "@/components/protocol/collaboration-presence";
import { useProtocolCollaboration } from "@/lib/hooks/use-protocol-collaboration";
import { useTagConfig, TagConfig } from "@/lib/hooks/use-tag-config";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { formatDate, formatDateRange, formatDateTime } from "@/lib/utils/format";
import { getCycleYear } from "@/lib/utils/cycle";
import {
  AttendanceFine,
  AttendanceFineListItem,
  DocumentTemplate,
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
export const TODO_STATUS = {
  open: 1,
  in_progress: 2,
  done: 3,
  cancelled: 4
} as const;

export function protocolStatusLabel(status: string) {
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

export function resequenceProtocolElements(items: ProtocolElement[]) {
  return items.map((item, index) => ({ ...item, sort_index: (index + 1) * 10 }));
}

/** Strip trailing "(…)" from section names, e.g. "Gliähwurm (Enea, Archie)" → "Gliähwurm" */
export function trimSectionName(name: string): string {
  return name.replace(/\s*\(.*\)$/, "").trim();
}


export function formatShortDate(value: string | null | undefined) {
  return formatDate(value);
}

export function formatFinanceAmount(amount: number, currency: string): string {
  const formatted = Math.abs(amount).toLocaleString("de-CH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${amount < 0 ? "−" : ""}${formatted} ${currency}`;
}

export function compareIsoDate(left: string | null | undefined, right: string | null | undefined) {
  if (!left && !right) return 0;
  if (!left) return -1;
  if (!right) return 1;
  return left.localeCompare(right);
}

export const ATTENDANCE_OPTIONS = [
  { value: "present", label: "Anwesend" },
  { value: "late", label: "Verspaetet" },
  { value: "excused", label: "Entschuldigt" },
  { value: "absent", label: "Unentschuldigt" },
] as const;

export function attendanceParticipants(participants: ParticipantSummary[]) {
  return participants.filter((participant) => !participant.exclude_from_attendance);
}

export type AttendanceTally = { present: number; late: number; excused: number; absent: number };

export function tallyAttendance(
  participants: ParticipantSummary[],
  attendanceEntries: Array<Record<string, any>>
): AttendanceTally {
  const eligible = attendanceParticipants(participants);
  const countByStatus = (status: string) =>
    eligible.filter((participant) => {
      const entry = attendanceEntries.find((candidate) => Number(candidate.participant_id) === participant.id);
      return (entry?.status ?? null) === status;
    }).length;
  return {
    present: countByStatus("present"),
    late: countByStatus("late"),
    excused: countByStatus("excused"),
    absent: countByStatus("absent"),
  };
}

/** Maps a protocol section's dominant block type to an existing app-shell nav icon for the Schnellzugriff sidebar. */
export function sectionIconKey(element: ProtocolElement): import("@/components/ui/nav-icons").NavIconKey {
  const codes = element.blocks.map((block) => block.element_type_code);
  if (codes.includes("attendance")) return "participants";
  if (codes.includes("todo")) return "todos";
  if (codes.includes("fine_list")) return "fines";
  if (codes.includes("finance_balance") || codes.includes("finance_transactions")) return "finances";
  if (codes.includes("chart")) return "statistics";
  if (codes.includes("event_list") || codes.includes("session_date")) return "events";
  if (codes.includes("bullet_list")) return "lists";
  if (codes.includes("matrix")) return "elements";
  return "documents";
}

export const EMBEDDED_BLOCK_OPTIONS = [
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

export const EMBEDDED_FORM_VALUE_OPTIONS = [
  { value: "text", label: "Freier Text" },
  { value: "participant", label: "Ein Teilnehmer" },
  { value: "participants", label: "Mehrere Teilnehmer" },
  { value: "event", label: "Ein Termin" },
] as const;

export type MatrixEmbeddedBlock = {
  element_type_id: number;
  title?: string | null;
  block_kind?: string | null;
  text_content?: string | null;
  configuration_snapshot_json?: Record<string, unknown>;
};

export type ProtocolEventDraft = {
  event_date: string;
  event_end_date: string;
  tag: string;
  title: string;
  description: string;
  participant_count: string;
};

export function createProtocolEventDraft(protocolDate: string | undefined, defaultTag = ""): ProtocolEventDraft {
  return {
    event_date: protocolDate || new Date().toISOString().slice(0, 10),
    event_end_date: "",
    tag: defaultTag,
    title: "",
    description: "",
    participant_count: "0",
  };
}

export function createInlineProtocolEventDraft(protocolDate: string | undefined, defaultTag = "", showTitle = true): ProtocolEventDraft {
  const draft = createProtocolEventDraft(protocolDate, defaultTag);
  if (!showTitle) {
    draft.title = "Neuer Termin";
  }
  return draft;
}

export function canCreateProtocolEventDraft(draft: ProtocolEventDraft) {
  return Boolean(draft.event_date.trim() && draft.title.trim());
}

export function embeddedBlockKindForElementType(elementTypeId: number | string) {
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

export function embeddedBlockTypeLabel(elementTypeId: number | string) {
  return EMBEDDED_BLOCK_OPTIONS.find((option) => option.value === Number(elementTypeId))?.label ?? `Block ${elementTypeId}`;
}

export function nextEmbeddedItemId(items: Array<Record<string, any>>, prefix: string) {
  const maxValue = items.reduce((highest, item) => {
    const match = String(item.id ?? "").match(new RegExp(`^${prefix}-(\\d+)$`));
    const candidate = match ? Number(match[1]) : 0;
    return Math.max(highest, candidate);
  }, 0);
  return `${prefix}-${maxValue + 1}`;
}

export function createEmbeddedFormRow(id = "form-row-1") {
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

export function createMatrixEmbeddedBlock(
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

export function asObject(value: unknown): Record<string, any> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, any>) : {};
}

export function readMatrixEmbeddedBlock(cell: Record<string, any>): MatrixEmbeddedBlock | null {
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

export function embeddedBlockSummary(
  embeddedBlock: MatrixEmbeddedBlock,
  availableParticipants: ParticipantSummary[],
  availableEvents: EventSummary[],
  protocol: ProtocolSummary,
  matrixColumn?: Record<string, any>,
  availableTemplates?: import("@/types/api").TemplateSummary[]
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
    const summaryTemplate = availableTemplates?.find((t) => t.id === protocol.template_id);
    const summaryCycleYear = protocol.protocol_date && summaryTemplate?.cycle_config
      ? getCycleYear(protocol.protocol_date, summaryTemplate.cycle_config.reset_month, summaryTemplate.cycle_config.reset_day)
      : null;
    const matchingEvents = availableEvents.filter((event) => {
      const effectiveEndDate = event.event_end_date || event.event_date;
      const matchesDate = !protocol.protocol_date ? true : config.event_only_before_protocol_date === true ? effectiveEndDate < protocol.protocol_date : config.event_only_from_protocol_date === false ? true : effectiveEndDate >= protocol.protocol_date;
      const eventTag = (event.tag ?? "").toLowerCase();
      const matchesTag = (!tagFilters.length || tagFilters.some((t) => eventTag.includes(t))) &&
        (!columnTagFilters.length || columnTagFilters.some((t) => eventTag.includes(t)));
      const matchesCycle = config.event_only_current_cycle !== true || summaryCycleYear === null
        ? true
        : (event.cycle_assignments ?? []).some(
            (a) => a.cycle_config_id === summaryTemplate?.cycle_config_id && a.cycle_year === summaryCycleYear
          );
      return matchesDate && matchesTag && matchesCycle;
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

export function visibleBlockTitle(block: {
  block_title_snapshot?: string | null;
  display_title_snapshot?: string | null;
  title_snapshot?: string | null;
}) {
  const blockTitle = String(block.block_title_snapshot ?? "").trim();
  const displayTitle = String(block.display_title_snapshot ?? "").trim();
  const title = String(block.title_snapshot ?? "").trim();
  return blockTitle || displayTitle || title || null;
}

export function TodoMiniMenu({
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
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const popoverStyle = usePopoverPosition(open, triggerRef, align, 6, { minWidth: 220 });
  usePopoverDismiss(open, () => setOpen(false), [triggerRef, panelRef]);

  const popover = open && typeof document !== "undefined" ? createPortal(
    <div ref={panelRef} id="due-date-portal" className="mini-menu-popover-portal" style={popoverStyle} role="menu">
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

// Shared "track changes" rendering for a todo's task text - used identically by both
// session-todos-section.tsx and focused-element-editor.tsx, which otherwise duplicate
// their todo-card markup independently. Word-style: a single red accent, underline for
// added/new content, strikethrough for removed/old content. A pending-delete todo (a
// pre-existing todo deleted while tracked - it isn't really gone yet, see
// ProtocolTodoService.delete_todo) always renders fully struck through regardless of
// whether it also has a "changed" mark from an earlier edit. onAccept, if given, renders
// a hover-revealed "Ausblenden" icon that accepts this one todo's change.
export function TrackedTaskText({ todo, trackChangesActive, onAccept }: { todo: ProtocolTodo; trackChangesActive: boolean; onAccept?: () => void }) {
  if (!trackChangesActive) return <>{todo.task}</>;
  const hideButton = onAccept ? <TrackedChangeHideButton onAccept={onAccept} title="Änderung an diesem Todo ausblenden" /> : null;
  if (todo.pending_delete) {
    return (
      <span className="tracked-run">
        <span className="tracked-strike">{todo.task}</span>
        {hideButton}
      </span>
    );
  }
  if (todo.tracked_change === "changed" && todo.tracked_change_before_json?.task) {
    return (
      <span className="tracked-run">
        <span className="tracked-strike">{todo.tracked_change_before_json.task}</span>{" "}
        <span className="tracked-underline">{todo.task}</span>
        {hideButton}
      </span>
    );
  }
  if (todo.tracked_change === "added") {
    return (
      <span className="tracked-run">
        <span className="tracked-underline">{todo.task}</span>
        {hideButton}
      </span>
    );
  }
  return <>{todo.task}</>;
}

export function TodoMenuOption({
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
