"use client";

import { Dispatch, SetStateAction, useEffect, useMemo, useRef, useState } from "react";

import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { Badge } from "@/components/ui/badge";
import { TodoAssigneeMenu } from "@/components/todos/todo-assignee-menu";
import { StructuredListTable, TrackedEntryInfo } from "@/components/lists/structured-list-table";
import { DateInput } from "@/components/ui/date-input";
import { RichTextEditor } from "@/components/ui/rich-text-editor";
import { TrackedChangeHideButton } from "@/components/ui/tracked-change-hide-button";
import { Modal } from "@/components/ui/modal";
import { LightboxImage } from "@/components/ui/lightbox-image";
import { StructuredListEditModal } from "@/components/protocol/planning/structured-list-edit-modal";
import { EventOverviewModal } from "@/components/protocol/planning/event-overview-modal";
import { CheckboxCandidateModal, CandidateItem } from "@/components/protocol/planning/checkbox-candidate-modal";
import { EventDetailForm } from "@/components/protocol/planning/event-detail-form";
import { PlanningIconTrigger } from "@/components/protocol/planning/planning-icon-trigger";
import { TrackedWordDiff } from "@/components/protocol/tracked-word-diff";
import { fetchCycleEvents } from "@/lib/api/cycle-events";
import { TagInput } from "@/components/ui/tag-input";
import { bumpStatsCharts } from "@/components/protocol/chart-block";
import { LockBadge } from "@/components/protocol/collaboration-presence";
import { useProtocolCollaboration } from "@/lib/hooks/use-protocol-collaboration";
import { TagConfig } from "@/lib/hooks/use-tag-config";
import { browserApiFetch } from "@/lib/api/client";
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
  RowListSnapshot,
  StructuredListDefinition,
  StructuredListEntry,
  TemplateSummary,
  TodoListItem,
  WholeListSnapshot,
} from "@/types/api";
import {
  ATTENDANCE_OPTIONS,
  MatrixEmbeddedBlock,
  ProtocolEventDraft,
  TODO_STATUS,
  TodoMenuOption,
  TodoMiniMenu,
  asObject,
  attendanceParticipants,
  tallyAttendance,
  canCreateProtocolEventDraft,
  compareIsoDate,
  createInlineProtocolEventDraft,
  createMatrixEmbeddedBlock,
  createProtocolEventDraft,
  embeddedBlockSummary,
  formatFinanceAmount,
  formatShortDate,
  readMatrixEmbeddedBlock,
  trimSectionName,
  visibleBlockTitle,
} from "@/components/protocol/protocol-editor-shared";
import { MatrixEmbeddedBlockEditor } from "@/components/protocol/matrix-embedded-block-editor";
import { ChartBlockRenderer } from "@/components/protocol/chart-block-renderer";
import { SessionTodosSection } from "@/components/protocol/session-todos-section";

