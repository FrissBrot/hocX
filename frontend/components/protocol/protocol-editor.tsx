"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";

import { SessionPanel, SessionPanelHandle } from "@/components/protocol/session-panel";
import { Modal } from "@/components/ui/modal";
import { Badge } from "@/components/ui/badge";
import { NavIcon } from "@/components/ui/nav-icons";
import { QuickActionsPill } from "@/components/protocol/quick-actions-pill";
import { bumpStatsCharts } from "@/components/protocol/chart-block";
import { CollaborationPresenceBar } from "@/components/protocol/collaboration-presence";
import { computePopoverPosition, usePopoverDismiss } from "@/components/ui/popover";
import { useProtocolCollaboration } from "@/lib/hooks/use-protocol-collaboration";
import { useTagConfig } from "@/lib/hooks/use-tag-config";
import { usePdfExport } from "@/lib/hooks/use-pdf-export";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { getCycleYear } from "@/lib/utils/cycle";
import { protocolStatusVariant } from "@/components/protocol/protocol-status";
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
import {
  ProtocolEventDraft,
  TODO_STATUS,
  TodoMenuOption,
  TodoMiniMenu,
  attendanceParticipants,
  createProtocolEventDraft,
  protocolStatusLabel,
  resequenceProtocolElements,
  sectionIconKey,
  tallyAttendance,
  trimSectionName,
  visibleBlockTitle,
} from "@/components/protocol/protocol-editor-shared";
import { CollaborationStatusPanel } from "@/components/protocol/collaboration-status-panel";
import { FocusedElementEditor } from "@/components/protocol/focused-element-editor";

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
  documentTemplates?: DocumentTemplate[];
  forceReadOnly?: boolean;
  canViewFines?: boolean;
};

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
  documentTemplates = [],
  forceReadOnly = false,
  canViewFines = true,
}: ProtocolEditorProps) {
  const router = useRouter();
  const [elements, setElements] = useState(initialElements);
  const [events, setEvents] = useState(availableEvents);
  const [lists, setLists] = useState(availableLists);
  const [eventContextMenu, setEventContextMenu] = useState<{ x: number; y: number; eventRow: EventSummary; blockId: number } | null>(null);
  const eventContextMenuRef = useRef<HTMLDivElement | null>(null);

  usePopoverDismiss(!!eventContextMenu, () => setEventContextMenu(null), [eventContextMenuRef]);

  // Closing on scroll is specific to this point-anchored context menu (it doesn't reposition
  // itself the way an anchored popover would), so it stays a separate effect alongside the
  // shared outside-click/Escape dismissal above rather than being folded into usePopoverDismiss.
  useEffect(() => {
    if (!eventContextMenu) return;
    function onScroll() {
      setEventContextMenu(null);
    }
    document.addEventListener("scroll", onScroll, true);
    return () => document.removeEventListener("scroll", onScroll, true);
  }, [eventContextMenu]);

  const currentTemplate = availableTemplates.find((t) => t.id === protocol.template_id) ?? null;
  const currentCycleYear: number | null = protocol.protocol_date && currentTemplate?.cycle_config
    ? getCycleYear(protocol.protocol_date, currentTemplate.cycle_config.reset_month, currentTemplate.cycle_config.reset_day)
    : null;
  const [listEntriesByDefinition, setListEntriesByDefinition] = useState<Record<number, StructuredListEntry[]>>(initialListEntries);
  const [todosByBlock, setTodosByBlock] = useState<Record<number, ProtocolTodo[]>>(initialTodos);
  const [pendingTodos, setPendingTodos] = useState<TodoListItem[]>(initialPendingTodos);
  const [imagesByBlock, setImagesByBlock] = useState<Record<number, ProtocolImage[]>>(initialImages);
  const [financeTransactions, setFinanceTransactions] = useState<Record<number, FinanceTransaction[]>>(initialFinanceTransactions);
  const [protocolFines, setProtocolFines] = useState<AttendanceFine[]>([]);
  const [pendingFines, setPendingFines] = useState<AttendanceFineListItem[]>([]);
  // Refresh chart blocks whenever fines change (add/delete)
  useEffect(() => { bumpStatsCharts(); }, [protocolFines.length]);
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
  const [trackChangesEnabled, setTrackChangesEnabledState] = useState(protocol.track_changes_enabled ?? false);
  // Tracking applies during "geplant" - confusingly, that's the status the app's own
  // workflowMeta below labels "Vorbereitungsmodus" ("preparation mode"); "vorbereitet"
  // is actually the live-session phase ("Sitzungsmodus"), where existing marks stay
  // visible but nothing new gets marked, exactly as requested.
  const trackChangesActive = protocolStatus === "geplant" && trackChangesEnabled;
  const [sessionNotes, setSessionNotes] = useState(protocol.session_notes ?? "");
  const [transitioningStatus, setTransitioningStatus] = useState(false);
  const showToast = useToast();
  const confirm = useConfirm();
  const elementSaveTimerRef = useRef<number | null>(null);
  const isRestoringRef = useRef(true);
  const [showSavedIndicator, setShowSavedIndicator] = useState(false);
  const savedIndicatorTimerRef = useRef<number | null>(null);
  const prevBlockStatusRef = useRef<Record<number, SaveState>>({});
  const collab = useProtocolCollaboration(protocol.id);
  const [showStatusChangeWarning, setShowStatusChangeWarning] = useState(false);

  useEffect(
    () =>
      collab.onStatusChanged(({ status, display_name }) => {
        setProtocolStatus(status);
        showToast(`Status wurde von ${display_name} zu "${protocolStatusLabel(status)}" geändert.`);
        // The backend already cleared every tracked-change mark server-side on this same
        // transition - refetch so a viewer who stays on this page (not the one who
        // triggered the transition, which navigates away right after) doesn't keep
        // showing stale red marks until a manual reload.
        if (status === "durchgeführt") {
          void refreshAfterTrackingCleared();
        }
      }),
    [collab.onStatusChanged, showToast]
  );

  useEffect(
    () =>
      collab.onFieldUpdate(({ field_key, patch }) => {
        if (field_key === "element-titles") {
          void refreshElementTitles();
          return;
        }
        if (field_key === "track-changes-toggle") {
          setTrackChangesEnabledState(!!(patch as { enabled?: boolean } | null)?.enabled);
          return;
        }
        // Todos/images/events had no live sync at all before this (audit F2, 2026-08-16):
        // another viewer only ever saw them after a manual reload. Broadcasts the full
        // resulting array/object (small lists, simpler than create/update/delete diffing)
        // right after the mutating client's own local state update - see
        // addTodo/updateTodo/deleteTodo, uploadImage/deleteImage,
        // createEventFromBlock/updateEventFromBlock/deleteEventFromBlock.
        if (field_key.endsWith("-todos") && field_key.startsWith("block-")) {
          const blockId = Number(field_key.slice("block-".length, -"-todos".length));
          if (Number.isFinite(blockId) && Array.isArray(patch)) {
            setTodosByBlock((current) => ({ ...current, [blockId]: patch as ProtocolTodo[] }));
          }
          return;
        }
        if (field_key.endsWith("-images") && field_key.startsWith("block-")) {
          const blockId = Number(field_key.slice("block-".length, -"-images".length));
          if (Number.isFinite(blockId) && Array.isArray(patch)) {
            setImagesByBlock((current) => ({ ...current, [blockId]: patch as ProtocolImage[] }));
          }
          return;
        }
        if (field_key === "event-created" && patch && typeof patch === "object") {
          const created = patch as EventSummary;
          setEvents((current) => (current.some((event) => event.id === created.id) ? current : [...current, created]));
          return;
        }
        if (field_key === "event-updated" && patch && typeof patch === "object") {
          const updated = patch as EventSummary;
          setEvents((current) => current.map((event) => (event.id === updated.id ? updated : event)));
          return;
        }
        if (field_key === "event-deleted" && patch && typeof patch === "object") {
          const { id } = patch as { id: number };
          setEvents((current) => current.filter((event) => event.id !== id));
          return;
        }
        if (!field_key.startsWith("block-")) return;
        const blockId = Number(field_key.slice("block-".length).split("-cell-")[0]);
        if (!Number.isFinite(blockId) || !patch || typeof patch !== "object") return;
        updateBlockInState(blockId, (block) => ({ ...block, ...(patch as Partial<typeof block>) }));
        // textDrafts (what the <textarea> actually renders, see handleTextChange) is
        // separate from the elements/blocks state updated above - without this, a text
        // block another user just saved keeps showing this client's stale draft even
        // after the field's readOnly lock releases, and the next local edit here would
        // silently overwrite the other user's change on save (audit F1, 2026-08-16).
        const incomingText = (patch as { text_content?: unknown }).text_content;
        if (typeof incomingText === "string") {
          setTextDrafts((current) => ({ ...current, [blockId]: incomingText }));
        }
      }),
    [collab.onFieldUpdate]
  );

  // Live "a list this protocol references changed elsewhere" push - just bumps the list's
  // known content_version so the stale-hint comparison in focused-element-editor.tsx picks
  // it up on the next render, even while this protocol stays open without a reload. Never
  // touches list_snapshot data itself - that only ever changes via an explicit refresh/sync.
  useEffect(
    () =>
      collab.onListChanged(({ list_definition_id, content_version }) => {
        setLists((current) =>
          current.map((list) => (list.id === list_definition_id ? { ...list, content_version } : list))
        );
      }),
    [collab.onListChanged]
  );

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
  // The icon/popup-driven planning UI (Tabelle-aus-Liste, Terminlisten, Termine-pro-Element,
  // Matrix-Auto-Spalten) is available in every status except "abgeschlossen", where isReadOnly
  // already blocks all editing.
  const isPlanningMode = !isReadOnly;
  // Scrollable-document layout (all sections mounted, non-active ones blurred) for every
  // status except "abgeschlossen", which keeps the original single-section-at-a-time view.
  const useDocumentLayout = protocolStatus !== "abgeschlossen";
  // Lifted here (was previously called once per FocusedElementEditor instance) so it fires
  // once regardless of how many sections are simultaneously mounted in the document layout.
  const { tagConfig, updateTagColor, renameTag } = useTagConfig();
  const { busyByProtocol: pdfBusyByProtocol, openOrGeneratePdf } = usePdfExport();

  const workflowMeta: Record<string, { modeLabel: string; ctaLabel: string; nextStatus: string }> = {
    geplant:       { modeLabel: "Vorbereitungsmodus",   ctaLabel: "Vorbereitung abschliessen", nextStatus: "vorbereitet" },
    vorbereitet:   { modeLabel: "Sitzungsmodus",         ctaLabel: "Sitzung abschliessen",      nextStatus: "durchgeführt" },
    durchgeführt:  { modeLabel: "Nachbearbeitungsmodus", ctaLabel: "Protokoll abschliessen",    nextStatus: "abgeschlossen" },
    abgeschlossen: { modeLabel: "Abgeschlossen",         ctaLabel: "",                          nextStatus: "" },
  };


  const performStatusTransition = async () => {
    const next = workflowMeta[protocolStatus]?.nextStatus;
    if (!next) return;

    setTransitioningStatus(true);
    try {
      await browserApiFetch(`/api/protocols/${protocol.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: next }),
      });
      setProtocolStatus(next);
      collab.sendStatusChanged(next);
      // Reset the remembered scroll position so reopening the protocol later starts at the
      // top again, instead of jumping back to wherever the status-transition button was
      // (typically the last point).
      const firstElementId = visibleElements[0]?.id;
      if (firstElementId) {
        if (elementSaveTimerRef.current) window.clearTimeout(elementSaveTimerRef.current);
        await browserApiFetch(`/api/protocols/${protocol.id}/scroll-position`, {
          method: "PUT",
          body: JSON.stringify({ element_id: firstElementId }),
        }).catch(() => {});
      }
      router.refresh();
      router.push("/protocols");
    } catch (err: unknown) {
      if (err instanceof Error) showToast(err.message);
    } finally {
      setTransitioningStatus(false);
    }
  };

  const transitionStatus = () => {
    if (!workflowMeta[protocolStatus]?.nextStatus) return;
    if (collab.hasOtherActiveEditors) {
      setShowStatusChangeWarning(true);
      return;
    }
    void performStatusTransition();
  };

  // Nur verlassen, ohne den Workflow-Status zu ändern - im Unterschied zu transitionStatus()
  // (Ctrl+Enter sprang bisher am Ende der Punkte in transitionStatus(), was versehentlich eine
  // Sitzung/das Protokoll abschliessen konnte, nur weil man einmal zu oft Ctrl+Enter gedrückt
  // hat).
  const closeProtocol = () => {
    router.push("/protocols");
  };
  const timers = useRef<Record<number, number>>({});
  const shouldScrollToElementRef = useRef(false);
  const navRef = useRef<HTMLElement | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const documentRef = useRef<HTMLElement | null>(null);
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
            .filter((block) => (isPlanningMode || block.is_visible_snapshot) && block.element_type_code !== "display")
            .sort((left, right) => left.sort_index - right.sort_index)
        }))
        .filter((element) => element.blocks.length > 0 || element.show_when_empty)
        .sort((left, right) => left.sort_index - right.sort_index),
    [elements, isPlanningMode]
  );

  const selectedElement = useMemo(
    () => visibleElements.find((element) => element.id === selectedElementId) ?? null,
    [selectedElementId, visibleElements]
  );
  const listDefinitionsById = useMemo(
    () => new Map(lists.map((listDefinition) => [listDefinition.id, listDefinition])),
    [lists]
  );
  const selectedElementIndex = useMemo(
    () => visibleElements.findIndex((element) => element.id === selectedElementId),
    [selectedElementId, visibleElements]
  );
  const attendanceTally = useMemo(() => {
    const attendanceBlock = elements.flatMap((element) => element.blocks).find((block) => block.element_type_code === "attendance");
    if (!attendanceBlock) return null;
    const entries = Array.isArray(attendanceBlock.configuration_snapshot_json.attendance_entries)
      ? (attendanceBlock.configuration_snapshot_json.attendance_entries as Array<Record<string, any>>)
      : [];
    return tallyAttendance(availableParticipants, entries);
  }, [elements, availableParticipants]);
  const attendanceRoster = useMemo(() => {
    const attendanceBlock = elements.flatMap((element) => element.blocks).find((block) => block.element_type_code === "attendance");
    const entries = attendanceBlock && Array.isArray(attendanceBlock.configuration_snapshot_json.attendance_entries)
      ? (attendanceBlock.configuration_snapshot_json.attendance_entries as Array<Record<string, any>>)
      : [];
    return attendanceParticipants(availableParticipants).map((participant) => ({
      id: participant.id,
      name: participant.display_name,
      status: (entries.find((entry) => Number(entry.participant_id) === participant.id)?.status as string | undefined) ?? null,
    }));
  }, [elements, availableParticipants]);
  const [collabStatusPanelOpen, setCollabStatusPanelOpen] = useState(false);

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
        // Document layout: scroll only .protocol-document itself (never section.
        // scrollIntoView() - that walks up and re-scrolls every clipping ancestor it
        // passes on the way, including the outer .app-frame-writing shell that's
        // deliberately pinned to the viewport via overflow:hidden - overflow:hidden
        // still counts as a "scrolling box" for scrollIntoView purposes even though it
        // never shows a scrollbar or responds to wheel input, so it silently absorbed
        // part of the scroll too, leaving the pinned shell offset from the viewport
        // with a matching dead strip of blank space at its bottom edge). The division
        // below undoes .protocol-document-shell's zoom: 0.9, which scales visual
        // pixels (getBoundingClientRect) relative to scrollTop's own unscaled space.
        const container = documentRef.current;
        const section = document.getElementById(`protocol-element-${selectedElementId}`);
        if (container && section) {
          const zoomHost = container.closest<HTMLElement>(".protocol-document-shell");
          const zoom = zoomHost ? parseFloat(getComputedStyle(zoomHost).zoom) || 1 : 1;
          const delta = (section.getBoundingClientRect().top - container.getBoundingClientRect().top) / zoom;
          container.scrollTo({ top: container.scrollTop + delta, behavior: "smooth" });
        }
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

      // Safety net: on the locked document-mode desktop layout the outer page must
      // never itself scroll (see the cascading-scrollIntoView note above - focus() below
      // has the same "scrolls every clipping ancestor" behavior unless told not to, and
      // there may be other browser-driven scroll-restoration sources beyond these two).
      // Confirmed live that leaving this unset does drift the pinned shell off the
      // viewport top with blank space appearing at its bottom to match.
      if (!panelRef.current && window.matchMedia("(min-width: 901px)").matches) {
        window.scrollTo(0, 0);
      }

      window.setTimeout(() => {
        const section = document.getElementById(`protocol-element-${selectedElementId}`);
        if (!section) return;
        const firstEditable = section.querySelector<HTMLElement>(
          '[data-form-input], textarea:not([readonly]), input:not([readonly]):not([type="file"])'
        );
        firstEditable?.focus({ preventScroll: true });
        if (!panelRef.current && window.matchMedia("(min-width: 901px)").matches) {
          window.scrollTo(0, 0);
        }
      }, 120);
    });
  }, [selectedElementId]);

  const visibleElementIdsKey = visibleElements.map((element) => element.id).join(",");

  // Scroll-spy for the continuous document layout: tracks whichever section currently sits
  // at the top of .protocol-document and makes it the active/highlighted one - matching
  // scroll-snap-align: start below (a short section snapped to the top of a much taller
  // pane would otherwise never contain the pane's vertical center, so center-based
  // detection stopped matching scroll-snap-align: start once that was switched from
  // "center"). Uses plain getBoundingClientRect() math (rAF-throttled on scroll/resize)
  // rather than IntersectionObserver - that earlier approach combined a custom `root`,
  // percentage rootMargin and the .protocol-document-shell `zoom` scale in a way that
  // didn't reliably fire (nothing ever got marked active). getBoundingClientRect always
  // reports already-zoomed, viewport-relative coordinates, so it isn't affected by that.
  // Deliberately only calls setSelectedElementId directly (never focusElement/
  // shouldScrollToElementRef) so passive scrolling never triggers the jump-effect's own
  // scroll/focus side effects above.
  useEffect(() => {
    if (!useDocumentLayout) return;
    const container = documentRef.current;
    if (!container) return;

    let rafId: number | null = null;

    function computeActiveSection() {
      rafId = null;
      const containerRect = container!.getBoundingClientRect();
      const topY = containerRect.top + 32;
      const sections = visibleElementIdsKey
        .split(",")
        .filter(Boolean)
        .map((id) => document.getElementById(`protocol-element-${id}`))
        .filter((section): section is HTMLElement => Boolean(section));
      if (!sections.length) return;

      let bestId: number | null = null;
      let bestDistance = Infinity;
      for (const section of sections) {
        const rect = section.getBoundingClientRect();
        const id = Number(section.id.replace("protocol-element-", ""));
        if (rect.top <= topY && rect.bottom >= topY) {
          bestId = id;
          break;
        }
        const distance = Math.abs(rect.top - topY);
        if (distance < bestDistance) {
          bestDistance = distance;
          bestId = id;
        }
      }
      if (bestId !== null) {
        setSelectedElementId((current) => (current === bestId ? current : bestId));
      }
    }

    function scheduleCompute() {
      if (rafId !== null) return;
      rafId = window.requestAnimationFrame(computeActiveSection);
    }

    computeActiveSection();
    container.addEventListener("scroll", scheduleCompute, { passive: true });
    window.addEventListener("resize", scheduleCompute);
    return () => {
      container.removeEventListener("scroll", scheduleCompute);
      window.removeEventListener("resize", scheduleCompute);
      if (rafId !== null) window.cancelAnimationFrame(rafId);
    };
  }, [useDocumentLayout, visibleElementIdsKey]);

  // Suspend the section blur/opacity transition while .protocol-document is actively being
  // scrolled - animating `filter: blur()` on a section at the same time the browser is running
  // its own native scroll-snap animation is what made the whole thing feel janky/buggy;
  // applying the blur state change instantly (no transition) once scrolling settles avoids the
  // two animations fighting each other.
  useEffect(() => {
    if (!useDocumentLayout) return;
    const container = documentRef.current;
    if (!container) return;
    let settleTimer: number | null = null;
    function onScroll() {
      container!.classList.add("is-scrolling");
      if (settleTimer) window.clearTimeout(settleTimer);
      settleTimer = window.setTimeout(() => container!.classList.remove("is-scrolling"), 150);
    }
    container.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      container.removeEventListener("scroll", onScroll);
      if (settleTimer) window.clearTimeout(settleTimer);
    };
  }, [useDocumentLayout]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const inFormField = target && (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.isContentEditable);

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
        } else if (!isReadOnly) {
          event.preventDefault();
          closeProtocol();
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
    } catch (err: unknown) {
      setBlockStatus((current) => {
        const next = { ...current };
        resequenced.forEach((element) => {
          element.blocks.forEach((block) => {
            next[block.id] = "error";
          });
        });
        return next;
      });
      showToast(err instanceof Error ? err.message : "Reihenfolge konnte nicht gespeichert werden", "error");
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

  // Section titles can contain a live-resolved "(Vorname Nachname)" suffix pulled from a
  // linked list entry (see resolve_display_section_title on the backend) - that resolution
  // already happens fresh on every fetch of this endpoint, so refetching it after a list
  // snapshot refresh/undo/sync is enough to pick up new names. Only section_name_snapshot is
  // merged per element (by id), never the whole element, so local block-editing state is
  // never disturbed.
  async function refreshElementTitles() {
    try {
      const fresh = await browserApiFetch<ProtocolElement[]>(`/api/protocols/${protocol.id}/elements`);
      const freshById = new Map(fresh.map((element) => [element.id, element.section_name_snapshot]));
      setElements((current) =>
        current.map((element) =>
          freshById.has(element.id) ? { ...element, section_name_snapshot: freshById.get(element.id)! } : element
        )
      );
    } catch {
      // best-effort - titles just stay as-is until the next successful refresh
    }
  }

  // Full replacement (not the narrow section_name_snapshot-only merge above) - this is
  // only called right after tracked-change marks were cleared server-side, so every
  // block's fresh configuration_snapshot_json/tracked_dirty/tracked_baseline_content is
  // exactly what should now be shown, plus todos need a per-block refetch since
  // pending-delete rows are now really gone.
  async function refreshAfterTrackingCleared() {
    try {
      const fresh = await browserApiFetch<ProtocolElement[]>(`/api/protocols/${protocol.id}/elements`);
      setElements(fresh);
      const todoBlockIds = fresh.flatMap((element) =>
        element.blocks.filter((block) => block.element_type_code === "todo").map((block) => block.id)
      );
      const todoLists = await Promise.all(
        todoBlockIds.map((blockId) =>
          browserApiFetch<ProtocolTodo[]>(`/api/protocol-element-blocks/${blockId}/todos`).then(
            (list) => [blockId, list] as const
          )
        )
      );
      setTodosByBlock((current) => {
        const next = { ...current };
        for (const [blockId, list] of todoLists) next[blockId] = list;
        return next;
      });
    } catch {
      // best-effort - a manual reload always recovers correct state
    }
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
      collab.sendFieldUpdate(`block-${blockId}`, { configuration_snapshot_json: updated.configuration_snapshot_json });
    } catch (err: unknown) {
      setStatus(blockId, "error");
      showToast(err instanceof Error ? err.message : "Änderung konnte nicht gespeichert werden", "error");
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
        const result = await browserApiFetch<{ tracked_dirty: boolean; tracked_baseline_content: string | null }>(
          `/api/protocol-element-blocks/${protocolElementBlockId}/text`,
          { method: "PUT", body: JSON.stringify({ content }) }
        );
        updateBlockInState(protocolElementBlockId, (block) => ({
          ...block,
          text_content: content,
          tracked_dirty: result.tracked_dirty,
          tracked_baseline_content: result.tracked_baseline_content,
        }));
        setStatus(protocolElementBlockId, "saved");
        collab.sendFieldUpdate(`block-${protocolElementBlockId}`, {
          text_content: content,
          tracked_dirty: result.tracked_dirty,
          tracked_baseline_content: result.tracked_baseline_content,
        });
      } catch (err: unknown) {
        setStatus(protocolElementBlockId, "error");
        showToast(err instanceof Error ? err.message : "Text konnte nicht gespeichert werden", "error");
      }
    }, 700);
  }

  // "Ausblenden" for a text block's red tracked-change highlight (whole block at once -
  // see AutosaveService.accept_tracked_changes for why not per-word).
  async function acceptTextTrackedChanges(protocolElementBlockId: number) {
    try {
      const result = await browserApiFetch<{ tracked_dirty: boolean; tracked_baseline_content: string | null }>(
        `/api/protocol-element-blocks/${protocolElementBlockId}/text/accept-tracked-changes`,
        { method: "POST" }
      );
      updateBlockInState(protocolElementBlockId, (block) => ({
        ...block,
        tracked_dirty: result.tracked_dirty,
        tracked_baseline_content: result.tracked_baseline_content,
      }));
      collab.sendFieldUpdate(`block-${protocolElementBlockId}`, {
        tracked_dirty: result.tracked_dirty,
        tracked_baseline_content: result.tracked_baseline_content,
      });
    } catch (err: unknown) {
      if (err instanceof Error) showToast(err.message);
    }
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
      const next = [...(todosByBlock[protocolElementBlockId] ?? []), created].sort((left, right) => left.sort_index - right.sort_index);
      setTodosByBlock((current) => ({ ...current, [protocolElementBlockId]: next }));
      collab.sendFieldUpdate(`block-${protocolElementBlockId}-todos`, next);
      setNewTodoTask((current) => ({ ...current, [protocolElementBlockId]: "" }));
      setNewTodoTags((current) => ({ ...current, [protocolElementBlockId]: "" }));
      setStatus(protocolElementBlockId, "saved");
    } catch (err: unknown) {
      setStatus(protocolElementBlockId, "error");
      showToast(err instanceof Error ? err.message : "Todo konnte nicht erstellt werden", "error");
    }
  }

  async function updateTodo(protocolElementBlockId: number, todoId: number, patch: Partial<ProtocolTodo>) {
    setStatus(protocolElementBlockId, "saving");
    try {
      const updated = await browserApiFetch<ProtocolTodo>(`/api/protocol-todos/${todoId}`, {
        method: "PATCH",
        body: JSON.stringify(patch)
      });
      const next = (todosByBlock[protocolElementBlockId] ?? []).map((todo) => (todo.id === todoId ? updated : todo));
      setTodosByBlock((current) => ({ ...current, [protocolElementBlockId]: next }));
      collab.sendFieldUpdate(`block-${protocolElementBlockId}-todos`, next);
      setStatus(protocolElementBlockId, "saved");
    } catch (err: unknown) {
      setStatus(protocolElementBlockId, "error");
      showToast(err instanceof Error ? err.message : "Todo konnte nicht gespeichert werden", "error");
    }
  }

  async function deleteTodo(protocolElementBlockId: number, todoId: number) {
    const ok = await confirm({
      message: "Todo endgültig löschen? Dies kann nicht rückgängig gemacht werden.",
      tone: "danger",
      confirmLabel: "Löschen"
    });
    if (!ok) return;
    setStatus(protocolElementBlockId, "saving");
    try {
      await browserApiFetch(`/api/protocol-todos/${todoId}`, { method: "DELETE" });
      const next = (todosByBlock[protocolElementBlockId] ?? []).filter((todo) => todo.id !== todoId);
      setTodosByBlock((current) => ({ ...current, [protocolElementBlockId]: next }));
      collab.sendFieldUpdate(`block-${protocolElementBlockId}-todos`, next);
      setStatus(protocolElementBlockId, "saved");
    } catch (err: unknown) {
      setStatus(protocolElementBlockId, "error");
      showToast(err instanceof Error ? err.message : "Todo konnte nicht gelöscht werden", "error");
    }
  }

  // "Ausblenden" on a todo's red tracked-change highlight: keeps the todo, just stops
  // marking it as changed/added/pending-delete. A pending-delete ghost is hard-deleted
  // server-side, so it disappears from the list entirely.
  async function acceptTodoTrackedChange(protocolElementBlockId: number, todoId: number) {
    try {
      const result = await browserApiFetch<{ todo: ProtocolTodo | null }>(
        `/api/protocol-todos/${todoId}/accept-tracked-change`,
        { method: "POST" }
      );
      setTodosByBlock((current) => ({
        ...current,
        [protocolElementBlockId]: result.todo
          ? (current[protocolElementBlockId] ?? []).map((todo) => (todo.id === todoId ? result.todo! : todo))
          : (current[protocolElementBlockId] ?? []).filter((todo) => todo.id !== todoId),
      }));
    } catch (err: unknown) {
      if (err instanceof Error) showToast(err.message);
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
      const next = [...(imagesByBlock[protocolElementBlockId] ?? []), created].sort((left, right) => left.sort_index - right.sort_index);
      setImagesByBlock((current) => ({ ...current, [protocolElementBlockId]: next }));
      collab.sendFieldUpdate(`block-${protocolElementBlockId}-images`, next);
      setSelectedFiles((current) => ({ ...current, [protocolElementBlockId]: null }));
      setStatus(protocolElementBlockId, "saved");
    } catch (err: unknown) {
      setStatus(protocolElementBlockId, "error");
      showToast(err instanceof Error ? err.message : "Bild konnte nicht hochgeladen werden", "error");
    }
  }

  async function deleteImage(protocolElementBlockId: number, imageId: number) {
    const ok = await confirm({
      message: "Bild endgültig löschen? Dies kann nicht rückgängig gemacht werden.",
      tone: "danger",
      confirmLabel: "Löschen"
    });
    if (!ok) return;
    setStatus(protocolElementBlockId, "saving");
    try {
      await browserApiFetch(`/api/protocol-images/${imageId}`, { method: "DELETE" });
      const next = (imagesByBlock[protocolElementBlockId] ?? []).filter((image) => image.id !== imageId);
      setImagesByBlock((current) => ({ ...current, [protocolElementBlockId]: next }));
      collab.sendFieldUpdate(`block-${protocolElementBlockId}-images`, next);
      setStatus(protocolElementBlockId, "saved");
    } catch (err: unknown) {
      setStatus(protocolElementBlockId, "error");
      showToast(err instanceof Error ? err.message : "Bild konnte nicht gelöscht werden", "error");
    }
  }

  async function createEventFromBlock(protocolElementBlockId: number, blockConfig: Record<string, any>, draftOverride?: ProtocolEventDraft): Promise<EventSummary | null> {
    const configuredTag = String(blockConfig.event_tag_filter ?? "").trim();
    const allowEndDate = blockConfig.event_allow_end_date === true;
    const draft = draftOverride ?? newEventDrafts[protocolElementBlockId] ?? createProtocolEventDraft(protocol.protocol_date, configuredTag);
    if (!draft.event_date.trim() || !draft.title.trim()) {
      setStatus(protocolElementBlockId, "error");
      return null;
    }
    setStatus(protocolElementBlockId, "saving");
    const cycleAssignments: { cycle_config_id: number; cycle_year: number }[] = [];
    if (currentCycleYear !== null && currentTemplate?.cycle_config_id && currentTemplate.cycle_config) {
      cycleAssignments.push({ cycle_config_id: currentTemplate.cycle_config_id, cycle_year: currentCycleYear });
      const eventCycleYear = draft.event_date
        ? getCycleYear(draft.event_date, currentTemplate.cycle_config.reset_month, currentTemplate.cycle_config.reset_day)
        : null;
      if (eventCycleYear !== null && eventCycleYear !== currentCycleYear) {
        cycleAssignments.push({ cycle_config_id: currentTemplate.cycle_config_id, cycle_year: eventCycleYear });
      }
    }
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
          cycle_assignments: cycleAssignments,
        }),
      });
      setEvents((current) => [...current, created]);
      collab.sendFieldUpdate("event-created", created);
      if (!draftOverride) {
        setNewEventDrafts((current) => ({
          ...current,
          [protocolElementBlockId]: createProtocolEventDraft(protocol.protocol_date, configuredTag),
        }));
      }
      setStatus(protocolElementBlockId, "saved");
      return created;
    } catch (err: unknown) {
      setStatus(protocolElementBlockId, "error");
      showToast(err instanceof Error ? err.message : "Termin konnte nicht erstellt werden", "error");
      return null;
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
      collab.sendFieldUpdate("event-updated", updated);
      setStatus(protocolElementBlockId, "saved");
      return true;
    } catch (err: unknown) {
      setStatus(protocolElementBlockId, "error");
      showToast(err instanceof Error ? err.message : "Termin konnte nicht gespeichert werden", "error");
      return false;
    }
  }

  async function deleteEventFromBlock(protocolElementBlockId: number, eventId: number) {
    setStatus(protocolElementBlockId, "saving");
    try {
      await browserApiFetch(`/api/events/${eventId}`, { method: "DELETE" });
      setEvents((current) => current.filter((event) => event.id !== eventId));
      collab.sendFieldUpdate("event-deleted", { id: eventId });
      setStatus(protocolElementBlockId, "saved");
    } catch (err: unknown) {
      setStatus(protocolElementBlockId, "error");
      showToast(err instanceof Error ? err.message : "Termin konnte nicht gelöscht werden", "error");
    }
  }

  function openEventContextMenu(nativeEvent: React.MouseEvent, eventRow: EventSummary, protocolElementBlockId: number) {
    nativeEvent.preventDefault();
    nativeEvent.stopPropagation();
    setEventContextMenu({ x: nativeEvent.clientX, y: nativeEvent.clientY, eventRow, blockId: protocolElementBlockId });
  }

  async function toggleEventCancelledFromContextMenu() {
    if (!eventContextMenu) return;
    const { eventRow, blockId } = eventContextMenu;
    setEventContextMenu(null);
    await updateEventFromBlock(blockId, eventRow.id, { is_cancelled: !eventRow.is_cancelled });
  }

  // Manual "Daten aktualisieren" click: pulls in the list's current data, keeps the
  // block's previous snapshot as the one undo step.
  //
  // Only configuration_snapshot_json is merged from the response, never the whole
  // object - _block_to_read() on the backend always returns element_type_code/
  // render_type_code/text_content/display_compiled_text as null/empty placeholders
  // (it's meant to be patched into existing block state, not replace it wholesale).
  // saveBlockConfiguration() above already follows this same rule; an earlier version
  // of these three handlers spread the whole response and nulled out element_type_code,
  // which made the block fall back to an "unknown" type and stop rendering its content
  // at all - found via Timo's own browser test.
  async function refreshBlockListSnapshot(blockId: number) {
    try {
      const updated = await browserApiFetch<ProtocolElement["blocks"][number]>(
        `/api/protocol-element-blocks/${blockId}/list-snapshot/refresh`,
        { method: "POST" }
      );
      updateBlockInState(blockId, (block) => ({ ...block, configuration_snapshot_json: updated.configuration_snapshot_json }));
      void refreshElementTitles();
      collab.sendFieldUpdate("element-titles", null);
    } catch (err: unknown) {
      if (err instanceof Error) showToast(err.message);
    }
  }

  async function undoBlockListSnapshot(blockId: number) {
    try {
      const updated = await browserApiFetch<ProtocolElement["blocks"][number]>(
        `/api/protocol-element-blocks/${blockId}/list-snapshot/undo`,
        { method: "POST" }
      );
      updateBlockInState(blockId, (block) => ({ ...block, configuration_snapshot_json: updated.configuration_snapshot_json }));
      void refreshElementTitles();
      collab.sendFieldUpdate("element-titles", null);
    } catch (err: unknown) {
      if (err instanceof Error) showToast(err.message);
    }
  }

  // "Ausblenden" on one whole-list entry's or row-link row's red tracked-change highlight.
  async function acceptTrackedListEntry(blockId: number, entryId: number) {
    try {
      const updated = await browserApiFetch<ProtocolElement["blocks"][number]>(
        `/api/protocol-element-blocks/${blockId}/list-snapshot/entries/${entryId}/accept-tracked-change`,
        { method: "POST" }
      );
      updateBlockInState(blockId, (block) => ({ ...block, configuration_snapshot_json: updated.configuration_snapshot_json }));
    } catch (err: unknown) {
      if (err instanceof Error) showToast(err.message);
    }
  }

  async function acceptTrackedRow(blockId: number, rowId: string) {
    try {
      const updated = await browserApiFetch<ProtocolElement["blocks"][number]>(
        `/api/protocol-element-blocks/${blockId}/rows/${rowId}/accept-tracked-change`,
        { method: "POST" }
      );
      updateBlockInState(blockId, (block) => ({ ...block, configuration_snapshot_json: updated.configuration_snapshot_json }));
    } catch (err: unknown) {
      if (err instanceof Error) showToast(err.message);
    }
  }

  // Silent resync called right after this protocol itself writes to a linked list entry
  // (see createListEntryFromBlock/updateListEntryFromBlock/deleteListEntryFromBlock below),
  // so the editor never shows a stale hint for a change it just made itself. Best-effort:
  // a failure here just leaves a stale badge until the next sync/manual refresh, never
  // corrupts data.
  async function syncBlockListSnapshot(blockId: number) {
    try {
      const updated = await browserApiFetch<ProtocolElement["blocks"][number]>(
        `/api/protocol-element-blocks/${blockId}/list-snapshot/sync`,
        { method: "POST" }
      );
      updateBlockInState(blockId, (block) => ({ ...block, configuration_snapshot_json: updated.configuration_snapshot_json }));
      void refreshElementTitles();
      collab.sendFieldUpdate("element-titles", null);
    } catch {
      // best-effort, see comment above
    }
  }

  // Only meaningful while protocolStatus === "geplant" - turning it off doesn't
  // retroactively unmark anything already tracked, it just stops new edits from being
  // marked going forward (see backend gating in the text/todo/list-sync routes).
  async function setTrackChangesEnabled(enabled: boolean) {
    setTrackChangesEnabledState(enabled);
    try {
      await browserApiFetch(`/api/protocols/${protocol.id}`, {
        method: "PATCH",
        body: JSON.stringify({ track_changes_enabled: enabled }),
      });
      collab.sendFieldUpdate("track-changes-toggle", { enabled });
    } catch (err: unknown) {
      setTrackChangesEnabledState(!enabled);
      if (err instanceof Error) showToast(err.message);
    }
  }

  // The "Liste bearbeiten" planning popup intentionally manages the live list directly
  // (not the protocol's frozen snapshot) - but listEntriesByDefinition is otherwise only
  // ever populated once at page load and patched locally by this protocol's own writes,
  // so it goes stale the moment the list changes through any other route (another tab,
  // another protocol, or this block's own "Daten aktualisieren"). Refetch right before
  // opening the popup so it always starts from the real current list state.
  async function refreshListEntries(listDefinitionId: number) {
    try {
      const fresh = await browserApiFetch<StructuredListEntry[]>(`/api/lists/${listDefinitionId}/entries`);
      setListEntriesByDefinition((current) => ({ ...current, [listDefinitionId]: fresh }));
    } catch {
      // best-effort - popup falls back to whatever was cached
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
      void syncBlockListSnapshot(protocolElementBlockId);
      return true;
    } catch (err: unknown) {
      setStatus(protocolElementBlockId, "error");
      showToast(err instanceof Error ? err.message : "Eintrag konnte nicht erstellt werden", "error");
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
      void syncBlockListSnapshot(protocolElementBlockId);
      return true;
    } catch (err: unknown) {
      setStatus(protocolElementBlockId, "error");
      showToast(err instanceof Error ? err.message : "Eintrag konnte nicht gespeichert werden", "error");
      return false;
    }
  }

  async function deleteListEntryFromBlock(protocolElementBlockId: number, listDefinitionId: number, entryId: number) {
    const ok = await confirm({
      message: "Eintrag endgültig löschen? Dies kann nicht rückgängig gemacht werden.",
      tone: "danger",
      confirmLabel: "Löschen"
    });
    if (!ok) return;
    setStatus(protocolElementBlockId, "saving");
    try {
      await browserApiFetch(`/api/list-entries/${entryId}`, { method: "DELETE" });
      setListEntriesByDefinition((current) => ({
        ...current,
        [listDefinitionId]: (current[listDefinitionId] ?? []).filter((entry) => entry.id !== entryId),
      }));
      setStatus(protocolElementBlockId, "saved");
      void syncBlockListSnapshot(protocolElementBlockId);
    } catch (err: unknown) {
      setStatus(protocolElementBlockId, "error");
      showToast(err instanceof Error ? err.message : "Eintrag konnte nicht gelöscht werden", "error");
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
    } catch (err: unknown) {
      updateBlockInState(blockId, (b) => ({ ...b, is_visible_snapshot: false, configuration_snapshot_json: block.configuration_snapshot_json }));
      showToast(err instanceof Error ? err.message : "Termin konnte nicht eingeblendet werden", "error");
    }
  }

  async function removeEventBlock(blockId: number) {
    // Optimistic removal, rolled back on failure by re-inserting the removed block into its
    // original element at its original position - mirrors the rollback pattern used for todo
    // updates in todos/todo-list-view.tsx.
    let removedFrom: { elementId: number; block: ProtocolElement["blocks"][number]; index: number } | null = null;
    setElements((current) =>
      current.map((element) => {
        const index = element.blocks.findIndex((b) => b.id === blockId);
        if (index === -1) return element;
        removedFrom = { elementId: element.id, block: element.blocks[index], index };
        return { ...element, blocks: element.blocks.filter((b) => b.id !== blockId) };
      })
    );
    try {
      await browserApiFetch(`/api/protocol-element-blocks/${blockId}`, { method: "DELETE" });
    } catch (err: unknown) {
      if (removedFrom) {
        const { elementId, block, index } = removedFrom;
        setElements((current) =>
          current.map((element) => {
            if (element.id !== elementId) return element;
            const blocks = [...element.blocks];
            blocks.splice(Math.min(index, blocks.length), 0, block);
            return { ...element, blocks };
          })
        );
      }
      showToast(err instanceof Error ? err.message : "Termin konnte nicht entfernt werden", "error");
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
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Termin konnte nicht hinzugefügt werden", "error");
      return null;
    }
  }

  return (
    <div className="grid" ref={editorRef}>
      {useDocumentLayout && (
        <div className="protocol-document-header">
          <a href="/protocols" className="button-inline protocol-document-back">← Zurück zu Protokollen</a>
          <Badge variant={protocolStatusVariant(protocolStatus)} className="protocol-document-badge">
            {protocolStatusLabel(protocolStatus)}
          </Badge>
          <h1 className="protocol-document-title">{protocol.title || protocol.protocol_number}</h1>
          <div className="protocol-document-actions">
            <button
              type="button"
              className="button-ghost"
              disabled={pdfBusyByProtocol[protocol.id]}
              onClick={() => openOrGeneratePdf(protocol)}
            >
              {pdfBusyByProtocol[protocol.id] ? "…" : "PDF exportieren"}
            </button>
            {!isReadOnly && workflowMeta[protocolStatus]?.ctaLabel && (
              <button
                type="button"
                className="button-primary"
                disabled={transitioningStatus}
                onClick={transitionStatus}
              >
                {transitioningStatus ? "…" : workflowMeta[protocolStatus]?.ctaLabel}
              </button>
            )}
          </div>
        </div>
      )}

      <div className="status-row">
        <span className="pill">{protocol.protocol_number}</span>
        <span className="pill">{workflowMeta[protocolStatus]?.modeLabel ?? protocolStatusLabel(protocolStatus)}</span>
        {protocol.import_source_url && (
          <a
            className="pill"
            href={protocol.import_source_url}
            title={protocol.import_source_filename ?? undefined}
          >
            Original-Dokument öffnen
          </a>
        )}
        {protocolStatus === "geplant" && !isReadOnly && (
          <TodoMiniMenu label={trackChangesEnabled ? "Änderungen nachverfolgen: An" : "Änderungen nachverfolgen: Aus"} compact>
            {(close) => (
              <>
                <TodoMenuOption label="An" active={trackChangesEnabled} onClick={() => { void setTrackChangesEnabled(true); close(); }} />
                <TodoMenuOption label="Aus" active={!trackChangesEnabled} onClick={() => { void setTrackChangesEnabled(false); close(); }} />
              </>
            )}
          </TodoMiniMenu>
        )}
        <CollaborationPresenceBar users={collab.otherPresence} connected={collab.connected} />
      </div>

      <Modal
        open={showStatusChangeWarning}
        title="Andere Person bearbeitet gerade"
        description="Mindestens eine andere Person bearbeitet dieses Protokoll gerade aktiv. Der Statuswechsel wird für alle sofort übernommen."
        onClose={() => setShowStatusChangeWarning(false)}
      >
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={() => setShowStatusChangeWarning(false)}>
            Abbrechen
          </button>
          <button
            type="button"
            className="button-primary"
            onClick={() => {
              setShowStatusChangeWarning(false);
              void performStatusTransition();
            }}
          >
            Trotzdem wechseln
          </button>
        </div>
      </Modal>

      {showSavedIndicator && <div className="save-indicator">✓ Gespeichert</div>}

      {useDocumentLayout ? (
        <div className="protocol-document-shell">
          <article className="protocol-document" ref={documentRef}>
            {visibleElements.length === 0 && (
              <div className="editor-panel-empty">
                <div>
                  <div className="eyebrow">Keine Punkte</div>
                  <h3>Dieses Protokoll hat noch keine sichtbaren Abschnitte</h3>
                </div>
              </div>
            )}
            {visibleElements.map((element, index) => (
              <div
                key={element.id}
                className="protocol-doc-section-wrap"
                onClick={selectedElementId === element.id ? undefined : () => focusElement(element.id)}
              >
              <FocusedElementEditor
                isActive={selectedElementId === element.id}
                tagConfig={tagConfig}
                updateTagColor={updateTagColor}
                renameTag={renameTag}
                collab={collab}
                trackChangesActive={trackChangesActive}
                element={element}
                elementIndex={index}
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
                acceptTodoTrackedChange={acceptTodoTrackedChange}
                acceptTrackedListEntry={acceptTrackedListEntry}
                acceptTrackedRow={acceptTrackedRow}
                acceptTextTrackedChanges={acceptTextTrackedChanges}
                createEventFromBlock={createEventFromBlock}
                updateEventFromBlock={updateEventFromBlock}
                deleteEventFromBlock={deleteEventFromBlock}
                onEventContextMenu={openEventContextMenu}
                uploadImage={uploadImage}
                deleteImage={deleteImage}
                listDefinitionsById={listDefinitionsById}
                listEntriesByDefinition={listEntriesByDefinition}
                createListEntryFromBlock={createListEntryFromBlock}
                updateListEntryFromBlock={updateListEntryFromBlock}
                deleteListEntryFromBlock={deleteListEntryFromBlock}
                refreshBlockListSnapshot={refreshBlockListSnapshot}
                refreshListEntries={refreshListEntries}
                undoBlockListSnapshot={undoBlockListSnapshot}
                todoTagFilter={todoTagFilter}
                setTodoTagFilter={setTodoTagFilter}
                newTodoTags={newTodoTags}
                setNewTodoTags={setNewTodoTags}
                isPlanningMode={isPlanningMode}
                unhideEventBlock={unhideEventBlock}
                removeEventBlock={removeEventBlock}
                addEventBlockToElement={addEventBlockToElement}
                onQuickTodoCreated={handleQuickTodoCreated}
                pendingTodos={pendingTodos}
                onPendingUpdate={(updated) => setPendingTodos((prev) => prev.map((t) => t.id === updated.id ? { ...t, ...updated } : t))}
                onPendingDone={(todoId) => setPendingTodos((prev) => prev.filter((t) => t.id !== todoId))}
                documentTemplates={documentTemplates}
              />
              </div>
            ))}
          </article>

          <aside className="protocol-quicknav" ref={navRef}>
            <div className="card protocol-quicknav-section">
              <div className="eyebrow">Schnellzugriff</div>
              <nav className="protocol-quicknav-list">
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
                      className={`protocol-quicknav-item${selectedElementId === element.id ? " protocol-quicknav-item-active" : ""}`}
                      onClick={() => focusElement(element.id)}
                      title={element.section_name_snapshot}
                    >
                      <span className="protocol-quicknav-icon-badge"><NavIcon name={sectionIconKey(element)} /></span>
                      <span className="protocol-quicknav-item-label">{element.section_name_snapshot}</span>
                    </button>
                  </div>
                ))}
              </nav>
            </div>

            {attendanceTally && (
              <div className="card protocol-quicknav-attendance">
                <div className="eyebrow">Anwesenheit</div>
                <div className="protocol-quicknav-stat-row">
                  <span>Anwesend</span>
                  <strong>{attendanceTally.present}</strong>
                </div>
                <div className="protocol-quicknav-stat-row">
                  <span>Entschuldigt</span>
                  <strong>{attendanceTally.excused}</strong>
                </div>
                <div className="protocol-quicknav-stat-row protocol-quicknav-stat-danger">
                  <span>Unentschuldigt</span>
                  <strong>{attendanceTally.absent}</strong>
                </div>
              </div>
            )}

            {!isReadOnly && <p className="protocol-quicknav-autosave muted">Änderungen werden automatisch gespeichert.</p>}
          </aside>
        </div>
      ) : (
      <>
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
                tabIndex={-1}
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
              tagConfig={tagConfig}
              updateTagColor={updateTagColor}
              renameTag={renameTag}
              collab={collab}
              trackChangesActive={trackChangesActive}
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
              acceptTodoTrackedChange={acceptTodoTrackedChange}
              acceptTrackedListEntry={acceptTrackedListEntry}
              acceptTrackedRow={acceptTrackedRow}
              acceptTextTrackedChanges={acceptTextTrackedChanges}
              createEventFromBlock={createEventFromBlock}
              updateEventFromBlock={updateEventFromBlock}
              deleteEventFromBlock={deleteEventFromBlock}
              onEventContextMenu={openEventContextMenu}
              uploadImage={uploadImage}
              deleteImage={deleteImage}
              listDefinitionsById={listDefinitionsById}
              listEntriesByDefinition={listEntriesByDefinition}
              createListEntryFromBlock={createListEntryFromBlock}
              updateListEntryFromBlock={updateListEntryFromBlock}
              deleteListEntryFromBlock={deleteListEntryFromBlock}
              refreshBlockListSnapshot={refreshBlockListSnapshot}
              refreshListEntries={refreshListEntries}
              undoBlockListSnapshot={undoBlockListSnapshot}
              todoTagFilter={todoTagFilter}
              setTodoTagFilter={setTodoTagFilter}
              newTodoTags={newTodoTags}
              setNewTodoTags={setNewTodoTags}
              isPlanningMode={isPlanningMode}
              unhideEventBlock={unhideEventBlock}
              removeEventBlock={removeEventBlock}
              addEventBlockToElement={addEventBlockToElement}
              onQuickTodoCreated={handleQuickTodoCreated}
              pendingTodos={pendingTodos}
              onPendingUpdate={(updated) => setPendingTodos((prev) => prev.map((t) => t.id === updated.id ? { ...t, ...updated } : t))}
              onPendingDone={(todoId) => setPendingTodos((prev) => prev.filter((t) => t.id !== todoId))}
              documentTemplates={documentTemplates}
            />
          ) : (
            <div className="editor-panel-empty">
              <div>
                <div className="eyebrow">Kein Punkt ausgewählt</div>
                <h3>Wähle einen Punkt aus dem Navigator</h3>
                <p>Jeder Punkt gruppiert alle Blöcke eines Elements, sodass Text, Todos und Bilder zusammenbleiben.</p>
              </div>
            </div>
          )}
        </article>
      </div>


      <div className="editor-fixed-actions">
        {!isReadOnly && selectedElementIndex >= 0 && selectedElementIndex < visibleElements.length - 1 ? (
          <>
            <button type="button" className="button-ghost editor-fixed-actions-close" onClick={closeProtocol}>
              Schliessen
            </button>
            <button
              type="button"
              className="button-primary"
              data-editor-primary-action
              onClick={() => {
                const nextElement = visibleElements[selectedElementIndex + 1];
                if (nextElement) focusElement(nextElement.id);
              }}
              onKeyDown={(e) => {
                if (e.key !== "Tab") return;
                const inputs = document.querySelectorAll<HTMLElement>("[data-form-input]");
                if (!inputs.length) return;
                e.preventDefault();
                if (e.shiftKey) {
                  inputs[inputs.length - 1].focus();
                } else {
                  inputs[0].focus();
                }
              }}
            >
              Weiter →
            </button>
          </>
        ) : !isReadOnly && workflowMeta[protocolStatus]?.ctaLabel ? (
          <>
            <button type="button" className="button-ghost editor-fixed-actions-close" onClick={closeProtocol}>
              Schliessen
            </button>
            <button
              type="button"
              className="button-primary"
              data-editor-primary-action
              disabled={transitioningStatus}
              onClick={transitionStatus}
            >
              {transitioningStatus ? "…" : workflowMeta[protocolStatus]?.ctaLabel}
            </button>
          </>
        ) : (
          <a href="/protocols" className="button-inline">← Zurück zu den Protokollen</a>
        )}
      </div>
      </>
      )}

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

      {protocolStatus === "vorbereitet" && !forceReadOnly && (
        <>
          <QuickActionsPill
            onNotesClick={() => { setCollabStatusPanelOpen(false); sessionPanelRef.current?.openAndFocusNotes(); }}
            onTodosClick={() => { setCollabStatusPanelOpen(false); sessionPanelRef.current?.openAndFocusTodo(); }}
            onCollabClick={() => { sessionPanelRef.current?.close(); setCollabStatusPanelOpen(true); }}
          />
          <CollaborationStatusPanel
            open={collabStatusPanelOpen}
            onClose={() => setCollabStatusPanelOpen(false)}
            protocolNumber={protocol.protocol_number}
            modeLabel={workflowMeta[protocolStatus]?.modeLabel ?? protocolStatusLabel(protocolStatus)}
            attendanceTally={attendanceTally}
            attendanceRoster={attendanceRoster}
            otherPresence={collab.otherPresence}
            connected={collab.connected}
            ctaLabel={!isReadOnly ? workflowMeta[protocolStatus]?.ctaLabel : undefined}
            onCta={() => {
              setCollabStatusPanelOpen(false);
              transitionStatus();
            }}
            ctaBusy={transitioningStatus}
          />
        </>
      )}

      {eventContextMenu && typeof document !== "undefined" && createPortal(
        <div
          ref={eventContextMenuRef}
          id="event-context-menu-portal"
          className="mini-menu-popover-portal"
          style={computePopoverPosition(new DOMRect(eventContextMenu.x, eventContextMenu.y, 0, 0), "start", 6, { minWidth: 220, estimatedHeight: 80 })}
          role="menu"
        >
          <button type="button" className="mini-menu-option" onClick={() => void toggleEventCancelledFromContextMenu()}>
            {eventContextMenu.eventRow.is_cancelled ? "Absage aufheben" : "Als abgesagt markieren"}
          </button>
        </div>,
        document.body
      )}
    </div>
  );
}
