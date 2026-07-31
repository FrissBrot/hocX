"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { useToast } from "@/contexts/toast-context";

import { SessionPanel, SessionPanelHandle } from "@/components/protocol/session-panel";
import { Modal } from "@/components/ui/modal";
import { bumpStatsCharts } from "@/components/protocol/chart-block";
import { CollaborationPresenceBar } from "@/components/protocol/collaboration-presence";
import { useProtocolCollaboration } from "@/lib/hooks/use-protocol-collaboration";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
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
import {
  ProtocolEventDraft,
  TODO_STATUS,
  createProtocolEventDraft,
  protocolStatusLabel,
  resequenceProtocolElements,
  smartPopoverStyle,
  trimSectionName,
  visibleBlockTitle,
} from "@/components/protocol/protocol-editor-shared";
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

  useEffect(() => {
    if (!eventContextMenu) return;
    function onPointerDown(nativeEvent: MouseEvent) {
      const target = nativeEvent.target as Node;
      if (!document.getElementById("event-context-menu-portal")?.contains(target)) {
        setEventContextMenu(null);
      }
    }
    function onKeyDown(nativeEvent: KeyboardEvent) {
      if (nativeEvent.key === "Escape") setEventContextMenu(null);
    }
    function onScroll() {
      setEventContextMenu(null);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("scroll", onScroll, true);
    };
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
  const [sessionNotes, setSessionNotes] = useState(protocol.session_notes ?? "");
  const [transitioningStatus, setTransitioningStatus] = useState(false);
  const showToast = useToast();
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
        if (!field_key.startsWith("block-")) return;
        const blockId = Number(field_key.slice("block-".length).split("-cell-")[0]);
        if (!Number.isFinite(blockId) || !patch || typeof patch !== "object") return;
        updateBlockInState(blockId, (block) => ({ ...block, ...(patch as Partial<typeof block>) }));
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
          '[data-form-input], textarea:not([readonly]), input:not([readonly]):not([type="file"])'
        );
        firstEditable?.focus();
      }, 120);
    });
  }, [selectedElementId]);

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
        collab.sendFieldUpdate(`block-${protocolElementBlockId}`, { text_content: content });
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
      if (!draftOverride) {
        setNewEventDrafts((current) => ({
          ...current,
          [protocolElementBlockId]: createProtocolEventDraft(protocol.protocol_date, configuredTag),
        }));
      }
      setStatus(protocolElementBlockId, "saved");
      return created;
    } catch {
      setStatus(protocolElementBlockId, "error");
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
      void syncBlockListSnapshot(protocolElementBlockId);
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
      void syncBlockListSnapshot(protocolElementBlockId);
    } catch {
      setStatus(protocolElementBlockId, "error");
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
              collab={collab}
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
                <div className="eyebrow">No point selected</div>
                <h3>Choose a point from the navigator</h3>
                <p>Each point groups all blocks from one element, so text, todos and images stay together.</p>
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

      {eventContextMenu && typeof document !== "undefined" && createPortal(
        <div
          id="event-context-menu-portal"
          className="mini-menu-popover-portal"
          style={smartPopoverStyle(new DOMRect(eventContextMenu.x, eventContextMenu.y, 0, 0), 220, "start", 80)}
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