export function FocusedElementEditor({
  collab,
  trackChangesActive,
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
  acceptTodoTrackedChange,
  acceptTrackedListEntry,
  acceptTrackedRow,
  acceptTextTrackedChanges,
  createEventFromBlock,
  updateEventFromBlock,
  deleteEventFromBlock,
  onEventContextMenu,
  uploadImage,
  deleteImage,
  listDefinitionsById,
  listEntriesByDefinition,
  createListEntryFromBlock,
  updateListEntryFromBlock,
  deleteListEntryFromBlock,
  refreshBlockListSnapshot,
  undoBlockListSnapshot,
  refreshListEntries,
  todoTagFilter,
  setTodoTagFilter,
  newTodoTags,
  setNewTodoTags,
  isPlanningMode,
  unhideEventBlock,
  removeEventBlock,
  addEventBlockToElement,
  onQuickTodoCreated,
  pendingTodos,
  onPendingUpdate,
  onPendingDone,
  documentTemplates,
  isActive = true,
  autoFocusToken = 0,
  tagConfig,
  updateTagColor,
  renameTag,
}: {
  collab: ReturnType<typeof useProtocolCollaboration>;
  trackChangesActive: boolean;
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
  acceptTodoTrackedChange: (protocolElementBlockId: number, todoId: number) => Promise<void>;
  acceptTrackedListEntry: (blockId: number, entryId: number) => Promise<void>;
  acceptTrackedRow: (blockId: number, rowId: string) => Promise<void>;
  acceptTextTrackedChanges: (protocolElementBlockId: number) => Promise<void>;
  createEventFromBlock: (protocolElementBlockId: number, blockConfig: Record<string, any>, draftOverride?: ProtocolEventDraft) => Promise<EventSummary | null>;
  updateEventFromBlock: (protocolElementBlockId: number, eventId: number, patch: Partial<EventSummary>) => Promise<boolean>;
  deleteEventFromBlock: (protocolElementBlockId: number, eventId: number) => Promise<void>;
  onEventContextMenu: (nativeEvent: React.MouseEvent, eventRow: EventSummary, protocolElementBlockId: number) => void;
  uploadImage: (protocolElementBlockId: number) => Promise<void>;
  deleteImage: (protocolElementBlockId: number, imageId: number) => Promise<void>;
  listDefinitionsById: Map<number, StructuredListDefinition>;
  listEntriesByDefinition: Record<number, StructuredListEntry[]>;
  createListEntryFromBlock: (protocolElementBlockId: number, listDefinitionId: number, payload: { sort_index: number; column_one_value: Record<string, unknown>; column_two_value: Record<string, unknown> }) => Promise<boolean>;
  updateListEntryFromBlock: (protocolElementBlockId: number, listDefinitionId: number, entryId: number, payload: Partial<{ sort_index: number; column_one_value: Record<string, unknown>; column_two_value: Record<string, unknown> }>) => Promise<boolean>;
  deleteListEntryFromBlock: (protocolElementBlockId: number, listDefinitionId: number, entryId: number) => Promise<void>;
  refreshBlockListSnapshot: (blockId: number) => Promise<void>;
  undoBlockListSnapshot: (blockId: number) => Promise<void>;
  refreshListEntries: (listDefinitionId: number) => Promise<void>;
  todoTagFilter: Record<number, string | null>;
  setTodoTagFilter: Dispatch<SetStateAction<Record<number, string | null>>>;
  newTodoTags: Record<number, string>;
  setNewTodoTags: Dispatch<SetStateAction<Record<number, string>>>;
  isPlanningMode: boolean;
  unhideEventBlock: (blockId: number) => Promise<void>;
  removeEventBlock: (blockId: number) => Promise<void>;
  addEventBlockToElement: (elementId: number, eventId: number) => Promise<ProtocolElement["blocks"][number] | null>;
  onQuickTodoCreated: (blockId: number, todoId: number, elementId: number) => void | Promise<void>;
  pendingTodos: TodoListItem[];
  onPendingUpdate: (updated: Partial<TodoListItem> & { id: number }) => void;
  onPendingDone: (todoId: number) => void;
  documentTemplates: DocumentTemplate[];
  /** True while this section is the one currently in focus in the scrollable document (see protocol-editor.tsx's scroll-spy); defaults to true for the legacy single-section "abgeschlossen" view, which always renders exactly one instance. */
  isActive?: boolean;
  /** Bumped by the parent only on an explicit "jump to this section" action (sidebar click, keyboard nav, restored scroll position) so autofocus never fires just because several sections mount at once. */
  autoFocusToken?: number;
  tagConfig: TagConfig;
  updateTagColor: (tag: string, color: string) => Promise<void>;
  renameTag: (oldTag: string, newTag: string) => Promise<void>;
}) {
  const confirm = useConfirm();
  const showToast = useToast();
  const sectionRef = useRef<HTMLElement | null>(null);
  const didMountRef = useRef(false);

  useEffect(() => {
    if (!didMountRef.current) {
      didMountRef.current = true;
      return;
    }
    window.setTimeout(() => {
      const firstEditable = sectionRef.current?.querySelector<HTMLElement>(
        '[data-form-input], textarea:not([readonly]), input:not([readonly]):not([type="file"])'
      );
      firstEditable?.focus();
    }, 50);
  }, [autoFocusToken]);

  const bulletSkipBlurRef = useRef(false);
  // Planning-mode ("geplant") popups: which block's edit/overview modal is currently open.
  const [listEditModalBlockId, setListEditModalBlockId] = useState<number | null>(null);
  const [eventOverviewBlockId, setEventOverviewBlockId] = useState<number | null>(null);
  const [matrixPickerBlockId, setMatrixPickerBlockId] = useState<number | null>(null);
  // Planning-mode consolidated checkbox popup for "Termine pro Element".
  const [showEventBlockPicker, setShowEventBlockPicker] = useState(false);
  const [eventBlockScope, setEventBlockScope] = useState<"current" | "all">("current");
  const [eventBlockCandidates, setEventBlockCandidates] = useState<EventSummary[]>([]);
  const [eventBlockCandidatesLoading, setEventBlockCandidatesLoading] = useState(false);
  const [showEventBlockCreateForm, setShowEventBlockCreateForm] = useState(false);
  const [eventBlockNewDraft, setEventBlockNewDraft] = useState<ProtocolEventDraft>(() =>
    createProtocolEventDraft(protocol.protocol_date)
  );
  const [creatingEventBlockNew, setCreatingEventBlockNew] = useState(false);
  const focusedTemplate = availableTemplates.find((t) => t.id === protocol.template_id) ?? null;

  const currentCycleYear: number | null = protocol.protocol_date && focusedTemplate?.cycle_config
    ? getCycleYear(protocol.protocol_date, focusedTemplate.cycle_config.reset_month, focusedTemplate.cycle_config.reset_day)
    : null;
  const [multiParticipantPicker, setMultiParticipantPicker] = useState<{
    kind: "form" | "matrix" | "embedded_form" | "event_field" | "list_entry";
    blockId: number;
    rowId: string;
    rowLabel: string;
    selectedIds: number[];
    columnId?: string;
    embeddedRowId?: string;
    singleSelect?: boolean;
    eventId?: number;
    eventFieldName?: string;
    listDefinitionId?: number;
    listEntryId?: number;
    listColumnKey?: "column_one_value" | "column_two_value";
  } | null>(null);
  const [eventFieldDrafts, setEventFieldDrafts] = useState<Record<string, string>>({});
  const [listEntryDrafts, setListEntryDrafts] = useState<Record<string, string>>({});
  const [multiParticipantSearch, setMultiParticipantSearch] = useState("");
  const multiParticipantSearchRef = useRef<HTMLInputElement | null>(null);
  const pickerTriggerRef = useRef<HTMLElement | null>(null);
  const [eventDrafts, setEventDrafts] = useState<Record<number, Partial<EventSummary>>>({});
  const [openNewEventRows, setOpenNewEventRows] = useState<Record<number, boolean>>({});
  const [creatingNewEventRows, setCreatingNewEventRows] = useState<Record<number, boolean>>({});
  const knownEventTags = useMemo(
    () => Array.from(new Set(availableEvents.map((e) => (e.tag ?? "").trim()).filter(Boolean))).sort(),
    [availableEvents]
  );
  const [eventBlockCandidatesRefreshKey, setEventBlockCandidatesRefreshKey] = useState(0);
  function refreshEventBlockCandidates() {
    setEventBlockCandidatesRefreshKey((k) => k + 1);
  }
  useEffect(() => {
    if (!showEventBlockPicker) return;
    let cancelled = false;
    setEventBlockCandidatesLoading(true);
    fetchCycleEvents(protocol.id, { scope: eventBlockScope, limit: 500 })
      .then((result) => {
        if (!cancelled) setEventBlockCandidates(result.items);
      })
      .catch((error) => {
        if (!cancelled) {
          showToast(error instanceof Error ? error.message : "Termine konnten nicht geladen werden", "error");
        }
      })
      .finally(() => {
        if (!cancelled) setEventBlockCandidatesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [showEventBlockPicker, eventBlockScope, protocol.id, eventBlockCandidatesRefreshKey, showToast]);
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
    pickerTriggerRef.current = document.activeElement as HTMLElement;
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
    pickerTriggerRef.current = document.activeElement as HTMLElement;
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
    pickerTriggerRef.current = document.activeElement as HTMLElement;
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

  function singleParticipantSummary(participantId: number | null | undefined): string {
    if (!participantId) return "Teilnehmer waehlen";
    const p = availableParticipants.find((entry) => entry.id === Number(participantId));
    return p?.display_name ?? "Teilnehmer waehlen";
  }

  function formatListEntryColumnValue(value: Record<string, any> | null | undefined, valueType: string): string {
    if (!value) return "";
    if (valueType === "participant") {
      const id = Number(value.participant_id ?? 0);
      return availableParticipants.find((p) => p.id === id)?.display_name ?? "";
    }
    if (valueType === "participants") {
      const ids = Array.isArray(value.participant_ids) ? value.participant_ids.map(Number) : [];
      return availableParticipants.filter((p) => ids.includes(p.id)).map((p) => p.display_name).join(", ");
    }
    if (valueType === "event") {
      const id = Number(value.event_id ?? 0);
      const eventRow = availableEvents.find((e) => e.id === id);
      return eventRow ? `${formatDateRange(eventRow.event_date, eventRow.event_end_date)} · ${eventRow.title}` : "";
    }
    return String(value.text_value ?? "").trim();
  }

  function selectSingleParticipant(participantId: number) {
    if (!multiParticipantPicker?.singleSelect) return;
    const { blockId, kind, rowId, columnId, listDefinitionId, listEntryId, listColumnKey } = multiParticipantPicker;
    if (kind === "list_entry" && listDefinitionId && listEntryId && listColumnKey) {
      void updateListEntryFromBlock(blockId, listDefinitionId, listEntryId, { [listColumnKey]: { participant_id: participantId } });
      closeParticipantPicker();
      return;
    }
    const currentBlock = element.blocks.find((b) => b.id === blockId);
    if (!currentBlock) return;
    const config = asObject(currentBlock.configuration_snapshot_json);
    if (kind === "form") {
      const nextRows = [...((Array.isArray(config.rows) ? config.rows : []) as Array<Record<string, any>>)];
      const targetIndex = nextRows.findIndex((r) => String(r.id ?? "") === rowId);
      if (targetIndex === -1) return;
      nextRows[targetIndex] = { ...nextRows[targetIndex], participant_id: participantId };
      void saveBlockConfiguration(blockId, { ...config, rows: nextRows });
    } else if (kind === "matrix" && columnId) {
      updateMatrixCell(blockId, config, columnId, rowId, { participant_id: participantId }, true);
    }
    closeParticipantPicker();
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

  function closeParticipantPicker() {
    setMultiParticipantPicker(null);
    setMultiParticipantSearch("");
    setTimeout(() => pickerTriggerRef.current?.focus(), 0);
  }

  function handleFormInputKeyDown(e: React.KeyboardEvent<HTMLElement>) {
    if (e.key === "Tab") {
      const container = (e.currentTarget as HTMLElement).closest("[data-form-block-id]");
      if (!container) return;
      const inputs = Array.from(container.querySelectorAll<HTMLElement>("[data-form-input]"));
      const idx = inputs.indexOf(e.currentTarget);
      if (idx === -1) return;
      const atLast = !e.shiftKey && idx === inputs.length - 1;
      const atFirst = e.shiftKey && idx === 0;
      if (atLast || atFirst) {
        e.preventDefault();
        document.querySelector<HTMLElement>(".editor-fixed-actions [data-editor-primary-action]")?.focus();
      }
    } else if (e.key === "Enter" && (e.currentTarget as HTMLElement).tagName === "SELECT") {
      const el = e.currentTarget as HTMLElement;
      setTimeout(() => { if (document.activeElement !== el) el.focus(); }, 10);
    }
  }

  function applyMultiParticipantSelection(currentBlockId: number, currentConfig: Record<string, unknown>) {
    if (!multiParticipantPicker || multiParticipantPicker.blockId !== currentBlockId) {
      return;
    }
    if (multiParticipantPicker.kind === "event_field" && multiParticipantPicker.eventId && multiParticipantPicker.eventFieldName) {
      void updateEventFromBlock(currentBlockId, multiParticipantPicker.eventId, {
        [multiParticipantPicker.eventFieldName]: multiParticipantPicker.selectedIds,
      } as Partial<EventSummary>);
      closeParticipantPicker();
      return;
    }
    if (multiParticipantPicker.kind === "list_entry" && multiParticipantPicker.listDefinitionId && multiParticipantPicker.listEntryId && multiParticipantPicker.listColumnKey) {
      void updateListEntryFromBlock(currentBlockId, multiParticipantPicker.listDefinitionId, multiParticipantPicker.listEntryId, {
        [multiParticipantPicker.listColumnKey]: { participant_ids: [...multiParticipantPicker.selectedIds] },
      });
      closeParticipantPicker();
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
    closeParticipantPicker();
  }

  function eventRowsForBlock(blockConfig: Record<string, any>) {
    return [...availableEvents]
      .filter((eventRow) => {
        const tagFilters = String(blockConfig.event_tag_filter ?? "").split(",").map((t) => t.trim().toLowerCase()).filter(Boolean);
        const matchesTag = !tagFilters.length || tagFilters.some((t) => (eventRow.tag ?? "").toLowerCase().includes(t));
        const effectiveEndDate = eventRow.event_end_date || eventRow.event_date;
        const matchesDate = !protocol.protocol_date ? true : blockConfig.event_only_before_protocol_date === true ? effectiveEndDate < protocol.protocol_date : blockConfig.event_only_from_protocol_date === false ? true : effectiveEndDate >= protocol.protocol_date;
        const matchesCycle = blockConfig.event_only_current_cycle !== true || currentCycleYear === null
          ? true
          : (eventRow.cycle_assignments ?? []).some(
              (a) => a.cycle_config_id === focusedTemplate?.cycle_config_id && a.cycle_year === currentCycleYear
            );
        return matchesTag && matchesDate && matchesCycle;
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
      showCancelled: blockConfig.event_show_cancelled === true,
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

  // auto_source_field: new schema; source_field_*: old schema
  function matrixSourceFieldForRow(source: string, row: Record<string, any>): string {
    if (row.auto_source_field) return String(row.auto_source_field);
    if (source === "participants") return String(row.source_field_participant ?? "");
    if (source === "events") return String(row.source_field_event ?? "");
    if (source === "list") return String(row.source_field_list ?? "");
    return "";
  }

  function matrixRowCellValue(row: Record<string, any>, textValue: string): Record<string, unknown> {
    const rowType = matrixRowType(row);
    if (!textValue && rowType === "participant") return {};
    if (!textValue && rowType === "event") return {};
    return textValue ? { text_value: textValue } : {};
  }

  function buildMatrixColumnForParticipant(rows: Array<Record<string, any>>, participant: ParticipantSummary) {
    const row_values: Record<string, Record<string, unknown>> = {};
    rows.forEach((row) => {
      const rowId = String(row.id ?? row.sort_index ?? rows.indexOf(row));
      const sourceField = matrixSourceFieldForRow("participants", row);
      const rowType = matrixRowType(row);
      if (sourceField) {
        let text = "";
        if (sourceField === "display_name") text = participant.display_name;
        else if (sourceField === "first_name") text = String(participant.first_name ?? "");
        else if (sourceField === "last_name") text = String(participant.last_name ?? "");
        else if (sourceField === "email") text = String(participant.email ?? "");
        row_values[rowId] = matrixRowCellValue(row, text);
      } else if (rowType === "participant") {
        row_values[rowId] = { participant_id: participant.id };
      } else if (rowType === "participants") {
        row_values[rowId] = { participant_ids: [participant.id] };
      }
    });
    return { id: `gen-p-${participant.id}`, title: participant.display_name, row_values };
  }

  function buildMatrixColumnForEvent(rows: Array<Record<string, any>>, event: EventSummary) {
    const row_values: Record<string, Record<string, unknown>> = {};
    rows.forEach((row) => {
      const rowId = String(row.id ?? row.sort_index ?? rows.indexOf(row));
      const sourceField = matrixSourceFieldForRow("events", row);
      const rowType = matrixRowType(row);
      if (sourceField) {
        let text = "";
        if (sourceField === "title") text = event.title;
        else if (sourceField === "event_date") text = formatDate(event.event_date);
        else if (sourceField === "tag") text = String(event.tag ?? "");
        else if (sourceField === "participant_count") text = String(event.participant_count ?? "");
        row_values[rowId] = matrixRowCellValue(row, text);
      } else if (rowType === "event") {
        row_values[rowId] = { event_id: event.id };
      }
    });
    return { id: `gen-e-${event.id}`, title: event.title, row_values };
  }

  function buildMatrixColumnForListEntry(rows: Array<Record<string, any>>, entry: StructuredListEntry) {
    const titleText =
      String(asObject(entry.column_one_value).text_value ?? "").trim() ||
      String(asObject(entry.column_two_value).text_value ?? "").trim() ||
      `Eintrag ${entry.id}`;
    const row_values: Record<string, Record<string, unknown>> = {};
    rows.forEach((row) => {
      const rowId = String(row.id ?? row.sort_index ?? rows.indexOf(row));
      const sourceField = matrixSourceFieldForRow("list", row);
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
        row_values[rowId] = matrixRowCellValue(row, String(colVal.text_value ?? "").trim());
      }
    });
    return { id: `gen-l-${entry.id}`, title: titleText, row_values };
  }

  function matrixAutoSourceInfo(blockConfig: Record<string, any>) {
    const autoSrc = blockConfig.auto_source;
    const source = String(
      (autoSrc && typeof autoSrc === "object" ? autoSrc.type : null) ?? blockConfig.matrix_column_source ?? ""
    );
    const eventTagFilter = String(
      (autoSrc && typeof autoSrc === "object" ? autoSrc.event_tag_filter : null) ??
      blockConfig.matrix_column_source_event_tag ?? ""
    ).trim().toLowerCase();
    const listId = Number(
      (autoSrc && typeof autoSrc === "object" ? autoSrc.list_id : null) ??
      blockConfig.matrix_column_source_list_id ?? 0
    );
    return { source, eventTagFilter, listId };
  }

  function generateMatrixColumns(blockId: number, blockConfig: Record<string, any>) {
    const { source, eventTagFilter, listId } = matrixAutoSourceInfo(blockConfig);
    const rows = matrixRows(blockConfig);

    let nextColumns: Array<Record<string, any>> = [];

    if (source === "participants") {
      nextColumns = availableParticipants.map((participant) => buildMatrixColumnForParticipant(rows, participant));
    } else if (source === "events") {
      const filtered = eventTagFilter
        ? availableEvents.filter((e) => String(e.tag ?? "").toLowerCase() === eventTagFilter)
        : availableEvents;
      nextColumns = filtered.map((event) => buildMatrixColumnForEvent(rows, event));
    } else if (source === "list") {
      const entries = listId ? (listEntriesByDefinition[listId] ?? []) : [];
      nextColumns = entries.map((entry) => buildMatrixColumnForListEntry(rows, entry));
    }

    if (!nextColumns.length) return;
    saveMatrixColumns(blockId, blockConfig, nextColumns);
  }

  // Non-destructive counterpart to generateMatrixColumns for planning mode: toggling a
  // candidate on/off only adds a column or flips its `hidden` flag, never overwrites or
  // drops existing (possibly manually edited) columns like the bulk "Generieren" button does.
  function matrixCandidateItems(blockConfig: Record<string, any>): CandidateItem[] {
    const { source, eventTagFilter, listId } = matrixAutoSourceInfo(blockConfig);
    const columns = matrixColumns(blockConfig);
    const columnById = new Map(columns.map((c) => [String(c.id ?? ""), c]));

    function toItem(id: string, label: string, sublabel?: string): CandidateItem {
      const existing = columnById.get(id);
      return {
        id,
        label,
        sublabel,
        checked: Boolean(existing) && !existing!.hidden,
      };
    }

    if (source === "participants") {
      return availableParticipants.map((p) => toItem(`gen-p-${p.id}`, p.display_name));
    }
    if (source === "events") {
      const filtered = eventTagFilter
        ? availableEvents.filter((e) => String(e.tag ?? "").toLowerCase() === eventTagFilter)
        : availableEvents;
      return filtered
        .sort((a, b) => a.event_date.localeCompare(b.event_date))
        .map((e) => toItem(`gen-e-${e.id}`, e.title, `${formatDate(e.event_date)}${e.tag ? ` · ${e.tag}` : ""}`));
    }
    if (source === "list") {
      const entries = listId ? (listEntriesByDefinition[listId] ?? []) : [];
      return entries.map((entry) => {
        const titleText =
          String((entry.column_one_value as any)?.text_value ?? "").trim() ||
          String((entry.column_two_value as any)?.text_value ?? "").trim() ||
          `Eintrag ${entry.id}`;
        return toItem(`gen-l-${entry.id}`, titleText);
      });
    }
    return [];
  }

  function toggleMatrixColumn(blockId: number, blockConfig: Record<string, any>, candidateId: string, nextChecked: boolean) {
    const { source } = matrixAutoSourceInfo(blockConfig);
    const columns = matrixColumns(blockConfig);
    const existing = columns.find((c) => String(c.id ?? "") === candidateId);

    if (existing) {
      saveMatrixColumns(
        blockId,
        blockConfig,
        columns.map((c) => (String(c.id ?? "") === candidateId ? { ...c, hidden: !nextChecked } : c))
      );
      return;
    }
    if (!nextChecked) return; // nothing to hide, no existing column
    const rows = matrixRows(blockConfig);
    let newColumn: Record<string, any> | null = null;
    if (source === "participants") {
      const participant = availableParticipants.find((p) => `gen-p-${p.id}` === candidateId);
      if (participant) newColumn = buildMatrixColumnForParticipant(rows, participant);
    } else if (source === "events") {
      const event = availableEvents.find((e) => `gen-e-${e.id}` === candidateId);
      if (event) newColumn = buildMatrixColumnForEvent(rows, event);
    } else if (source === "list") {
      const { listId } = matrixAutoSourceInfo(blockConfig);
      const entries = listId ? (listEntriesByDefinition[listId] ?? []) : [];
      const entry = entries.find((e) => `gen-l-${e.id}` === candidateId);
      if (entry) newColumn = buildMatrixColumnForListEntry(rows, entry);
    }
    if (!newColumn) return;
    saveMatrixColumns(blockId, blockConfig, [...columns, newColumn]);
  }

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
    <section
      id={`protocol-element-${element.id}`}
      ref={sectionRef}
      className={`protocol-doc-section${isActive ? " protocol-doc-section-active" : " protocol-doc-section-blurred"}`}
      inert={!isActive}
    >
      <div className="editor-panel-header">
        <div>
          <div className="eyebrow">Punkt {elementIndex + 1}</div>
          <h2>{element.section_name_snapshot}</h2>
        </div>
      </div>
      <div className="element-block-stack">
        {element.blocks.length === 0 && element.show_when_empty && (
          isPlanningMode ? (
            <div className="editor-block-empty-placeholder-auto">
              <span>Keine Elemente angezeigt.</span>
              <PlanningIconTrigger
                title="Termine auswählen"
                icon="☑"
                onClick={() => setShowEventBlockPicker(true)}
              />
            </div>
          ) : (
            <div className="element-block-empty-hint">Keine Termine in diesem Zeitraum.</div>
          )
        )}
        {element.blocks.map((block, blockIndex) => {
          const blockTitle = visibleBlockTitle(block);
          const elementType = block.element_type_code ?? "unknown";
          const elementTypeLabel: Record<string, string> = {
            text: "Text", static_text: "Text", display: "Anzeige", form: "Formular",
            todo: "Aufgaben", image: "Bild", bullet_list: "Aufzählung",
            event_list: "Termine", attendance: "Anwesenheit", matrix: "Matrix",
            session_date: "Nächster Hock", finance_balance: "Kontostand",
            finance_transactions: "Transaktionen", fine_list: "Bussenliste",
            chart: "Diagramm",
          };
          const blockConfig = asObject(block.configuration_snapshot_json);
          // Matrix blocks lock per-cell instead (see cellFieldKey below), so the whole-block
          // lock is skipped there to avoid one cell's edit blocking every other cell.
          const blockFieldKey = `block-${block.id}`;
          const blockLockHolder = elementType !== "matrix" ? collab.isLockedByOther(blockFieldKey) : null;
          // Effective editability: forced open in geplant/durchgeführt, locked in abgeschlossen
          const blockEditable = !isReadOnly && !blockLockHolder && (forceEditable || block.is_editable_snapshot);
          // In planning mode ("geplant"), the Terminliste is read-only inline; adding/
          // editing/deleting Termine moves into the Terminübersicht popup.
          const eventListInlineEditable = blockEditable && !isPlanningMode;
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
          const matrixAutoSourceType = elementType === "matrix" ? matrixAutoSourceInfo(blockConfig).source : "";
          // Planning mode ("geplant") replaces the inline column toolbar/"Generieren" for
          // auto-sourced matrices with the checkbox popup; manual matrices and "durchgeführt"
          // keep the existing inline management untouched.
          const matrixPlanningManageable = isPlanningMode && allowMatrixColumnManagement && Boolean(matrixAutoSourceType);
          const matrixInlineColumnManagement = allowMatrixColumnManagement && !matrixPlanningManageable;
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
          const previousBlock = blockIndex > 0 ? element.blocks[blockIndex - 1] : null;
          const isFirstInAutoGroup =
            isPlanningMode &&
            isAutoEventBlock &&
            (!previousBlock || asObject(previousBlock.configuration_snapshot_json).repeat_source_type !== "event");
          return (
            <section
              className={`card editor-block-card${elementType === "event_list" ? " editor-block-card-event-list" : ""}${isHidden ? " editor-block-card-hidden" : ""}${blockLockHolder ? " editor-block-card-locked" : ""}${(isPlanningMode && isAutoEventBlock) || matrixPlanningManageable ? " editor-block-card-auto-generated" : ""}`}
              key={block.id}
              onFocusCapture={elementType === "matrix" ? undefined : () => collab.lockField(blockFieldKey)}
              onBlurCapture={
                elementType === "matrix"
                  ? undefined
                  : (event) => {
                      if (!event.currentTarget.contains(event.relatedTarget as Node)) {
                        collab.unlockField(blockFieldKey);
                      }
                    }
              }
            >
              {isFirstInAutoGroup ? (
                <>
                  <span className="editor-block-auto-generated-label">Wiederholt sich pro Termin</span>
                  <div className="editor-block-auto-generated-icon">
                    <PlanningIconTrigger
                      title="Termine auswählen"
                      icon="☑"
                      onClick={() => setShowEventBlockPicker(true)}
                    />
                  </div>
                </>
              ) : null}
              <div className="editor-panel-header">
                <div>
                  <div className="eyebrow">{elementTypeLabel[elementType] ?? elementType}{isHidden ? " · ausgeblendet" : ""}</div>
                  {blockTitle ? <h3>{blockTitle}</h3> : null}
                  {block.description_snapshot ? <p className="muted">{block.description_snapshot}</p> : null}
                  {blockLockHolder ? <LockBadge holder={blockLockHolder} /> : null}
                </div>
              </div>

              {(elementType === "text" || elementType === "static_text") && (
                <div className="tracked-text-block">
                  <RichTextEditor
                    value={textDrafts[block.id] ?? ""}
                    onChange={(md) => handleTextChange(block.id, md)}
                    readOnly={!blockEditable}
                    placeholder="Text schreiben… Fett mit **text**, kursiv mit *text*, Liste mit - oder 1."
                    trackedBaseline={trackChangesActive && block.tracked_dirty ? block.tracked_baseline_content : undefined}
                  />
                  {trackChangesActive && block.tracked_dirty && block.tracked_baseline_content !== textDrafts[block.id] && (
                    <TrackedChangeHideButton
                      title="Änderungen in diesem Textblock ausblenden"
                      onAccept={() => void acceptTextTrackedChanges(block.id)}
                    />
                  )}
                </div>
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
                      const isPendingDelete = trackChangesActive && !!todo.pending_delete;
                      const todoEditable = blockEditable && !isPendingDelete;
                      const isTrackedAdded = trackChangesActive && todo.tracked_change === "added";
                      const trackedBeforeTask =
                        trackChangesActive && todo.tracked_change === "changed" ? todo.tracked_change_before_json?.task : undefined;
                      return (
                        <article className={`todo-card todo-card-compact${isDone ? " todo-card-done" : ""}${isPendingDelete ? " todo-tracked-pending-delete" : ""}`} key={todo.id}>
                          <button
                            type="button"
                            className={`todo-toggle${isDone ? " todo-toggle-done" : ""}`}
                            disabled={!todoEditable}
                            onClick={() =>
                              todoEditable && void updateTodo(block.id, todo.id, {
                                todo_status_id: isDone ? TODO_STATUS.open : TODO_STATUS.done,
                                completed_at: isDone ? null : new Date().toISOString(),
                              }).then(bumpStatsCharts)
                            }
                            aria-label={isDone ? "Reopen todo" : "Mark todo done"}
                          >
                            {isDone ? "✓" : "○"}
                          </button>
                          <div className="todo-main todo-main-compact">
                            {trackedBeforeTask && (
                              <div className="tracked-strike tracked-before-caption">{trackedBeforeTask}</div>
                            )}
                            <textarea
                              className={`todo-input${isPendingDelete ? " tracked-strike" : isTrackedAdded || trackedBeforeTask ? " tracked-underline" : ""}`}
                              rows={1}
                              value={todo.task}
                              readOnly={!todoEditable}
                              onInput={(event) => autoResizeTodoField(event.currentTarget)}
                              onChange={(event) => {
                                if (!todoEditable) return;
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
                            {(isPendingDelete || isTrackedAdded || trackedBeforeTask) && (
                              <TrackedChangeHideButton
                                title="Änderung an diesem Todo ausblenden"
                                onAccept={() => void acceptTodoTrackedChange(block.id, todo.id)}
                              />
                            )}
                          </div>
                          {todoEditable && (
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
                          {todoEditable && (
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
                              if (bulletSkipBlurRef.current) { bulletSkipBlurRef.current = false; return; }
                              void saveBlockConfiguration(block.id, {
                                ...blockConfig,
                                bullet_items: ((Array.isArray(blockConfig.bullet_items) ? blockConfig.bullet_items : []) ?? []) as string[],
                              });
                            }}
                            onKeyDown={(event) => {
                              if (event.key !== "Enter" || event.shiftKey) return;
                              event.preventDefault();
                              bulletSkipBlurRef.current = true;
                              const items = (Array.isArray(blockConfig.bullet_items) ? blockConfig.bullet_items : []) as string[];
                              if (item === "") {
                                const nextItems = items.filter((_, i) => i !== index);
                                setBlockConfigLocal(block.id, { ...blockConfig, bullet_items: nextItems });
                                void saveBlockConfiguration(block.id, { ...blockConfig, bullet_items: nextItems });
                              } else {
                                const nextItems = [...items.slice(0, index + 1), "", ...items.slice(index + 1)];
                                setBlockConfigLocal(block.id, { ...blockConfig, bullet_items: nextItems });
                                const el = event.currentTarget;
                                window.setTimeout(() => {
                                  const container = el.closest(".todo-list");
                                  const textareas = container?.querySelectorAll<HTMLTextAreaElement>("textarea.todo-input");
                                  textareas?.[index + 1]?.focus();
                                }, 50);
                              }
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
                    // The list may have changed since this block's snapshot was taken (or
                    // there may be no snapshot yet on an old/abgeschlossen protocol) - the
                    // read-only preview and the directly-editable table below both render
                    // from the frozen snapshot when present, falling back to today's live
                    // lookup otherwise. The management modal further down intentionally
                    // keeps reading/writing the live list, since it's a "manage the list
                    // itself" tool, not part of the protocol's frozen record.
                    const wholeListSnapshot = blockConfig.list_snapshot as WholeListSnapshot | undefined;
                    const snapshotDefinition: StructuredListDefinition | null = wholeListSnapshot
                      ? {
                          ...linkedListDefinition,
                          column_one_title: wholeListSnapshot.column_one_title,
                          column_one_value_type: wholeListSnapshot.column_one_value_type,
                          column_two_title: wholeListSnapshot.column_two_title,
                          column_two_value_type: wholeListSnapshot.column_two_value_type,
                        }
                      : null;
                    const snapshotEntries: StructuredListEntry[] | null = wholeListSnapshot
                      ? wholeListSnapshot.entries.map((entry) => ({
                          id: entry.id,
                          list_definition_id: linkedListId,
                          sort_index: entry.sort_index,
                          column_one_value: entry.column_one_value,
                          column_two_value: entry.column_two_value,
                          created_at: "",
                          updated_at: "",
                        }))
                      : null;
                    const displayDefinition = snapshotDefinition ?? linkedListDefinition;
                    const displayEntries = snapshotEntries ?? (listEntriesByDefinition[linkedListId] ?? []);
                    // Diffing already happened server-side at the last sync (see
                    // list_snapshot_service._merge_tracked_list_entries) - this just reads
                    // the '_tracked'/'_tracked_before' markers already embedded per entry.
                    const entryTrackedStatusById: Record<number, TrackedEntryInfo> | undefined = trackChangesActive && wholeListSnapshot
                      ? Object.fromEntries(
                          wholeListSnapshot.entries
                            .filter((entry) => !!entry._tracked)
                            .map((entry) => [entry.id, { status: entry._tracked!, before: entry._tracked_before }])
                        )
                      : undefined;
                    const isListStale = !isReadOnly && !!wholeListSnapshot && linkedListDefinition.content_version > wholeListSnapshot.synced_version;
                    const hasListUndo = !!wholeListSnapshot?.previous;
                    const listSnapshotBanner = (isListStale || hasListUndo) && (
                      <div className="list-snapshot-banner">
                        {isListStale && (
                          <button type="button" className="list-snapshot-refresh-button" onClick={() => void refreshBlockListSnapshot(block.id)}>
                            ⟳ Daten aktualisieren
                          </button>
                        )}
                        {hasListUndo && (
                          <button type="button" className="list-snapshot-undo-button" onClick={() => void undoBlockListSnapshot(block.id)}>
                            Rückgängig
                          </button>
                        )}
                      </div>
                    );
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
                    if (isPlanningMode) {
                      return (
                        <div className="grid">
                          <div className="editor-planning-toolbar">
                            <PlanningIconTrigger title="Liste bearbeiten" onClick={() => { void refreshListEntries(linkedListId).then(() => setListEditModalBlockId(block.id)); }} />
                          </div>
                          {listSnapshotBanner}
                          <StructuredListTable
                            definition={displayDefinition}
                            entries={displayEntries}
                            availableParticipants={availableParticipants}
                            availableEvents={availableEvents}
                            editable={false}
                            emptyMessage="Noch keine Eintraege in dieser Liste."
                            groupByColumn={linkedListGroupBy}
                            sortByColumn={linkedListSortBy}
                            sortDirection={linkedListSortDirection}
                            entryTrackedStatusById={entryTrackedStatusById}
                            onAcceptTrackedEntry={(entryId) => void acceptTrackedListEntry(block.id, entryId)}
                            onCreateEntry={() => Promise.resolve(false)}
                            onUpdateEntry={() => Promise.resolve(false)}
                            onDeleteEntry={() => Promise.resolve()}
                          />
                          <StructuredListEditModal
                            open={listEditModalBlockId === block.id}
                            onClose={() => setListEditModalBlockId(null)}
                            definition={linkedListDefinition}
                            entries={listEntriesByDefinition[linkedListId] ?? []}
                            availableParticipants={availableParticipants}
                            availableEvents={availableEvents}
                            groupByColumn={linkedListGroupBy}
                            sortByColumn={linkedListSortBy}
                            sortDirection={linkedListSortDirection}
                            onChangeGroupBy={(value) => void saveBlockConfiguration(block.id, { ...blockConfig, linked_list_group_by: value || null })}
                            onChangeSortBy={(value) => void saveBlockConfiguration(block.id, { ...blockConfig, linked_list_sort_by: value || null, linked_list_sort_direction: value ? linkedListSortDirection : "asc" })}
                            onChangeSortDirection={(value) => void saveBlockConfiguration(block.id, { ...blockConfig, linked_list_sort_direction: value })}
                            onCreateEntry={(payload) => createListEntryFromBlock(block.id, linkedListId, payload)}
                            onUpdateEntry={(entryId, payload) => updateListEntryFromBlock(block.id, linkedListId, entryId, payload)}
                            onDeleteEntry={(entryId) => deleteListEntryFromBlock(block.id, linkedListId, entryId)}
                          />
                        </div>
                      );
                    }
                    return (
                      <div className="grid">
                        {listSnapshotBanner}
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
                          definition={displayDefinition}
                          entries={displayEntries}
                          availableParticipants={availableParticipants}
                          availableEvents={availableEvents}
                          editable={blockEditable}
                          emptyMessage="Noch keine Eintraege in dieser Liste."
                          groupByColumn={linkedListGroupBy}
                          sortByColumn={linkedListSortBy}
                          sortDirection={linkedListSortDirection}
                          entryTrackedStatusById={entryTrackedStatusById}
                          onAcceptTrackedEntry={(entryId) => void acceptTrackedListEntry(block.id, entryId)}
                          onCreateEntry={(payload) => createListEntryFromBlock(block.id, linkedListId, payload)}
                          onUpdateEntry={(entryId, payload) => updateListEntryFromBlock(block.id, linkedListId, entryId, payload)}
                          onDeleteEntry={(entryId) => deleteListEntryFromBlock(block.id, linkedListId, entryId)}
                        />
                      </div>
                    );
                  }
                  const linkedEvent = isAutoEventBlock
                    ? availableEvents.find((e) => e.id === Number(blockConfig.repeat_source_id))
                    : undefined;
                  const configuredEventFields = isAutoEventBlock && Array.isArray(blockConfig.event_fields)
                    ? (blockConfig.event_fields as Array<{ field: string; label: string }>)
                    : [];
                  return (
                    <div className="grid">
                      {String(blockConfig.left_column_heading ?? "").trim() || String(blockConfig.value_column_heading ?? "").trim() ? (
                        <div className="form-block-row form-block-row-head">
                          <div className="field-label-inline">{String(blockConfig.left_column_heading ?? "").trim()}</div>
                          <div className="field-label-inline">{String(blockConfig.value_column_heading ?? "").trim()}</div>
                          <div />
                        </div>
                      ) : null}
                      {linkedEvent && configuredEventFields.length > 0 && (
                        <div className="form-block-list">
                          {configuredEventFields.map((ef) => {
                            const draftKey = `${block.id}-${ef.field}`;
                            const isParticipantsField = ef.field.endsWith("_ids");
                            const isDateField = ef.field === "event_date" || ef.field === "event_end_date";
                            const isNumberField = ef.field === "participant_count";
                            const currentIds: number[] = isParticipantsField
                              ? ((linkedEvent as unknown as Record<string, unknown>)[ef.field] as number[] | undefined ?? [])
                              : [];
                            const participantSummary = isParticipantsField
                              ? currentIds.length === 0
                                ? "Auswählen…"
                                : availableParticipants
                                    .filter((p) => currentIds.includes(p.id))
                                    .map((p) => p.display_name)
                                    .join(", ") || `${currentIds.length} ausgewählt`
                              : "";
                            return (
                              <div className="form-block-row" key={`${block.id}-ef-${ef.field}`} style={{ borderLeft: "2px solid var(--accent-soft)" }}>
                                <div className="field-label-inline">{ef.label}</div>
                                {isParticipantsField ? (
                                  <button
                                    type="button"
                                    data-form-input
                                    className="button-ghost form-participant-picker-button"
                                    disabled={!blockEditable}
                                    onClick={() => {
                                      pickerTriggerRef.current = document.activeElement as HTMLElement;
                                      setMultiParticipantSearch("");
                                      setMultiParticipantPicker({
                                        kind: "event_field",
                                        blockId: block.id,
                                        rowId: ef.field,
                                        rowLabel: ef.label,
                                        selectedIds: currentIds,
                                        eventId: linkedEvent.id,
                                        eventFieldName: ef.field,
                                      });
                                    }}
                                  >
                                    {participantSummary}
                                  </button>
                                ) : (
                                  <input
                                    data-form-input
                                    type={isDateField ? "date" : isNumberField ? "number" : "text"}
                                    disabled={!blockEditable}
                                    value={eventFieldDrafts[draftKey] ?? String((linkedEvent as unknown as Record<string, unknown>)[ef.field] ?? "")}
                                    onChange={(e) => setEventFieldDrafts((d) => ({ ...d, [draftKey]: e.target.value }))}
                                    onBlur={(e) => {
                                      const val = e.target.value;
                                      setEventFieldDrafts((d) => { const next = { ...d }; delete next[draftKey]; return next; });
                                      void updateEventFromBlock(block.id, linkedEvent.id, {
                                        [ef.field]: isNumberField ? Number(val) : (val || null),
                                      } as Partial<EventSummary>);
                                    }}
                                    style={{ background: "transparent" }}
                                  />
                                )}
                                <div />
                              </div>
                            );
                          })}
                        </div>
                      )}
                      {(() => {
                        // Block-level (not per-row) stale check: this block's "Daten
                        // aktualisieren" refreshes every list_entry row it owns in one call
                        // (see list_snapshot_service.refresh_block_list_snapshot), so one
                        // shared banner for the whole block matches that granularity.
                        const listEntryRows = ((Array.isArray(blockConfig.rows) ? blockConfig.rows : []) as Array<Record<string, any>>)
                          .filter((row) => String(row.value_type ?? row.row_type ?? "text") === "list_entry");
                        const rowsAreStale = !isReadOnly && listEntryRows.some((row) => {
                          const snapshot = row.list_snapshot as RowListSnapshot | undefined;
                          if (!snapshot) return false;
                          const liveDefinition = listDefinitionsById.get(Number(row.linked_list_id ?? 0));
                          return !!liveDefinition && liveDefinition.content_version > snapshot.synced_version;
                        });
                        const rowsHaveUndo = listEntryRows.some((row) => {
                          const snapshot = row.list_snapshot as RowListSnapshot | undefined;
                          return !!snapshot && "previous" in snapshot && !!snapshot.previous;
                        });
                        if (!rowsAreStale && !rowsHaveUndo) return null;
                        return (
                          <div className="list-snapshot-banner">
                            {rowsAreStale && (
                              <button type="button" className="list-snapshot-refresh-button" onClick={() => void refreshBlockListSnapshot(block.id)}>
                                ⟳ Daten aktualisieren
                              </button>
                            )}
                            {rowsHaveUndo && (
                              <button type="button" className="list-snapshot-undo-button" onClick={() => void undoBlockListSnapshot(block.id)}>
                                Rückgängig
                              </button>
                            )}
                          </div>
                        );
                      })()}
                      <div className="form-block-list" data-form-block-id={block.id}>
                        {((Array.isArray(blockConfig.rows) ? blockConfig.rows : []) as Array<Record<string, any>>).map((row, index) => {
                          const rowType = String(row.value_type ?? row.row_type ?? "text");
                          if (rowType === "list_entry") {
                            const linkedListId = Number(row.linked_list_id ?? 0);
                            const linkedListEntryId = Number(row.linked_list_entry_id ?? 0);
                            const rowSnapshot = row.list_snapshot as RowListSnapshot | undefined;
                            const liveListDefinition = listDefinitionsById.get(linkedListId);
                            const liveListEntry = (listEntriesByDefinition[linkedListId] ?? []).find((entry) => entry.id === linkedListEntryId);
                            const entryExists = rowSnapshot ? rowSnapshot.entry_exists : !!liveListDefinition && !!liveListEntry;
                            if (!entryExists) {
                              return (
                                <div className="form-block-row" key={`${block.id}-form-${index}`}>
                                  <div className="field-label-inline muted">Verknüpfter Listeneintrag wurde gelöscht</div>
                                  <div />
                                </div>
                              );
                            }
                            // Column titles/types come from the snapshot (frozen at last
                            // sync) rather than the live definition, so a pending column
                            // structure change doesn't get misinterpreted before refresh -
                            // e.g. a column retyped from text to participant must keep being
                            // read as text here until "Daten aktualisieren" is clicked.
                            const listDefinition: StructuredListDefinition | undefined =
                              rowSnapshot && "column_one_title" in rowSnapshot
                                ? {
                                    ...(liveListDefinition as StructuredListDefinition),
                                    column_one_title: rowSnapshot.column_one_title,
                                    column_one_value_type: rowSnapshot.column_one_value_type,
                                    column_two_title: rowSnapshot.column_two_title,
                                    column_two_value_type: rowSnapshot.column_two_value_type,
                                  }
                                : liveListDefinition;
                            const listEntry =
                              rowSnapshot && rowSnapshot.entry_exists
                                ? {
                                    column_one_value: rowSnapshot.column_one_value,
                                    column_two_value: rowSnapshot.column_two_value,
                                  }
                                : liveListEntry;
                            if (!listDefinition || !listEntry) {
                              return (
                                <div className="form-block-row" key={`${block.id}-form-${index}`}>
                                  <div className="field-label-inline muted">Verknüpfter Listeneintrag wurde gelöscht</div>
                                  <div />
                                </div>
                              );
                            }
                            const fixedColumn: "column_one" | "column_two" = row.list_fixed_column === "column_two" ? "column_two" : "column_one";
                            const variableColumn: "column_one" | "column_two" = fixedColumn === "column_one" ? "column_two" : "column_one";
                            const fixedValueType = fixedColumn === "column_two" ? listDefinition.column_two_value_type : listDefinition.column_one_value_type;
                            const variableValueType = variableColumn === "column_two" ? listDefinition.column_two_value_type : listDefinition.column_one_value_type;
                            const fixedRawValue = (fixedColumn === "column_two" ? listEntry.column_two_value : listEntry.column_one_value) as Record<string, any>;
                            const variableRawValue = (variableColumn === "column_two" ? listEntry.column_two_value : listEntry.column_one_value) as Record<string, any>;
                            const variableColumnKey: "column_one_value" | "column_two_value" = variableColumn === "column_two" ? "column_two_value" : "column_one_value";
                            const aliasOrFixedValue = String(row.label ?? "").trim() || formatListEntryColumnValue(fixedRawValue, fixedValueType);
                            const draftKey = `${block.id}-listentry-${row.id ?? index}`;
                            // A removed row is a phantom reconstructed from its last-known
                            // values (entry_exists stays true on purpose so it keeps
                            // rendering here instead of falling into the "wurde gelöscht"
                            // branch above) - always struck through, never editable.
                            if (trackChangesActive && rowSnapshot?._tracked === "removed") {
                              return (
                                <div className="form-block-row" key={`${block.id}-form-${index}`}>
                                  <div className="field-label-inline tracked-strike">{aliasOrFixedValue}</div>
                                  <div className="tracked-strike">
                                    {formatListEntryColumnValue(variableRawValue, variableValueType)}
                                    <TrackedChangeHideButton
                                      title="Entfernte Zeile ausblenden"
                                      onAccept={() => void acceptTrackedRow(block.id, String(row.id ?? index))}
                                    />
                                  </div>
                                </div>
                              );
                            }
                            const trackedBeforeVariableValue =
                              trackChangesActive && rowSnapshot?._tracked === "changed" ? rowSnapshot._tracked_before?.[variableColumnKey] : undefined;
                            const variableTrackedChanged =
                              !!trackedBeforeVariableValue && JSON.stringify(variableRawValue ?? {}) !== JSON.stringify(trackedBeforeVariableValue ?? {});
                            return (
                              <div className="form-block-row" key={`${block.id}-form-${index}`}>
                                <div className="field-label-inline">{aliasOrFixedValue}</div>
                                <div className={variableTrackedChanged ? "tracked-cell" : undefined}>
                                {variableTrackedChanged && (
                                  <div className="tracked-before-caption">
                                    <TrackedWordDiff
                                      before={formatListEntryColumnValue(trackedBeforeVariableValue as Record<string, any>, variableValueType)}
                                      after={formatListEntryColumnValue(variableRawValue, variableValueType)}
                                    />
                                  </div>
                                )}
                                {variableTrackedChanged && (
                                  <TrackedChangeHideButton onAccept={() => void acceptTrackedRow(block.id, String(row.id ?? index))} />
                                )}
                                {variableValueType === "participant" ? (
                                  <button
                                    type="button"
                                    data-form-input
                                    className="button-ghost form-participant-picker-button"
                                    disabled={!blockEditable}
                                    onKeyDown={handleFormInputKeyDown}
                                    onClick={(e) => {
                                      pickerTriggerRef.current = e.currentTarget;
                                      setMultiParticipantSearch("");
                                      setMultiParticipantPicker({
                                        kind: "list_entry",
                                        blockId: block.id,
                                        rowId: String(row.id ?? index),
                                        rowLabel: aliasOrFixedValue || "Wert",
                                        selectedIds: variableRawValue?.participant_id ? [Number(variableRawValue.participant_id)] : [],
                                        singleSelect: true,
                                        listDefinitionId: linkedListId,
                                        listEntryId: linkedListEntryId,
                                        listColumnKey: variableColumnKey,
                                      });
                                    }}
                                  >
                                    {formatListEntryColumnValue(variableRawValue, "participant") || "Teilnehmer wählen"}
                                  </button>
                                ) : variableValueType === "participants" ? (
                                  <button
                                    type="button"
                                    data-form-input
                                    className="button-ghost form-participant-picker-button"
                                    disabled={!blockEditable}
                                    onKeyDown={handleFormInputKeyDown}
                                    onClick={() => {
                                      pickerTriggerRef.current = document.activeElement as HTMLElement;
                                      setMultiParticipantSearch("");
                                      setMultiParticipantPicker({
                                        kind: "list_entry",
                                        blockId: block.id,
                                        rowId: String(row.id ?? index),
                                        rowLabel: aliasOrFixedValue || "Wert",
                                        selectedIds: Array.isArray(variableRawValue?.participant_ids) ? variableRawValue.participant_ids.map(Number) : [],
                                        listDefinitionId: linkedListId,
                                        listEntryId: linkedListEntryId,
                                        listColumnKey: variableColumnKey,
                                      });
                                    }}
                                  >
                                    {formatListEntryColumnValue(variableRawValue, "participants") || "Teilnehmer wählen"}
                                  </button>
                                ) : variableValueType === "event" ? (
                                  <select
                                    data-form-input
                                    value={variableRawValue?.event_id ?? ""}
                                    disabled={!blockEditable}
                                    onKeyDown={handleFormInputKeyDown}
                                    onChange={(event) => {
                                      void updateListEntryFromBlock(block.id, linkedListId, linkedListEntryId, {
                                        [variableColumnKey]: { event_id: event.target.value ? Number(event.target.value) : null },
                                      });
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
                                    data-form-input
                                    className="todo-input"
                                    disabled={!blockEditable}
                                    value={listEntryDrafts[draftKey] ?? String(variableRawValue?.text_value ?? "")}
                                    onInput={(event) => autoResizeTodoField(event.currentTarget)}
                                    onKeyDown={handleFormInputKeyDown}
                                    onChange={(event) => setListEntryDrafts((current) => ({ ...current, [draftKey]: event.target.value }))}
                                    onBlur={(event) => {
                                      setListEntryDrafts((current) => {
                                        const next = { ...current };
                                        delete next[draftKey];
                                        return next;
                                      });
                                      void updateListEntryFromBlock(block.id, linkedListId, linkedListEntryId, {
                                        [variableColumnKey]: { text_value: event.target.value },
                                      });
                                    }}
                                  />
                                )}
                                </div>
                              </div>
                            );
                          }
                          return (
                          <div className="form-block-row" key={`${block.id}-form-${index}`}>
                            <div className="field-label-inline">{row.label ?? `Feld ${index + 1}`}</div>
                            {rowType === "participant" ? (
                              <button
                                type="button"
                                data-form-input
                                className="button-ghost form-participant-picker-button"
                                onKeyDown={handleFormInputKeyDown}
                                onClick={(e) => {
                                  pickerTriggerRef.current = e.currentTarget;
                                  setMultiParticipantSearch("");
                                  setMultiParticipantPicker({
                                    kind: "form",
                                    blockId: block.id,
                                    rowId: String(row.id ?? index),
                                    rowLabel: String(row.label ?? `Feld ${index + 1}`),
                                    selectedIds: row.participant_id ? [Number(row.participant_id)] : [],
                                    singleSelect: true,
                                  });
                                }}
                              >
                                {singleParticipantSummary(row.participant_id)}
                              </button>
                            ) : rowType === "participants" ? (
                              <button
                                type="button"
                                data-form-input
                                className="button-ghost form-participant-picker-button"
                                onKeyDown={handleFormInputKeyDown}
                                onClick={() => openMultiParticipantPicker(block.id, index, row)}
                              >
                                {multiParticipantSummary(row)}
                              </button>
                            ) : rowType === "event" ? (
                              <select
                                data-form-input
                                value={row.event_id ?? ""}
                                onKeyDown={handleFormInputKeyDown}
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
                                data-form-input
                                className="todo-input"
                                value={row.text_value ?? ""}
                                onInput={(event) => autoResizeTodoField(event.currentTarget)}
                                onKeyDown={handleFormInputKeyDown}
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
                          </div>
                        );})}
                      </div>
                    </div>
                  );
                })()
              )}

              {elementType === "matrix" && (
                <div className="grid">
                  {matrixPlanningManageable ? (
                    <div className="editor-planning-toolbar">
                      <PlanningIconTrigger
                        title="Spalten auswählen"
                        icon="☑"
                        onClick={() => setMatrixPickerBlockId(block.id)}
                      />
                    </div>
                  ) : matrixInlineColumnManagement ? (
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
                    const cols = matrixColumns(blockConfig).filter((c) => !c?.hidden);
                    const rows = matrixRows(blockConfig);
                    if (matrixPlanningManageable && cols.length === 0) {
                      return (
                        <div className="editor-block-empty-placeholder-auto">
                          <span>Keine Elemente angezeigt.</span>
                          <PlanningIconTrigger
                            title="Spalten auswählen"
                            icon="☑"
                            onClick={() => setMatrixPickerBlockId(block.id)}
                          />
                        </div>
                      );
                    }
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
                                ) : matrixInlineColumnManagement ? (
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
                                const cellFieldKey = `block-${block.id}-cell-${rowId}-${columnId ?? columnIndex}`;
                                const cellLockHolder = isPlaceholder ? null : collab.isLockedByOther(cellFieldKey);
                                const cellEditable = !isPlaceholder && blockEditable && !cellLockHolder && (forceEditable || matrixRowEditable(row));
                                const autoEvents = (!isPlaceholder && !embeddedBlock && matrixRowType(row) === "events")
                                  ? matrixEventsForRow(row, column!) : [];
                                return (
                                  <div key={`${rowId}-${columnIndex}`} className="matrix-card-row">
                                    <div className={`matrix-card-row-label${(!forceEditable && !matrixRowEditable(row)) ? " matrix-row-locked" : ""}`}>
                                      {row.label ?? `Zeile ${rowIndex + 1}`}
                                      {(!forceEditable && !matrixRowEditable(row)) ? <span className="matrix-lock-icon"> 🔒</span> : null}
                                      {cellLockHolder ? <LockBadge holder={cellLockHolder} /> : null}
                                    </div>
                                    <div
                                      className="matrix-card-row-cell"
                                      onFocusCapture={isPlaceholder ? undefined : () => collab.lockField(cellFieldKey)}
                                      onBlurCapture={
                                        isPlaceholder
                                          ? undefined
                                          : (event) => {
                                              if (!event.currentTarget.contains(event.relatedTarget as Node)) {
                                                collab.unlockField(cellFieldKey);
                                              }
                                            }
                                      }
                                    >
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
                                            currentCycleYear={currentCycleYear}
                                            cycleConfigId={focusedTemplate?.cycle_config_id ?? null}
                                            onEventContextMenu={(nativeEvent, eventRow) => onEventContextMenu(nativeEvent, eventRow, block.id)}
                                            isPlanningMode={isPlanningMode}
                                            knownEventTags={knownEventTags}
                                            tagConfig={tagConfig}
                                            onTagColorChange={updateTagColor}
                                            onTagRename={renameTag}
                                          />
                                          {cellEditable ? (
                                            <div className="matrix-row-summary muted">
                                              {embeddedBlockSummary(embeddedBlock, availableParticipants, availableEvents, protocol, column!, availableTemplates)}
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
                                            <button
                                              type="button"
                                              className="button-ghost form-participant-picker-button"
                                              onClick={(e) => {
                                                pickerTriggerRef.current = e.currentTarget;
                                                setMultiParticipantSearch("");
                                                setMultiParticipantPicker({
                                                  kind: "matrix",
                                                  blockId: block.id,
                                                  rowId: rowId!,
                                                  rowLabel: String(row.label ?? "Teilnehmer"),
                                                  selectedIds: value.participant_id ? [Number(value.participant_id)] : [],
                                                  columnId: columnId!,
                                                  singleSelect: true,
                                                });
                                              }}
                                            >
                                              {singleParticipantSummary(value.participant_id)}
                                            </button>
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
                  {matrixPlanningManageable && (
                    <CheckboxCandidateModal
                      open={matrixPickerBlockId === block.id}
                      onClose={() => setMatrixPickerBlockId(null)}
                      title="Spalten auswählen"
                      description="Spalten dieser Matrix an-/abwählen. Werte bleiben beim Abwählen erhalten."
                      items={matrixCandidateItems(blockConfig)}
                      onToggle={(item, nextChecked) => toggleMatrixColumn(block.id, blockConfig, item.id, nextChecked)}
                    />
                  )}
                </div>
              )}

              {elementType === "event_list" && (
                <div className="grid event-list-grid">
                  {isPlanningMode && (
                    <div className="editor-planning-toolbar">
                      <PlanningIconTrigger
                        title="Terminübersicht öffnen"
                        icon="🗓"
                        onClick={() => setEventOverviewBlockId(block.id)}
                      />
                    </div>
                  )}
                  <div className={`event-table-wrap${hasPastEvents ? " event-table-wrap-scrollable" : ""}`}>
                    <table className="data-table event-table event-table-compact">
                      <thead>
                        <tr>
                          {editableEventColumns?.showDate ? <th>Dat.</th> : null}
                          {editableEventColumns?.showTag ? <th>Tag</th> : null}
                          {editableEventColumns?.showTitle ? <th>Titel</th> : null}
                          {editableEventColumns?.showDescription ? <th>Beschreibung</th> : null}
                          {editableEventColumns?.showParticipantCount ? <th className="event-column-count">TN</th> : null}
                          {editableEventColumns?.showCancelled ? <th>Abgesagt</th> : null}
                          {eventListInlineEditable ? (
                            <th className="event-column-actions" aria-label="Aktionen">
                              <button
                                type="button"
                                className="button-ghost button-icon"
                                title="Terminzeile hinzufügen"
                                aria-label="Terminzeile hinzufügen"
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
                        {eventListInlineEditable && showNewEventRow && newEventDraft ? (
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
                            {editableEventColumns?.showCancelled ? <td /> : null}
                            {eventListInlineEditable ? (
                              <td>
                                <div className="event-row-actions">
                                  <button
                                    type="button"
                                    className="button-ghost button-icon button-icon-danger"
                                    title="Neue Terminzeile verwerfen"
                                    aria-label="Neue Terminzeile verwerfen"
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
                            const showCancelledStyle = editableEventColumns?.showCancelled && eventRow.is_cancelled;
                            return (
                              <tr
                                key={eventRow.id}
                                className={`${isPast && blockConfig.event_gray_past !== false ? "event-row-past" : ""}${showCancelledStyle ? " event-row-cancelled" : ""}`}
                                data-upcoming={rowIndex === firstUpcomingIndex ? "true" : undefined}
                                onContextMenu={(nativeEvent) => onEventContextMenu(nativeEvent, eventRow, block.id)}
                              >
                                {editableEventColumns?.showDate ? (
                                  <td>
                                    {eventListInlineEditable ? (
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
                                    {eventListInlineEditable ? (
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
                                    {eventListInlineEditable ? (
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
                                    {eventListInlineEditable ? (
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
                                    {eventListInlineEditable ? (
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
                                {editableEventColumns?.showCancelled ? (
                                  <td>
                                    {eventRow.is_cancelled ? <Badge variant="danger">Abgesagt</Badge> : <span className="muted">–</span>}
                                  </td>
                                ) : null}
                                {eventListInlineEditable ? (
                                  <td>
                                    <div className="event-row-actions">
                                      <button
                                        type="button"
                                        className="button-ghost button-icon button-icon-danger"
                                        title="Termin löschen"
                                        aria-label="Termin löschen"
                                        onClick={async () => {
                                          const ok = await confirm({
                                            message: `Termin "${eventRow.title}" endgültig löschen? Das entfernt ihn aus allen Protokollen.`,
                                            tone: "danger",
                                            confirmLabel: "Löschen"
                                          });
                                          if (!ok) return;
                                          await deleteEventFromBlock(block.id, eventRow.id);
                                        }}
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
                            <td colSpan={Number(editableEventColumns?.showDate) + Number(editableEventColumns?.showTag) + Number(editableEventColumns?.showTitle) + Number(editableEventColumns?.showDescription) + Number(editableEventColumns?.showParticipantCount) + Number(editableEventColumns?.showCancelled) + Number(eventListInlineEditable)}>
                              <span className="muted">Keine passenden Termine.</span>
                            </td>
                          </tr>
                        ) : null}
                      </tbody>
                    </table>
                  </div>
                  {isPlanningMode && (
                    <EventOverviewModal
                      open={eventOverviewBlockId === block.id}
                      onClose={() => setEventOverviewBlockId(null)}
                      protocolId={protocol.id}
                      forcedTag={forcedEventTag}
                      allowEndDate={allowEventEndDate}
                      protocolDate={protocol.protocol_date ?? null}
                      visibleEvents={editableEventRows}
                      availableParticipants={availableParticipants}
                      knownEventTags={knownEventTags}
                      tagConfig={tagConfig}
                      onTagColorChange={updateTagColor}
                      onTagRename={renameTag}
                      onCreateEvent={(draft) => createEventFromBlock(block.id, blockConfig, draft)}
                      onUpdateEvent={(eventId, patch) => updateEventFromBlock(block.id, eventId, patch)}
                      onDeleteEvent={(eventId) => deleteEventFromBlock(block.id, eventId)}
                    />
                  )}
                </div>
              )}

              {elementType === "attendance" && (() => {
                const attendanceEntries = Array.isArray(blockConfig.attendance_entries) ? (blockConfig.attendance_entries as Array<Record<string, any>>) : [];
                const fineAccountId = Number(blockConfig.fine_account_id ?? 0);
                const fineAmountLate = Number(blockConfig.fine_amount_late ?? 0);
                const fineAmountAbsent = Number(blockConfig.fine_amount_absent ?? 0);
                const hasFineConfig = fineAccountId > 0 && (fineAmountLate > 0 || fineAmountAbsent > 0);

                async function handleAttendanceChange(participant: ParticipantSummary, newStatus: string) {
                  const previousEntries = attendanceEntries;
                  const nextEntries = attendanceEntries.filter((entry) => Number(entry.participant_id) !== participant.id);
                  nextEntries.push({ participant_id: participant.id, participant_name: participant.display_name, status: newStatus });
                  try {
                    await saveBlockConfiguration(block.id, { ...blockConfig, attendance_entries: nextEntries });

                    if (hasFineConfig) {
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

                    bumpStatsCharts();
                  } catch (error) {
                    // The sequence can fail partway through (attendance saved but fine update
                    // failed, or vice versa) - roll the attendance status back to what it was
                    // before this change so the UI doesn't show a state that never fully applied.
                    await saveBlockConfiguration(block.id, { ...blockConfig, attendance_entries: previousEntries }).catch(() => {});
                    showToast(
                      error instanceof Error
                        ? `Anwesenheit/Busse eventuell nicht synchron: ${error.message}`
                        : "Anwesenheit/Busse eventuell nicht synchron. Bitte prüfen.",
                      "error"
                    );
                  }
                }

                const { present: nPresent, late: nLate, excused: nExcused, absent: nAbsent } =
                  tallyAttendance(availableParticipants, attendanceEntries);
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
                <div className="session-date-block">
                  <div className="session-date-main">
                    <span className="session-date-label">Datum</span>
                    <DateInput
                      value={String(blockConfig.selected_date ?? "")}
                      readOnly={!blockEditable}
                      onChange={(value) => { if (blockEditable) patchBlockConfigValue(block.id, "selected_date", value || null, blockConfig); }}
                    />
                  </div>
                  {availableTemplates.filter((t) => t.status !== "archived").length > 1 && (() => {
                    const activeFollowupId = blockConfig.followup_template_id
                      ? Number(blockConfig.followup_template_id)
                      : null;
                    const selectedTemplate = activeFollowupId
                      ? availableTemplates.find((t) => t.id === activeFollowupId)
                      : null;
                    const triggerLabel = selectedTemplate?.name ?? "Wie dieses Protokoll";
                    const otherTemplates = availableTemplates.filter(
                      (t) => t.id !== protocol.template_id && t.status !== "archived",
                    );
                    return (
                      <div className="session-date-template">
                        <span className="session-date-label">Folge-Template</span>
                        <TodoMiniMenu label={triggerLabel} compact>
                          {(close) => (
                            <div className="mini-menu-section">
                              <TodoMenuOption
                                label="Wie dieses Protokoll"
                                active={!activeFollowupId}
                                onClick={() => {
                                  patchBlockConfigValue(block.id, "followup_template_id", null, blockConfig);
                                  close();
                                }}
                              />
                              {otherTemplates.map((template) => (
                                <TodoMenuOption
                                  key={template.id}
                                  label={template.name}
                                  active={activeFollowupId === template.id}
                                  onClick={() => {
                                    patchBlockConfigValue(block.id, "followup_template_id", template.id, blockConfig);
                                    close();
                                  }}
                                />
                              ))}
                            </div>
                          )}
                        </TodoMiniMenu>
                      </div>
                    );
                  })()}
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
                          return (
                            <div key={fine.id} id={`fine-row-${fine.id}`} className={`fine-list-row${isCollected ? " fine-collected" : ""}`}>
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
                                {isCollected && (
                                  <>
                                    <span className="todo-pending-resolved">Kassiert</span>
                                    {fine.collected_at && (
                                      <span className="fine-collected-note" style={{ display: "block" }}>
                                        {formatDateTime(fine.collected_at)}
                                        {fine.collected_by_display_name ? ` von ${fine.collected_by_display_name}` : ""}
                                      </span>
                                    )}
                                  </>
                                )}
                              </span>
                              {!isCollected && !isReadOnly ? (
                                <button
                                  type="button"
                                  className="fine-action-btn fine-collect-btn"
                                  title="Busse kassieren"
                                  aria-label="Busse kassieren"
                                  onClick={async () => {
                                    try {
                                      const updated = await browserApiFetch<AttendanceFine>(
                                        `/api/fines/${fine.id}/collect`,
                                        { method: "POST", body: JSON.stringify({ collecting_protocol_id: protocol.id }) }
                                      );
                                      if (updated) setPendingFines((prev) => prev.map((f) => f.id === updated.id ? { ...f, ...updated } : f));
                                    } catch (error) {
                                      showToast(error instanceof Error ? error.message : "Busse konnte nicht kassiert werden", "error");
                                    }
                                  }}
                                >✓</button>
                              ) : <span />}
                              {!isCollected && !isReadOnly ? (
                                <button
                                  type="button"
                                  className="fine-action-btn fine-delete-btn"
                                  title="Busse löschen"
                                  aria-label="Busse löschen"
                                  onClick={async () => {
                                    const ok = await confirm({
                                      message: "Busse endgültig löschen? Dies kann nicht rückgängig gemacht werden.",
                                      tone: "danger",
                                      confirmLabel: "Löschen"
                                    });
                                    if (!ok) return;
                                    try {
                                      await browserApiFetch(`/api/fines/${fine.id}`, { method: "DELETE" });
                                      setPendingFines((prev) => prev.filter((f) => f.id !== fine.id));
                                    } catch (error) {
                                      showToast(error instanceof Error ? error.message : "Busse konnte nicht gelöscht werden", "error");
                                    }
                                  }}
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
                      const isCollectedElsewhere = isCollected && !!fine.closed_in_protocol_id;
                      return (
                        <div key={fine.id} id={`fine-row-${fine.id}`} className={`fine-list-row${isCollected ? " fine-collected" : ""}`}>
                          <span className="fine-participant">{fine.participant_name_snapshot}</span>
                          <span className="fine-type-label">{fine.fine_type === "late" ? "Verspätet" : "Unentschuldigt"}</span>
                          <span className="fine-amount">{fine.amount.toFixed(2)} {cur}</span>
                          <span className="fine-status">
                            {isCollectedElsewhere ? (
                              <span className="todo-closed-elsewhere-badge">Später beglichen</span>
                            ) : isCollected ? "✓ Kassiert" : "Ausstehend"}
                            {isCollected && fine.collected_at && (
                              <span className="fine-collected-note" style={{ display: "block" }}>
                                {formatDateTime(fine.collected_at)}
                                {fine.collected_by_display_name ? ` von ${fine.collected_by_display_name}` : ""}
                              </span>
                            )}
                          </span>
                          {!isCollected && !isReadOnly ? (
                            <button
                              type="button"
                              className="fine-action-btn fine-collect-btn"
                              title="Busse kassieren"
                              aria-label="Busse kassieren"
                              onClick={async () => {
                                try {
                                  const updated = await browserApiFetch<AttendanceFine>(
                                    `/api/fines/${fine.id}/collect`,
                                    { method: "POST", body: JSON.stringify({ collecting_protocol_id: protocol.id }) }
                                  );
                                  if (updated) setProtocolFines((prev) => prev.map((f) => f.id === updated.id ? updated : f));
                                } catch (error) {
                                  showToast(error instanceof Error ? error.message : "Busse konnte nicht kassiert werden", "error");
                                }
                              }}
                            >✓</button>
                          ) : <span />}
                          {!isCollected ? (
                            <button
                              type="button"
                              className="fine-action-btn fine-delete-btn"
                              title="Busse löschen"
                              aria-label="Busse löschen"
                              onClick={async () => {
                                const ok = await confirm({
                                  message: "Busse endgültig löschen? Dies kann nicht rückgängig gemacht werden.",
                                  tone: "danger",
                                  confirmLabel: "Löschen"
                                });
                                if (!ok) return;
                                try {
                                  await browserApiFetch(`/api/fines/${fine.id}`, { method: "DELETE" });
                                  setProtocolFines((prev) => prev.filter((f) => f.id !== fine.id));
                                } catch (error) {
                                  showToast(error instanceof Error ? error.message : "Busse konnte nicht gelöscht werden", "error");
                                }
                              }}
                            >✕</button>
                          ) : <span />}
                        </div>
                      );
                    })}
                    </div>}

                  </div>
                );
              })()}

              {elementType === "chart" && (
                <ChartBlockRenderer
                  blockId={block.id}
                  config={blockConfig as { chart_type?: string; cycle_key?: string }}
                  editable={false}
                  onSave={(cfg) => void saveBlockConfiguration(block.id, cfg)}
                />
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
                        <LightboxImage alt={image.title ?? image.original_name} src={`${browserApiBaseUrl}${image.content_url}`} />
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
        {/* The "Termine auswählen" trigger lives in the top-right notch of the red border
            itself (see isFirstInAutoGroup above), not as a separate row. */}
      </div>
      {/* Rendered inside the same <section> (not as a sibling) so it shares this element's
          blur/inert/active state in the scrollable document layout, and is included in the
          section's own bounding box for the scroll-spy's centering calculation. */}
      <SessionTodosSection
        sectionTag={trimSectionName(element.section_name_snapshot)}
        todos={Object.values(todosByBlock).flat().filter((t) => (t.tags ?? []).includes(trimSectionName(element.section_name_snapshot).toLowerCase()))}
        pendingTodos={pendingTodos.filter((t) => (t.tags ?? []).includes(trimSectionName(element.section_name_snapshot).toLowerCase()))}
        isReadOnly={isReadOnly}
        trackChangesActive={trackChangesActive}
        participants={availableParticipants}
        dueEvents={[...availableEvents].sort((a, b) => a.event_date.localeCompare(b.event_date))}
        protocol={protocol}
        onUpdate={updateTodo}
        onDelete={deleteTodo}
        onPendingUpdate={onPendingUpdate}
        onPendingDone={onPendingDone}
        onAcceptTrackedChange={acceptTodoTrackedChange}
      />
    </section>
    {isPlanningMode && (() => {
      const referenceBlock = element.blocks.find((b) => asObject(b.configuration_snapshot_json).repeat_source_type === "event");
      const referenceConfig = referenceBlock ? asObject(referenceBlock.configuration_snapshot_json) : {};
      const tagFilters = String(referenceConfig.event_tag_filter ?? "").split(",").map((t) => t.trim().toLowerCase()).filter(Boolean);
      const usedEventIds = new Set(
        element.blocks
          .map((b) => asObject(b.configuration_snapshot_json).repeat_source_id)
          .filter((id) => id != null)
          .map(Number)
      );
      const existingItems: CandidateItem[] = element.blocks
        .filter((b) => asObject(b.configuration_snapshot_json).repeat_source_type === "event")
        .map((b) => {
          const config = asObject(b.configuration_snapshot_json);
          const eventId = Number(config.repeat_source_id);
          const evt = availableEvents.find((e) => e.id === eventId);
          return {
            id: `block-${b.id}`,
            label: String(config.repeat_source_label ?? evt?.title ?? `Termin ${eventId}`),
            sublabel: evt ? `${formatDate(evt.event_date)}${evt.tag ? ` · ${evt.tag}` : ""}` : undefined,
            checked: b.is_visible_snapshot,
            groupLabel: "Bereits vorhanden",
          };
        });
      function toCandidateItem(evt: EventSummary, groupLabel: string): CandidateItem {
        return {
          id: `event-${evt.id}`,
          label: evt.title,
          sublabel: `${formatDate(evt.event_date)}${evt.tag ? ` · ${evt.tag}` : ""}`,
          checked: false,
          groupLabel,
        };
      }
      const availableCandidates = eventBlockCandidates
        .filter((evt) => !usedEventIds.has(evt.id))
        .sort((a, b) => a.event_date.localeCompare(b.event_date));
      const matchingCandidates = tagFilters.length
        ? availableCandidates.filter((evt) => tagFilters.some((t) => (evt.tag ?? "").toLowerCase().includes(t)))
        : availableCandidates;
      const otherCandidates = tagFilters.length
        ? availableCandidates.filter((evt) => !tagFilters.some((t) => (evt.tag ?? "").toLowerCase().includes(t)))
        : [];
      const candidateItems: CandidateItem[] = [
        ...matchingCandidates.map((evt) => toCandidateItem(evt, "Passend zum Filter")),
        ...otherCandidates.map((evt) => toCandidateItem(evt, "Weitere Termine")),
      ];
      function findCandidateEvent(item: CandidateItem): EventSummary | undefined {
        if (item.id.startsWith("block-")) {
          const b = element.blocks.find((blk) => `block-${blk.id}` === item.id);
          const eventId = b ? Number(asObject(b.configuration_snapshot_json).repeat_source_id) : NaN;
          return availableEvents.find((e) => e.id === eventId);
        }
        const eventId = Number(item.id.slice("event-".length));
        return eventBlockCandidates.find((e) => e.id === eventId);
      }
      // Unchecking a "Bereits vorhanden" Termin removes its block outright (not just hides it) so
      // it visibly leaves this group and becomes an available candidate again — hiding it here left
      // a confusing unchecked "ghost" entry stuck in "Bereits vorhanden". Note: this deletes the
      // block's own content (e.g. typed text) — re-checking creates a fresh block, it does not
      // restore prior text.
      async function handleToggle(item: CandidateItem, nextChecked: boolean) {
        if (item.id.startsWith("block-")) {
          const blockId = Number(item.id.slice("block-".length));
          if (nextChecked) {
            await unhideEventBlock(blockId);
          } else {
            const ok = await confirm({
              message: "Termin abwählen? Der Inhalt dieses Blocks (z.B. eingegebener Text) geht dabei verloren und wird beim erneuten Anhaken NICHT wiederhergestellt.",
              tone: "danger",
              confirmLabel: "Abwählen"
            });
            if (!ok) return;
            await removeEventBlock(blockId);
          }
        } else if (item.id.startsWith("event-") && nextChecked) {
          const eventId = Number(item.id.slice("event-".length));
          await addEventBlockToElement(element.id, eventId);
        }
      }
      async function handleCreateNew() {
        if (!eventBlockNewDraft.event_date.trim() || !eventBlockNewDraft.title.trim()) return;
        setCreatingEventBlockNew(true);
        const created = await createEventFromBlock(referenceBlock?.id ?? 0, referenceConfig, eventBlockNewDraft);
        if (created) {
          await addEventBlockToElement(element.id, created.id);
          setEventBlockNewDraft(createProtocolEventDraft(protocol.protocol_date, String(referenceConfig.event_tag_filter ?? "").trim()));
          setShowEventBlockCreateForm(false);
        }
        setCreatingEventBlockNew(false);
      }
      const forcedTagForNew = String(referenceConfig.event_tag_filter ?? "").trim();
      return (
        <CheckboxCandidateModal
          open={showEventBlockPicker}
          onClose={() => setShowEventBlockPicker(false)}
          title="Termine auswählen"
          description="Auf einen Termin klicken, um ihn an-/abzuwählen. Passend zum Filter stehen oben, weitere Termine unten."
          items={[...existingItems, ...candidateItems]}
          loading={eventBlockCandidatesLoading}
          onToggle={handleToggle}
          renderEditForm={(item) => {
            const evt = findCandidateEvent(item);
            if (!evt) return null;
            return (
              <EventDetailForm
                event={evt}
                allowEndDate={referenceConfig.event_allow_end_date === true}
                availableParticipants={availableParticipants}
                knownEventTags={knownEventTags}
                tagConfig={tagConfig}
                onTagColorChange={updateTagColor}
                onTagRename={renameTag}
                onUpdate={(patch) =>
                  updateEventFromBlock(referenceBlock?.id ?? 0, evt.id, patch).then(refreshEventBlockCandidates)
                }
              />
            );
          }}
          topActions={
            <div style={{ display: "grid", gap: 12, width: "100%" }}>
              <div className="list-block-config-bar">
                <button
                  type="button"
                  className={`button-toggle${eventBlockScope === "current" ? " button-toggle-active" : ""}`}
                  onClick={() => setEventBlockScope("current")}
                >
                  Aktueller Zyklus
                </button>
                <button
                  type="button"
                  className={`button-toggle${eventBlockScope === "all" ? " button-toggle-active" : ""}`}
                  onClick={() => setEventBlockScope("all")}
                >
                  Alle Termine
                </button>
              </div>
              {showEventBlockCreateForm ? (
                <div className="event-row-new grid" style={{ gap: 8 }}>
                  <div className="event-date-fields">
                    <DateInput
                      className="event-field-date"
                      value={eventBlockNewDraft.event_date}
                      disabled={creatingEventBlockNew}
                      onChange={(value) => setEventBlockNewDraft((d) => ({ ...d, event_date: value }))}
                    />
                  </div>
                  <TagInput
                    value={forcedTagForNew || eventBlockNewDraft.tag}
                    onChange={(v) => setEventBlockNewDraft((d) => ({ ...d, tag: v }))}
                    suggestions={knownEventTags}
                    placeholder="Tag"
                    multi={false}
                    readOnly={Boolean(forcedTagForNew) || creatingEventBlockNew}
                    tagConfig={tagConfig}
                    onTagColorChange={updateTagColor}
                    onTagRename={renameTag}
                  />
                  <input
                    className="input event-field-title"
                    value={eventBlockNewDraft.title}
                    disabled={creatingEventBlockNew}
                    onChange={(e) => setEventBlockNewDraft((d) => ({ ...d, title: e.target.value }))}
                    placeholder="Titel"
                  />
                  <div className="modal-actions">
                    <button type="button" className="button-ghost" disabled={creatingEventBlockNew} onClick={() => setShowEventBlockCreateForm(false)}>
                      Abbrechen
                    </button>
                    <button type="button" className="button-primary" disabled={creatingEventBlockNew} onClick={() => void handleCreateNew()}>
                      {creatingEventBlockNew ? "…" : "Termin anlegen"}
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  className="button-inline"
                  style={{ justifySelf: "start" }}
                  onClick={() => setShowEventBlockCreateForm(true)}
                >
                  + Neuer Termin
                </button>
              )}
            </div>
          }
        />
      );
    })()}
    <Modal
      open={Boolean(multiParticipantPicker)}
      onClose={() => closeParticipantPicker()}
      title={multiParticipantPicker ? `Teilnehmer waehlen: ${multiParticipantPicker.rowLabel}` : "Teilnehmer waehlen"}
      description={multiParticipantPicker?.singleSelect ? "Teilnehmer auswaehlen." : "Suche nach Teilnehmern und markiere mehrere Eintraege mit Haken."}
    >
      <div className="grid">
        <label className="field-stack">
          <span className="field-label">Suche</span>
          <input
            ref={multiParticipantSearchRef}
            value={multiParticipantSearch}
            onChange={(event) => setMultiParticipantSearch(event.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                if (multiParticipantPicker?.singleSelect) {
                  if (filteredParticipants.length === 1) selectSingleParticipant(filteredParticipants[0].id);
                } else if (multiParticipantPicker) {
                  const currentBlock = element.blocks.find((b) => b.id === multiParticipantPicker.blockId);
                  if (currentBlock) {
                    applyMultiParticipantSelection(currentBlock.id, asObject(currentBlock.configuration_snapshot_json));
                  }
                }
              }
            }}
            placeholder="Teilnehmer suchen"
            autoFocus
          />
        </label>
        {!multiParticipantPicker?.singleSelect && (
          <div className="status-row">
            <span className="pill">{multiParticipantPicker?.selectedIds.length ?? 0} ausgewaehlt</span>
            <span className="pill">{filteredParticipants.length} sichtbar</span>
          </div>
        )}
        <div className="selection-list">
          {filteredParticipants.map((participant) => {
            const checked = multiParticipantPicker?.selectedIds.includes(participant.id) ?? false;
            const isSingle = Boolean(multiParticipantPicker?.singleSelect);
            return (
              <label key={participant.id} className={`selection-card selection-card-checkbox${checked ? " selection-card-active" : ""}`}>
                <input
                  type={isSingle ? "radio" : "checkbox"}
                  checked={checked}
                  onChange={() => {
                    if (isSingle) {
                      selectSingleParticipant(participant.id);
                    } else {
                      toggleMultiParticipantSelection(participant.id);
                    }
                  }}
                  onKeyDown={(e) => {
                    if (isSingle) return;
                    if (e.key === " ") {
                      e.preventDefault();
                      toggleMultiParticipantSelection(participant.id);
                      multiParticipantSearchRef.current?.focus();
                      multiParticipantSearchRef.current?.select();
                    } else if (e.key === "Enter") {
                      e.preventDefault();
                      if (multiParticipantPicker) {
                        const currentBlock = element.blocks.find((b) => b.id === multiParticipantPicker.blockId);
                        if (currentBlock) {
                          applyMultiParticipantSelection(currentBlock.id, asObject(currentBlock.configuration_snapshot_json));
                        }
                      }
                    }
                  }}
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
        {!multiParticipantPicker?.singleSelect && (
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
        )}
      </div>
    </Modal>
    </>
  );
}
