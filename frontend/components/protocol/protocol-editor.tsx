"use client";

import { useShortcut } from "@/lib/keyboard/use-shortcut";
import { announce } from "@/lib/a11y/announce";
import { eventFilterTagText, normalizeEventFilter } from "@/lib/element-types/event-filter";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { runSerializedByKey } from "@/lib/utils/serialize-by-key";
import { mergeEventPatches } from "@/lib/utils/event-patch";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";

import { ParticipantDateContext } from "@/contexts/participant-date-context";
import { ParticipantDirectoryContext } from "@/contexts/participant-directory-context";
import { SessionPanel, SessionPanelHandle } from "@/components/protocol/session-panel";
import type { QuickTodoFineAccess } from "@/components/protocol/quick-todo-fine";
import { useCreateSubmissionFromTodo } from "@/components/todos/use-create-submission-from-todo";
import { Modal } from "@/components/ui/modal";
import { ProtocolOutline, type OutlineItem } from "@/components/protocol/protocol-outline";
import { DRAWER_SHORTCUTS, ProtocolDock, ProtocolDrawer, type DrawerId } from "@/components/protocol/protocol-dock";
import { ProtocolStatusDrawer } from "@/components/protocol/protocol-status-drawer";
import { ATTENDANCE_SEARCH_ATTR } from "@/components/protocol/attendance-board";
import { bumpStatsCharts, startFreshStatsVersion } from "@/components/protocol/chart-block";
import { CollaborationPresenceBar } from "@/components/protocol/collaboration-presence";
import { StatusTransitionDialog } from "@/components/protocol/status-transition-dialog";
import { ProtocolHeader, type ProtocolSaveState } from "@/components/protocol/protocol-header";
import { computePopoverPosition, usePopoverDismiss } from "@/components/ui/popover";
import { useProtocolCollaboration } from "@/lib/hooks/use-protocol-collaboration";
import { useTagConfig } from "@/lib/hooks/use-tag-config";
import { useStableCallbacks } from "@/lib/hooks/use-stable-callbacks";
import { usePdfExport } from "@/lib/hooks/use-pdf-export";
import { ApiError, browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { isAlreadyUploadedLazy } from "@/lib/image-analysis/precheck-lazy";
import { clearDraft, discardMutation, getOfflineServerSnapshot, getOfflineSnapshot, queueMutation, readDraft, removeMutation, saveDraft, subscribeOfflineStore } from "@/lib/offline-store";
import { getCycleYear } from "@/lib/utils/cycle";
import { templateChangedSinceSync, useTemplateSync } from "@/components/protocol/use-template-sync";
import {
  AttendanceFine,
  AttendanceFineListItem,
  EventPatch,
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
  ListValues,
  StructuredListEntry,
  TemplateSummary,
  TodoListItem,
  ProtocolAgendaItem,
} from "@/types/api";
import {
  ProtocolEventDraft,
  TODO_STATUS,
  createProtocolEventDraft,
  protocolStatusLabel,
  resequenceProtocolElements,
  outlineSummary,
  attendanceParticipants,
  imageSimilarityNotice,
  trimSectionName,
  visibleAttendanceTally,
} from "@/components/protocol/protocol-editor-shared";
import { FocusedElementEditor } from "@/components/protocol/focused-element-editor";
import { pdfCoverageSignature, usePdfCoverage } from "@/components/protocol/use-pdf-coverage";
import { AgendaItemsSection } from "@/components/protocol/agenda-items-section";
import { AgendaQuickCreateForm } from "@/components/protocol/agenda-quick-create-form";
import { AgendaPostponeModal } from "@/components/agenda/agenda-item-modal";
import { ProtocolSearchModal } from "@/components/protocol/protocol-search";
import { createDebouncedSaveQueue } from "@/components/protocol/debounced-save-queue";
import { createTextDraftStore, decideDraftRestore, textDraftBaseKey, textDraftKey } from "@/components/protocol/text-drafts";
import { useTextDraftEmptiness } from "@/components/protocol/use-text-draft";
import { jumpToSection, prefersReducedMotion } from "@/components/protocol/document-scroll";
import { createSectionSpy, type SectionSpy } from "@/components/protocol/section-spy";
import { localIsoDate } from "@/lib/documents/todo-export-filter";
import { useCompleteEvents } from "@/lib/protocol/use-complete-events";

type ProtocolEditorProps = {
  protocol: ProtocolSummary;
  initialElements: ProtocolElement[];
  initialTodos: Record<string, ProtocolTodo[]>;
  initialImages: Record<string, ProtocolImage[]>;
  availableParticipants: ParticipantSummary[];
  participantDirectory?: ParticipantSummary[];
  availableEvents: EventSummary[];
  /** false: availableEvents enthält nur die für die Anzeige nötigen Termine, der Editor lädt den
   * Rest nach dem ersten Darstellen nach (lib/protocol/initial-editor-data.ts) */
  eventsComplete?: boolean;
  availableLists: StructuredListDefinition[];
  initialListEntries: Record<string, StructuredListEntry[]>;
  availableTemplates: TemplateSummary[];
  availableAccounts: FinanceAccount[];
  initialFinanceTransactions: Record<string, FinanceTransaction[]>;
  initialPendingTodos?: TodoListItem[];
  forceReadOnly?: boolean;
  canViewFines?: boolean;
  /** Transaktionen direkt im Block «Transaktionen» erfassen (finances.manage) */
  canManageFinances?: boolean;
  /** Pendenzen-Bussen in «Schnelle Pendenz» (Sitzungsmenü) */
  todoFines?: QuickTodoFineAccess;
  /** «Als Abgabe einsammeln» im Menü einer Pendenz (submissions.manage inkl. Modul Abgabebox, meetings.edit) */
  canCollectSubmissions?: boolean;
  /** Abgeschlossenes Protokoll zurücksetzen (meetings.approve) */
  canApprove?: boolean;
  // Vom Server mitgeladen (page.tsx), damit sie nicht erst nach der Hydration starten.
  // null/undefined: nicht mitgeladen (Fehler, fehlendes Recht) - der Editor lädt dann selbst.
  initialProtocolFines?: AttendanceFine[] | null;
  initialPendingFines?: AttendanceFineListItem[] | null;
  initialAgendaItems?: ProtocolAgendaItem[] | null;
  initialScrollPosition?: { element_id: string | null } | null;
};

const EMPTY_AGENDA_ITEMS: ProtocolAgendaItem[] = [];
const EMPTY_TODOS: ProtocolTodo[] = [];
const EMPTY_TEXT_DRAFTS: Record<string, string> = {};
/** Strg+Enter überspringt reine Anzeigen und die Sitzungsnotizen (die bearbeitet die Schublade). */
const NON_NAVIGABLE_BLOCK_TYPES = new Set(["session_notes", "display", "finance_balance", "chart"]);

/** Gleiche Einträge in gleicher Reihenfolge (Identität), für stabile abgeleitete Arrays. */
function sameItems<T>(left: readonly T[], right: readonly T[]) {
  return left === right || (left.length === right.length && left.every((item, index) => item === right[index]));
}

export function ProtocolEditor({
  protocol,
  initialElements,
  initialTodos,
  initialImages,
  availableParticipants,
  participantDirectory = [],
  availableEvents,
  eventsComplete = true,
  availableLists,
  initialListEntries,
  availableTemplates,
  availableAccounts,
  initialFinanceTransactions,
  initialPendingTodos = [],
  forceReadOnly = false,
  canViewFines = true,
  canManageFinances = false,
  todoFines,
  canCollectSubmissions = false,
  canApprove = false,
  initialProtocolFines,
  initialPendingFines,
  initialAgendaItems,
  initialScrollPosition,
}: ProtocolEditorProps) {
  const t = useTranslations("protocols.editor");
  const tRoot = useTranslations("protocols");
  const tAgenda = useTranslations("agenda");
  const tCommon = useTranslations("common");
  const tBuilder = useTranslations("protocols.builder");
  const router = useRouter();
  const [elements, setElements] = useState(initialElements);
  const [events, setEvents] = useState(availableEvents);
  useCompleteEvents(eventsComplete, setEvents);
  const [lists, setLists] = useState(availableLists);
  const [eventContextMenu, setEventContextMenu] = useState<{ x: number; y: number; eventRow: EventSummary; blockId: string } | null>(null);
  const eventContextMenuRef = useRef<HTMLDivElement | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);

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
  const [listEntriesByDefinition, setListEntriesByDefinition] = useState<Record<string, StructuredListEntry[]>>(initialListEntries);
  const [todosByBlock, setTodosByBlock] = useState<Record<string, ProtocolTodo[]>>(initialTodos);
  // Aktueller Stand für asynchrone Antworten: eine spät eintreffende Speicher-Antwort darf nicht
  // auf dem Stand vom Zeitpunkt des Aufrufs aufbauen (überschriebe neuere Änderungen).
  const todosByBlockRef = useRef(todosByBlock);
  todosByBlockRef.current = todosByBlock;
  const [pendingTodos, setPendingTodos] = useState<TodoListItem[]>(initialPendingTodos);
  const [imagesByBlock, setImagesByBlock] = useState<Record<string, ProtocolImage[]>>(initialImages);
  const [financeTransactions, setFinanceTransactions] = useState<Record<string, FinanceTransaction[]>>(initialFinanceTransactions);
  // Kontostände ändern sich mit Transaktionen, die im Protokoll erfasst werden
  const [accounts, setAccounts] = useState<FinanceAccount[]>(availableAccounts);
  const [financeVersion, setFinanceVersion] = useState(0);
  const [protocolFines, setProtocolFines] = useState<AttendanceFine[]>(initialProtocolFines ?? []);
  const [pendingFines, setPendingFines] = useState<AttendanceFineListItem[]>(initialPendingFines ?? []);
  // Beim Öffnen frisch gerechnete Statistik für die Diagramme - vor deren erstem Abruf. Früher
  // erledigte das bumpStatsCharts() im Mount-Effekt unten, nachdem die Diagramme schon geladen
  // hatten: jedes Diagramm lud dadurch doppelt (_t=0, _t=1).
  useState(() => { startFreshStatsVersion(); return null; });
  // Diagramme neu laden, wenn Bussen dazukommen oder wegfallen - nicht beim Öffnen und nicht beim
  // ersten Laden der Bussen (der Stand ist dann schon in der Statistik enthalten).
  const protocolFinesCountRef = useRef(protocolFines.length);
  useEffect(() => {
    if (protocolFinesCountRef.current === protocolFines.length) return;
    protocolFinesCountRef.current = protocolFines.length;
    bumpStatsCharts();
  }, [protocolFines.length]);
  // Getippter Text je Block ausserhalb des Editor-Zustands (T3, text-drafts.ts): eine Taste
  // rendert nur den Textblock neu, nicht den ganzen Editor.
  const [textDraftStore] = useState(() =>
    createTextDraftStore(
      Object.fromEntries(
        initialElements.flatMap((element) =>
          element.blocks
            .filter((block) => block.element_type_code === "text" || block.element_type_code === "static_text")
            .map((block) => [block.id, block.text_content ?? ""])
        )
      )
    )
  );
  const textDraftEmptiness = useTextDraftEmptiness(textDraftStore);
  const [newTodoTask, setNewTodoTask] = useState<Record<string, string>>({});
  const [newTodoTags, setNewTodoTags] = useState<Record<string, string>>({});
  const [todoTagFilter, setTodoTagFilter] = useState<Record<string, string | null>>({});
  const [newEventDrafts, setNewEventDrafts] = useState<Record<string, ProtocolEventDraft>>({});
  const [selectedFiles, setSelectedFiles] = useState<Record<string, File | null>>({});
  const [blockStatus, setBlockStatus] = useState<Record<string, SaveState>>({});
  // Vom Server mitgeladene Leseposition gleich als Start: der erste Scroll geht dann direkt dorthin
  const [selectedElementId, setSelectedElementId] = useState<string | null>(() => {
    const remembered = initialScrollPosition?.element_id;
    return remembered && initialElements.some((element) => element.id === remembered) ? remembered : initialElements[0]?.id ?? null;
  });
  // Aktiver Block (L4): nur dort hängt ein Editor; null = alles statisch. Mit Punkt, damit nur
  // dieser Punkt (memoisiert) neu rendert.
  const [activeBlock, setActiveBlock] = useState<{ elementId: string; blockId: string } | null>(null);
  // Zuletzt gespeicherte bzw. vom Server gelesene Leseposition: dieselbe nicht erneut speichern
  const savedScrollElementIdRef = useRef<string | null>(initialScrollPosition?.element_id ?? null);
  const [protocolStatus, setProtocolStatus] = useState(protocol.status);
  const [trackChangesEnabled, setTrackChangesEnabledState] = useState(protocol.track_changes_enabled ?? false);
  // Tracking applies during "geplant" - confusingly, that's the status the app's own
  // workflowMeta below labels "Vorbereitungsmodus" ("preparation mode"); "vorbereitet"
  // is actually the live-session phase ("Sitzungsmodus"), where existing marks stay
  // visible but nothing new gets marked, exactly as requested.
  const trackChangesActive = protocolStatus === "geplant" && trackChangesEnabled;
  const [sessionNotes, setSessionNotes] = useState(protocol.session_notes ?? "");
  // Neu geladenes Protokoll (z. B. nach Refresh) übernimmt den Server-Stand, wie im Sitzungspanel.
  useEffect(() => {
    setSessionNotes(protocol.session_notes ?? "");
  }, [protocol.id, protocol.session_notes]);
  const [transitioningStatus, setTransitioningStatus] = useState(false);
  const showToast = useToast();
  const createSubmissionFromTodo = useCreateSubmissionFromTodo();
  const confirm = useConfirm();
  const elementSaveTimerRef = useRef<number | null>(null);
  const isRestoringRef = useRef(true);
  const collab = useProtocolCollaboration(protocol.id);
  // Rückfrage vor dem Statuswechsel (StatusTransitionDialog)
  const [transitionDialogOpen, setTransitionDialogOpen] = useState(false);
  // Tablet (schmales Fenster): Gliederung als Überlagerung ein-/ausblenden
  const [outlineOpen, setOutlineOpen] = useState(false);
  // Anliegen (agenda_item): ohne eigenen Block unter ihrem Traktandum, siehe
  // backend app/services/agenda_item_service.py. Geladen im Client, neu bei Collab-Meldung.
  const [agendaItems, setAgendaItems] = useState<ProtocolAgendaItem[]>(initialAgendaItems ?? []);
  // Offene Schublade (Dock unten): Notizen, Pendenz, Anliegen, Status & Zusammenarbeit
  const [drawer, setDrawer] = useState<DrawerId | null>(null);
  const drawerRef = useRef<HTMLElement | null>(null);
  const [reverting, setReverting] = useState(false);
  const [agendaPostponeItem, setAgendaPostponeItem] = useState<ProtocolAgendaItem | null>(null);
  const reloadAgendaItems = useCallback(async () => {
    try {
      setAgendaItems(await browserApiFetch<ProtocolAgendaItem[]>(`/api/protocols/${protocol.id}/agenda-items`));
    } catch {
      // Best effort: ohne Anliegen bleibt der Editor voll nutzbar.
    }
  }, [protocol.id]);
  // Vom Server mitgeladen: erst bei einem Statuswechsel neu laden
  const agendaItemsPrefetchedRef = useRef(initialAgendaItems != null);
  useEffect(() => {
    if (agendaItemsPrefetchedRef.current) {
      agendaItemsPrefetchedRef.current = false;
      return;
    }
    void reloadAgendaItems();
  }, [reloadAgendaItems, protocolStatus]);

  useEffect(
    () =>
      collab.onStatusChanged(({ status, display_name }) => {
        setProtocolStatus(status);
        showToast(t("statusChangedByOtherToast", { name: display_name, status: protocolStatusLabel(status, tRoot) }));
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
      collab.onFieldUpdate(({ field_key, patch, display_name }) => {
        // Vorlagen-Abgleich (Protokollliste, "Elemente aus Vorlage neu laden") ersetzt und
        // ergänzt Blöcke - der lokale Stand (Entwürfe, Todos/Bilder je Block) passt dann
        // nicht mehr, deshalb die Seite neu laden statt einzelne Blöcke zu patchen.
        if (field_key === "template-synced") {
          showToast(t("templateSyncedByOther", { name: display_name }), "info");
          window.setTimeout(() => window.location.reload(), 1500);
          return;
        }
        if (field_key === "element-titles") {
          void refreshElementTitles();
          return;
        }
        if (field_key === "agenda-items") {
          void reloadAgendaItems();
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
          const blockId = field_key.slice("block-".length, -"-todos".length);
          if (blockId && Array.isArray(patch)) {
            setTodosByBlock((current) => ({ ...current, [blockId]: patch as ProtocolTodo[] }));
          }
          return;
        }
        if (field_key.endsWith("-images") && field_key.startsWith("block-")) {
          const blockId = field_key.slice("block-".length, -"-images".length);
          if (blockId && Array.isArray(patch)) {
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
          const { id } = patch as { id: string };
          setEvents((current) => current.filter((event) => event.id !== id));
          return;
        }
        if (!field_key.startsWith("block-")) return;
        const blockId = field_key.slice("block-".length).split("-cell-")[0];
        if (!blockId || !patch || typeof patch !== "object") return;
        updateBlockInState(blockId, (block) => ({ ...block, ...(patch as Partial<typeof block>) }));
        // The text draft store (what the text block actually renders, see handleTextChange) is
        // separate from the elements/blocks state updated above - without this, a text
        // block another user just saved keeps showing this client's stale draft even
        // after the field's readOnly lock releases, and the next local edit here would
        // silently overwrite the other user's change on save (audit F1, 2026-08-16).
        const incomingText = (patch as { text_content?: unknown }).text_content;
        if (typeof incomingText === "string") {
          textDraftStore.set(blockId, incomingText);
          // Keep the optimistic-concurrency baseline (see textBaselineRef's declaration) in
          // step with this genuinely new server content, so this client's next save doesn't
          // send a now-stale expected_content for a change it never made itself.
          textBaselineRef.current[blockId] = incomingText;
        }
      }),
    [collab.onFieldUpdate]
  );

  // Live "a list this protocol references changed elsewhere" push - just bumps the list's
  // known content_version so the stale-hint comparison in focused-element-editor.tsx picks
  // it up on the next render, even while this protocol stays open without a reload. Never
  // touches list_snapshot data itself - that only ever changes via an explicit refresh/sync.
  // Die Verantwortlichen in den Traktandentiteln dagegen liest das Backend live aus der
  // Tabelle (resolve_display_section_title) - deshalb hier die Titel neu laden.
  useEffect(
    () =>
      collab.onListChanged(({ list_definition_id, content_version }) => {
        setLists((current) =>
          current.map((list) => (list.id === list_definition_id ? { ...list, content_version } : list))
        );
        void refreshElementTitles();
      }),
    [collab.onListChanged]
  );

  // Nur laden, was page.tsx nicht schon mitgebracht hat (beim ersten Durchlauf)
  const finesPrefetchedRef = useRef({ fines: initialProtocolFines != null, pending: initialPendingFines != null });
  useEffect(() => {
    const prefetched = finesPrefetchedRef.current;
    finesPrefetchedRef.current = { fines: false, pending: false };
    if (!canViewFines) return;
    if (!prefetched.fines) {
      browserApiFetch<AttendanceFine[]>(`/api/protocols/${protocol.id}/fines`)
        .then((data) => {
          if (!data) return;
          // Erstes Laden: kein Neuladen der Diagramme (siehe protocolFinesCountRef)
          protocolFinesCountRef.current = data.length;
          setProtocolFines(data);
        })
        .catch(() => { /* silently ignore 403 for restricted roles */ });
    }
    if (!prefetched.pending) {
      browserApiFetch<AttendanceFineListItem[]>(`/api/protocols/${protocol.id}/pending-fines`)
        .then((data) => { if (data) setPendingFines(data); })
        .catch(() => {});
    }
  }, [protocol.id, canViewFines]);

  // Restore last active element from backend (von page.tsx mitgeladen, sonst hier abgefragt)
  useEffect(() => {
    const restore = (data: { element_id: string | null } | null) => {
        isRestoringRef.current = false;
        savedScrollElementIdRef.current = data?.element_id ?? null;
        // Beim Öffnen auf den gemerkten Punkt springen (sofern es ihn noch gibt), sonst bleibt
        // das Dokument oben beim ersten Punkt.
        isInitialScrollRef.current = true;
        shouldScrollToElementRef.current = true;
        const id = data?.element_id;
        if (id && initialElements.some((e) => e.id === id)) {
          setSelectedElementId(id);
        }
        setScrollRequestId((current) => current + 1);
    };
    if (initialScrollPosition != null) {
      restore(initialScrollPosition);
      return;
    }
    browserApiFetch<{ element_id: string | null }>(`/api/protocols/${protocol.id}/scroll-position`)
      .then(restore)
      .catch(() => {
        isRestoringRef.current = false;
        isInitialScrollRef.current = true;
        shouldScrollToElementRef.current = true;
        setScrollRequestId((current) => current + 1);
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [protocol.id]);

  // Save active element to backend (debounced, skip during initial restore)
  useEffect(() => {
    if (!selectedElementId || isRestoringRef.current) return;
    if (elementSaveTimerRef.current) window.clearTimeout(elementSaveTimerRef.current);
    if (selectedElementId === savedScrollElementIdRef.current) return;
    elementSaveTimerRef.current = window.setTimeout(() => {
      savedScrollElementIdRef.current = selectedElementId;
      void browserApiFetch(`/api/protocols/${protocol.id}/scroll-position`, {
        method: "PUT",
        body: JSON.stringify({ element_id: selectedElementId }),
      }).catch(() => {
        // Remembering the editor position is only a convenience. A transient network
        // failure must not surface as an unhandled rejection and crash the editor.
      });
    }, 800);
    return () => {
      if (elementSaveTimerRef.current) window.clearTimeout(elementSaveTimerRef.current);
    };
  }, [selectedElementId, protocol.id]);

  // Editing mode derived from status and role
  const forceEditable = !forceReadOnly && (protocolStatus === "geplant" || protocolStatus === "durchgeführt");
  const isReadOnly = forceReadOnly || protocolStatus === "abgeschlossen";
  // Hinweis «Vorlage wurde geändert»: bestehenden Abgleich (Rückfrage mit Vorschau) auslösen,
  // danach neu laden - Blöcke wurden ersetzt/ergänzt (wie beim Abgleich durch andere).
  const runTemplateSync = useTemplateSync();
  const [templateSyncing, setTemplateSyncing] = useState(false);
  async function reloadFromTemplate() {
    setTemplateSyncing(true);
    try {
      if (await runTemplateSync(protocol.id)) window.location.reload();
    } finally {
      setTemplateSyncing(false);
    }
  }
  // The icon/popup-driven planning UI (Tabelle-aus-Liste, Terminlisten, Termine-pro-Element,
  // Matrix-Auto-Spalten) is available in every status except "abgeschlossen", where isReadOnly
  // already blocks all editing.
  const isPlanningMode = !isReadOnly;
  // Lifted here (was previously called once per FocusedElementEditor instance) so it fires
  // once regardless of how many sections are simultaneously mounted in the document layout.
  const { tagConfig, updateTagColor, renameTag } = useTagConfig();
  const { busyByProtocol: pdfBusyByProtocol, openOrGeneratePdf } = usePdfExport();

  const workflowMeta: Record<string, { modeLabel: string; ctaLabel: string; nextStatus: string }> = {
    geplant:       { modeLabel: t("workflowPreparationMode"),   ctaLabel: t("workflowFinishPreparation"), nextStatus: "vorbereitet" },
    vorbereitet:   { modeLabel: t("workflowSessionMode"),       ctaLabel: t("workflowFinishSession"),     nextStatus: "durchgeführt" },
    durchgeführt:  { modeLabel: t("workflowPostProcessingMode"), ctaLabel: t("workflowFinishProtocol"),   nextStatus: "abgeschlossen" },
    abgeschlossen: { modeLabel: t("workflowDone"),              ctaLabel: "",                             nextStatus: "" },
  };


  // Vor jedem Statuswechsel: entprellte Text- und Notiz-Speicherungen sofort auslösen und
  // abwarten. Sonst kam der PATCH auf «abgeschlossen» vor dem letzten PUT an, der Text-Save
  // scheiterte mit 409 und der letzte Satz fehlte im eingefrorenen Protokoll und im PDF.
  const flushPendingSaves = async (): Promise<boolean> => {
    const [textOk, notesOk] = await Promise.all([
      textSaveQueue.flushAll(),
      sessionPanelRef.current?.flushPendingSaves() ?? Promise.resolve(true),
    ]);
    return textOk && notesOk;
  };

  const performStatusTransition = async () => {
    const next = workflowMeta[protocolStatus]?.nextStatus;
    if (!next) return;

    setTransitioningStatus(true);
    try {
      if (!(await flushPendingSaves())) {
        showToast(t("statusChangeUnsavedChanges"), "error");
        return;
      }
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
      showToast(err instanceof Error && err.message ? err.message : t("statusChangeFailed"), "error");
    } finally {
      setTransitioningStatus(false);
    }
  };

  // Jeder Statuswechsel braucht eine Bestätigung (Folgen + wer gerade mitarbeitet, ein Dialog)
  const transitionStatus = () => {
    const next = workflowMeta[protocolStatus]?.nextStatus;
    if (!next || transitioningStatus) return;
    setTransitionDialogOpen(true);
  };
  const transitionNext = workflowMeta[protocolStatus]?.nextStatus ?? "";
  const transitionCopy =
    transitionNext === "abgeschlossen"
      ? { title: t("finishProtocolConfirmTitle"), message: t("finishProtocolConfirmMessage") }
      : transitionNext === "durchgeführt"
        ? { title: t("finishSessionConfirmTitle"), message: t("finishSessionConfirmMessage") }
        : { title: t("finishPreparationConfirmTitle"), message: t("finishPreparationConfirmMessage") };

  // Per text block: the content the server is known to hold right now - the
  // optimistic-concurrency baseline sent as expected_content (see handleTextChange). Only
  // ever set from a confirmed server state (save response, conflict refresh, another user's
  // collab update), never from merely typed text. An earlier version advanced it on every
  // keystroke; since the save is debounced, intermediate keystrokes are never sent, so the
  // next real save claimed a baseline the server had never seen -> 409 on practically every
  // edit of more than one character, and the conflict handler replaced the just-typed text
  // with the server version even though nobody else was editing.
  const textBaselineRef = useRef<Record<string, string>>({});
  // Per text block: the currently running save. Saves of the same block are serialized so a
  // save never reads the baseline before the previous save's response has updated it.
  // Umgesetzt in createDebouncedSaveQueue (debounced-save-queue.ts).
  const sendTextSaveRef = useRef<(blockId: string, content: string) => Promise<boolean>>(async () => true);
  const [textSaveQueue] = useState(() =>
    createDebouncedSaveQueue<string>(700, (blockId, content) => sendTextSaveRef.current(blockId, content))
  );
  // Funktionsdeklaration (gehoistet), liest bei jedem Aufruf den aktuellen Render-Stand.
  sendTextSaveRef.current = sendTextSave;
  const shouldScrollToElementRef = useRef(false);
  // Separate from shouldScrollToElementRef: only an explicit jump (sidebar/keyboard/search,
  // set in focusElement below) should steal focus into a field. Restoring the remembered
  // scroll position on page load must still land the view there (so returning users keep
  // their place), but doing that right after opening the page - without the user asking for
  // it - must not also autofocus a form field (usability-audit finding F9, 2026-10-01: a
  // freshly opened protocol jumped straight into an input with the cursor already blinking).
  const shouldAutoFocusRef = useRef(false);
  // The first scroll after opening jumps instantly instead of animating from the top.
  const isInitialScrollRef = useRef(false);
  // Aktiver Punkt beim Scrollen (section-spy.ts) und laufender Sprung (document-scroll.ts)
  const spyRef = useRef<SectionSpy | null>(null);
  const cancelJumpRef = useRef<(() => void) | null>(null);
  const [scrollRequestId, setScrollRequestId] = useState(0);
  const selectedElementIdRef = useRef(selectedElementId);
  selectedElementIdRef.current = selectedElementId;
  const documentRef = useRef<HTMLDivElement | null>(null);
  const sessionPanelRef = useRef<SessionPanelHandle | null>(null);
  useEffect(() => {
    return () => {
      textSaveQueue.cancelAll();
    };
  }, [textSaveQueue]);

  // Recover text that was typed before a tab/browser crash or a failed request. A draft is
  // only ever removed after the backend confirmed the exact value.
  // Ein Entwurf, dessen Baseline nicht mehr dem Serverstand entspricht (jemand anderes hat
  // inzwischen gespeichert), wird nicht automatisch übernommen, sondern nur auf Wunsch.
  useEffect(() => {
    const restoredDrafts: (readonly [string, string])[] = [];
    const conflictingDrafts: (readonly [string, string])[] = [];
    const initialDrafts = textDraftStore.getAll();
    for (const blockId of Object.keys(initialDrafts)) {
      const draft = readDraft(textDraftKey(blockId));
      const decision = decideDraftRestore(draft, readDraft(textDraftBaseKey(blockId)), initialDrafts[blockId]);
      if (decision === "restore") restoredDrafts.push([blockId, draft as string]);
      if (decision === "conflict") conflictingDrafts.push([blockId, draft as string]);
    }
    const applyDrafts = (drafts: (readonly [string, string])[]) => textDraftStore.setMany(drafts);
    if (restoredDrafts.length > 0) {
      applyDrafts(restoredDrafts);
      showToast(t("draftsRestoredToast", { count: restoredDrafts.length }), "info");
    }
    if (conflictingDrafts.length > 0) {
      showToast(t("draftsConflictToast", { count: conflictingDrafts.length }), "error", {
        action: {
          label: t("draftsConflictApply"),
          onClick: () => {
            // Ausdrücklich gewählt: Entwurf übernehmen, die neue Baseline ist der aktuelle
            // Serverstand, damit die nächste Speicherung nicht als Konflikt scheitert.
            for (const [blockId] of conflictingDrafts) saveDraft(textDraftBaseKey(blockId), knownServerText(blockId));
            applyDrafts(conflictingDrafts);
          },
        },
      });
    }
  // Initial server values are deliberately compared exactly once per mounted protocol.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [protocol.id]);

  useEffect(() => {
    const flushed = (event: Event) => {
      const key = (event as CustomEvent<{ key?: string }>).detail?.key;
      if (!key?.startsWith("protocol-text:")) return;
      clearDraft(key);
      const blockId = key.slice("protocol-text:".length);
      if (blockId) clearDraft(textDraftBaseKey(blockId));
      if (blockId) setStatus(blockId, "saved");
    };
    window.addEventListener("hocx:mutation-flushed", flushed);
    return () => window.removeEventListener("hocx:mutation-flushed", flushed);
  }, []);

  useEffect(() => {
    // Covers the bulk "verwerfen" action in ConnectivityStatus discarding a text-save that
    // was blocked on the outbox (e.g. a conflict that happened while this tab was offline,
    // only surfacing once it reconnected and flushOutbox tried it) - the immediate-conflict
    // path in handleTextChange already refreshes state itself, so this only matters for
    // that separate route into the same "blocked" outcome. Deliberately does not clearDraft:
    // the local draft stays as the documented fallback until the user's next edit overwrites
    // it or they reload and accept the server content.
    const discarded = (event: Event) => {
      const key = (event as CustomEvent<{ key?: string }>).detail?.key;
      if (!key?.startsWith("protocol-text:")) return;
      const blockId = key.slice("protocol-text:".length);
      if (blockId) setStatus(blockId, "error");
    };
    window.addEventListener("hocx:mutation-discarded", discarded);
    return () => window.removeEventListener("hocx:mutation-discarded", discarded);
  }, []);

  // Speicherstatus im Kopf (F8): speichert / gespeichert / offline (n wartend) / Fehler mit Sprung
  // zum Block. «Gespeichert» erst, nachdem in dieser Sitzung etwas gespeichert wurde.
  const offline = useSyncExternalStore(subscribeOfflineStore, getOfflineSnapshot, getOfflineServerSnapshot);
  const blockStatusValues = Object.values(blockStatus);
  const errorBlockId = Object.entries(blockStatus).find(([, state]) => state === "error")?.[0] ?? null;
  const saveKind: ProtocolSaveState["kind"] = !offline.online
    ? "offline"
    : errorBlockId
      ? "error"
      : blockStatusValues.includes("saving")
        ? "saving"
        : blockStatusValues.includes("saved")
          ? "saved"
          : "idle";
  const offlinePending = offline.pending;
  const saveState = useMemo<ProtocolSaveState>(
    () => (saveKind === "offline" ? { kind: "offline", pending: offlinePending } : { kind: saveKind }),
    [saveKind, offlinePending]
  );

  // Abgeleitete Punkte je Quell-Objekt zwischenspeichern: ein unveränderter Punkt behält seine
  // Identität, und der memoisierte FocusedElementEditor rendert nur den geänderten neu.
  const derivedElementsRef = useRef(new WeakMap<ProtocolElement, ProtocolElement>());
  const derivedPlanningModeRef = useRef(isPlanningMode);
  const visibleElements = useMemo(() => {
    if (derivedPlanningModeRef.current !== isPlanningMode) {
      derivedElementsRef.current = new WeakMap();
      derivedPlanningModeRef.current = isPlanningMode;
    }
    const cache = derivedElementsRef.current;
    return [...elements]
      .filter((element) => element.is_visible_snapshot)
      .map((element) => {
        const cached = cache.get(element);
        if (cached) return cached;
        const derived = {
          ...element,
          blocks: [...element.blocks]
            .filter((block) => (isPlanningMode || block.is_visible_snapshot) && block.element_type_code !== "display")
            .sort((left, right) => left.sort_index - right.sort_index)
        };
        cache.set(element, derived);
        return derived;
      })
      .filter((element) => element.blocks.length > 0 || element.show_when_empty)
      .sort((left, right) => left.sort_index - right.sort_index);
  }, [elements, isPlanningMode]);

  const visibleElementIdsKey = visibleElements.map((element) => element.id).join(",");

  const selectedElement = useMemo(
    () => visibleElements.find((element) => element.id === selectedElementId) ?? null,
    [selectedElementId, visibleElements]
  );
  const agendaByElement = useMemo(() => {
    const visibleIds = new Set(visibleElementIdsKey.split(",").filter(Boolean));
    const byElement: Record<string, ProtocolAgendaItem[]> = {};
    const other: ProtocolAgendaItem[] = [];
    for (const item of agendaItems) {
      if (item.protocol_element_id && visibleIds.has(item.protocol_element_id)) {
        (byElement[item.protocol_element_id] ??= []).push(item);
      } else {
        other.push(item);
      }
    }
    return { byElement, other };
  }, [agendaItems, visibleElementIdsKey]);
  const agendaSectionHandlers = useMemo(() => ({
    onChanged: (updated: ProtocolAgendaItem) => setAgendaItems((current) => current.map((item) => (item.id === updated.id ? updated : item))),
    onRemoved: (itemId: string) => setAgendaItems((current) => current.filter((item) => item.id !== itemId)),
    onPostpone: (item: ProtocolAgendaItem) => setAgendaPostponeItem(item),
  }), []);
  // Je Punkt ein fertiges Element mit stabiler Identität, damit memoisierte Punkte nicht wegen
  // eines neuen agendaSlot-Elements neu rendern.
  // Ein Slot wird nur neu gebaut, wenn sich die Anliegen dieses Punkts (oder isReadOnly) ändern.
  const agendaSlotCacheRef = useRef(new Map<string, { items: ProtocolAgendaItem[]; isReadOnly: boolean; node: React.ReactNode }>());
  const agendaSlots = useMemo(() => {
    const cache = agendaSlotCacheRef.current;
    const slots: Record<string, React.ReactNode> = {};
    for (const elementId of visibleElementIdsKey.split(",").filter(Boolean)) {
      const items = agendaByElement.byElement[elementId] ?? EMPTY_AGENDA_ITEMS;
      const cached = cache.get(elementId);
      if (cached && cached.isReadOnly === isReadOnly && sameItems(cached.items, items)) {
        slots[elementId] = cached.node;
        continue;
      }
      const node = <AgendaItemsSection items={items} isReadOnly={isReadOnly} {...agendaSectionHandlers} />;
      cache.set(elementId, { items, isReadOnly, node });
      slots[elementId] = node;
    }
    return slots;
  }, [visibleElementIdsKey, agendaByElement, isReadOnly, agendaSectionHandlers]);
  // Pendenzen je Punkt für die Sitzungsansicht (Tag = Punktname). Unveränderte Listen behalten
  // ihre Identität, damit eine Pendenz-Änderung nur die betroffenen Punkte neu rendert.
  const sessionTodoCacheRef = useRef(new Map<string, ProtocolTodo[]>());
  const sessionTodosByElement = useMemo(() => {
    const allTodos = Object.values(todosByBlock).flat();
    const cache = sessionTodoCacheRef.current;
    const result: Record<string, ProtocolTodo[]> = {};
    for (const element of visibleElements) {
      const tag = trimSectionName(element.section_name_snapshot).toLowerCase();
      const todos = allTodos.filter((todo) => (todo.tags ?? []).includes(tag));
      const previous = cache.get(element.id);
      const stable = previous && sameItems(previous, todos) ? previous : todos.length ? todos : EMPTY_TODOS;
      cache.set(element.id, stable);
      result[element.id] = stable;
    }
    return result;
  }, [todosByBlock, visibleElements]);
  // Über den Inhalt stabil: ändert sich nur ein Block, bleibt das Objekt (und damit
  // listDefinitionsById) gleich und die übrigen Punkte rendern nicht neu.
  const listPublicIdsKey = JSON.stringify(Object.assign({}, ...elements.flatMap((element) =>
    element.blocks.map((block) => block.public_reference_ids?.lists ?? {})
  )));
  const listPublicIds = useMemo(() => JSON.parse(listPublicIdsKey) as Record<string, string>, [listPublicIdsKey]);
  const listDefinitionsById = useMemo(() => {
    const definitions = new Map(lists.map((definition) => [definition.id, definition]));
    for (const [internalId, publicId] of Object.entries(listPublicIds)) {
      const definition = definitions.get(publicId);
      if (definition) definitions.set(internalId, definition);
    }
    return definitions;
  }, [lists, listPublicIds]);
  const attendanceTally = useMemo(
    () => visibleAttendanceTally(elements, availableParticipants, protocol.protocol_date, protocolStatus === "abgeschlossen"),
    [elements, availableParticipants, protocol.protocol_date, protocolStatus]
  );
  // Schublade umschalten; beim Schliessen zurück auf den Knopf im Dock
  function toggleDrawer(id: DrawerId) {
    if (drawer === id) {
      closeDrawer();
      return;
    }
    if (isReadOnly && (id === "todo" || id === "agenda")) return;
    if (id === "todo") sessionPanelRef.current?.prefillTodoFromSelection();
    setDrawer(id);
    if (id === "agenda" || id === "status") {
      window.setTimeout(() => {
        const field = drawerRef.current?.querySelector<HTMLElement>("[data-drawer-autofocus]");
        (field ?? drawerRef.current?.querySelector<HTMLElement>(".protocol-drawer-close"))?.focus();
      }, 60);
    }
  }
  function closeDrawer() {
    const closing = drawer;
    setDrawer(null);
    if (closing) window.requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-drawer-button="${closing}"]`)?.focus());
  }

  const sessionDueEvents = useMemo(() => {
    const tpl = availableTemplates.find((template) => template.id === protocol.template_id);
    const tag = tpl?.todo_due_event_tag?.trim().toLowerCase();
    const today = localIsoDate();
    const upcoming = events.filter((event) => event.event_date >= today);
    return tag ? upcoming.filter((event) => (event.tag ?? "").toLowerCase().includes(tag)) : upcoming;
  }, [availableTemplates, protocol.template_id, events]);


  function setStatus(protocolElementBlockId: string, status: SaveState) {
    // Unveränderten Status nicht neu setzen: beim Tippen kam sonst pro Taste ein zusätzlicher Render
    setBlockStatus((current) => (current[protocolElementBlockId] === status ? current : { ...current, [protocolElementBlockId]: status }));
  }

  useEffect(() => () => cancelJumpRef.current?.(), []);

  function focusElement(protocolElementId: string) {
    shouldScrollToElementRef.current = true;
    shouldAutoFocusRef.current = true;
    setSelectedElementId(protocolElementId);
    // Also re-run the scroll effect when the target is already the selected element
    // (e.g. search hit on the current section after the user scrolled away from it).
    setScrollRequestId((current) => current + 1);
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

  // Sprung zum gewählten Punkt (Gliederung, Suche, Tastatur, gemerkte Leseposition). Zweistufig,
  // weil Punkte ausserhalb des Bildes nicht gerendert sind (content-visibility, jumpToSection).
  useEffect(() => {
    if (!selectedElementId || !shouldScrollToElementRef.current) {
      return;
    }

    shouldScrollToElementRef.current = false;
    const smooth = !isInitialScrollRef.current && !prefersReducedMotion();
    isInitialScrollRef.current = false;

    const frame = window.requestAnimationFrame(() => {
      // Nur .protocol-doc selbst scrollen (nie scrollIntoView(): das scrollt jeden Vorfahren mit,
      // auch die fest stehende Hülle der Schreibansicht).
      const container = documentRef.current;
      const section = document.getElementById(`protocol-element-${selectedElementId}`);
      if (container && section) {
        cancelJumpRef.current?.();
        const spy = spyRef.current;
        spy?.setCurrent(selectedElementId);
        spy?.setPaused(true);
        cancelJumpRef.current = jumpToSection(container, section, {
          smooth,
          onDone: () => {
            cancelJumpRef.current = null;
            spy?.setPaused(false);
          },
        });
      }

      // Die Seite selbst darf in der Schreibansicht nie scrollen (focus() unten scrollt sonst
      // jeden Vorfahren mit).
      if (window.matchMedia("(min-width: 901px)").matches) {
        window.scrollTo(0, 0);
      }

      window.setTimeout(() => {
        const shouldAutoFocus = shouldAutoFocusRef.current;
        shouldAutoFocusRef.current = false;
        if (shouldAutoFocus) {
          const target = document.getElementById(`protocol-element-${selectedElementId}`);
          const firstEditable = target?.querySelector<HTMLElement>(
            '[data-form-input], textarea:not([readonly]), input:not([readonly]):not([type="file"])'
          );
          firstEditable?.focus({ preventScroll: true });
        }
        if (window.matchMedia("(min-width: 901px)").matches) {
          window.scrollTo(0, 0);
        }
      }, 120);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [selectedElementId, scrollRequestId]);

  // Aktiver Punkt beim Scrollen: IntersectionObserver statt Messen in jedem Frame (section-spy.ts).
  // Passives Scrollen fokussiert nie ein Feld (kein focusElement).
  useEffect(() => {
    const container = documentRef.current;
    if (!container) return;
    const spy = createSectionSpy(
      container,
      (section) => section.id.replace("protocol-element-", "") || null,
      (id) => {
        if (selectedElementIdRef.current === id) return;
        selectedElementIdRef.current = id;
        setSelectedElementId(id);
      }
    );
    spyRef.current = spy;
    return () => {
      spy?.destroy();
      spyRef.current = null;
    };
  }, []);
  useEffect(() => {
    const container = documentRef.current;
    if (!container) return;
    spyRef.current?.observe(Array.from(container.querySelectorAll<HTMLElement>(".protocol-doc-section")));
  }, [visibleElementIdsKey]);

  // Tastenkürzel des Editors (Definitionen und Regeln: lib/keyboard/registry.ts, Gruppe «protocol»).
  // Der zentrale Dispatcher sorgt dafür, dass sie nicht in offenen Dialogen/Menüs, nicht in
  // Listen-Widgets und (ohne Modifier) nicht beim Tippen auslösen.
  // Strg+F → Kapitel-/Volltextsuche (statt der Browsersuche), auch beim Tippen. Ist eine
  // Anwesenheitskontrolle im aktiven Punkt, fokussiert das erste Strg+F deren Personensuche, ein
  // weiteres (Fokus schon dort) öffnet die Kapitelsuche.
  useShortcut("protocol.find", () => {
    const activeSection = selectedElementId ? document.getElementById(`protocol-element-${selectedElementId}`) : null;
    const attendanceSearch = activeSection?.querySelector<HTMLInputElement>(`[${ATTENDANCE_SEARCH_ATTR}]`);
    if (attendanceSearch && document.activeElement !== attendanceSearch) {
      attendanceSearch.focus();
      attendanceSearch.select();
      return;
    }
    setSearchOpen(true);
  });
  useShortcut(DRAWER_SHORTCUTS.notes, () => toggleDrawer("notes"));
  useShortcut(DRAWER_SHORTCUTS.todo, () => (isReadOnly ? false : toggleDrawer("todo")));
  useShortcut(DRAWER_SHORTCUTS.agenda, () => (isReadOnly ? false : toggleDrawer("agenda")));
  useShortcut(DRAWER_SHORTCUTS.status, () => toggleDrawer("status"));
  // Blockweise (Strg/⌘+Enter, mit Umschalt rückwärts), auch in Feldern. Nach dem letzten Block
  // bleibt der Fokus dort (früher schloss Strg+Enter am Ende das Protokoll).
  useShortcut("protocol.nextBlock", () => stepBlock(1));
  useShortcut("protocol.previousBlock", () => stepBlock(-1));

  /** Block aktivieren (oder mit null verlassen); der Punkt des Blocks wird aktiver Punkt. */
  function activateBlock(blockId: string | null) {
    if (!blockId || isReadOnly) {
      setActiveBlock(null);
      return;
    }
    const element = visibleElements.find((item) => item.blocks.some((block) => block.id === blockId));
    if (!element) return;
    setActiveBlock({ elementId: element.id, blockId });
    if (selectedElementIdRef.current !== element.id) {
      selectedElementIdRef.current = element.id;
      spyRef.current?.setCurrent(element.id);
      setSelectedElementId(element.id);
    }
  }

  /** Bausteine, die Strg+Enter anspringt: sichtbar, bearbeitbar, nicht von anderen gesperrt. */
  function navigableBlocks() {
    if (isReadOnly) return [];
    return visibleElements.flatMap((element) =>
      element.blocks
        .filter((block) =>
          block.is_visible_snapshot &&
          !NON_NAVIGABLE_BLOCK_TYPES.has(block.element_type_code ?? "") &&
          (forceEditable || block.is_editable_snapshot) &&
          !collab.isLockedByOther(`block-${block.id}`)
        )
        .map((block) => ({ elementId: element.id, blockId: block.id }))
    );
  }

  function stepBlock(direction: 1 | -1) {
    const order = navigableBlocks();
    if (!order.length) return false;
    const current = activeBlock ? order.findIndex((entry) => entry.blockId === activeBlock.blockId) : -1;
    let index: number;
    if (current >= 0) {
      index = current + direction;
    } else {
      // Ohne aktiven Block: ab dem aktiven Punkt (vorwärts dessen erster, rückwärts der Block davor)
      const sectionIndex = Math.max(0, visibleElements.findIndex((element) => element.id === selectedElementId));
      const first = order.findIndex((entry) => visibleElements.findIndex((element) => element.id === entry.elementId) >= sectionIndex);
      index = first < 0 ? (direction > 0 ? order.length : order.length - 1) : direction > 0 ? first : first - 1;
    }
    if (index < 0 || index >= order.length) {
      // Am Rand bleiben (nichts schliessen), nur ansagen
      announce(direction > 0 ? t("lastBlockReached") : t("firstBlockReached"));
      return;
    }
    const target = order[index];
    activateBlock(target.blockId);
    revealBlock(target.blockId);
  }

  /** Block ins Bild holen (nur wenn nötig) und sein erstes Feld fokussieren. */
  function revealBlock(blockId: string) {
    window.requestAnimationFrame(() => {
      const container = documentRef.current;
      const card = container?.querySelector<HTMLElement>(`[data-block-id="${CSS.escape(blockId)}"]`);
      if (!container || !card) return;
      const cardRect = card.getBoundingClientRect();
      const viewRect = container.getBoundingClientRect();
      if (cardRect.top < viewRect.top + 40 || cardRect.top > viewRect.bottom - 160) {
        container.scrollTo({ top: container.scrollTop + cardRect.top - viewRect.top - 80, behavior: prefersReducedMotion() ? "auto" : "smooth" });
      }
      // Textblöcke fokussieren sich selbst, sobald der Editor geladen ist (autoFocus)
      if (card.dataset.blockType === "text" || card.dataset.blockType === "static_text") return;
      window.setTimeout(() => {
        const field = card.querySelector<HTMLElement>(
          '[data-form-input], textarea:not([readonly]), input:not([readonly]):not([type="file"]):not([type="checkbox"]), button:not([disabled]):not([data-block-activate])'
        );
        field?.focus({ preventScroll: true });
      }, 60);
    });
  }

  // Nur lesend (abgeschlossen, Statuswechsel): kein aktiver Block
  useEffect(() => {
    if (isReadOnly) setActiveBlock(null);
  }, [isReadOnly]);

  async function reorderElements(sourceId: string, targetId: string | null) {
    if (sourceId === targetId) return;
    const ordered = [...elements].sort((left, right) => left.sort_index - right.sort_index);
    const sourceIndex = ordered.findIndex((item) => item.id === sourceId);
    const targetIndex = targetId === null ? ordered.length - 1 : ordered.findIndex((item) => item.id === targetId);
    if (sourceIndex === -1 || targetIndex === -1) {
      return;
    }
    const [moved] = ordered.splice(sourceIndex, 1);
    ordered.splice(targetIndex, 0, moved);
    const resequenced = resequenceProtocolElements(ordered);
    const nextStatus: Record<string, SaveState> = {};
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
      showToast(err instanceof Error ? err.message : t("orderSaveFailed"), "error");
    }
  }

  function updateBlockInState(blockId: string, updater: (current: ProtocolElement["blocks"][number]) => ProtocolElement["blocks"][number]) {
    setElements((current) =>
      current.map((element) =>
        element.blocks.some((block) => block.id === blockId)
          ? { ...element, blocks: element.blocks.map((block) => (block.id === blockId ? updater(block) : block)) }
          : element
      )
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

  // Pulls the current server-side text_content for a single block after a 409 conflict on
  // its text save (see handleTextChange) - reuses the same "/elements" list endpoint as
  // refreshElementTitles/refreshAfterTrackingCleared rather than a dedicated per-block GET,
  // since one doesn't exist and this only needs to run once, on-demand, per conflict.
  async function refreshBlockTextFromServer(blockId: string) {
    try {
      const fresh = await browserApiFetch<ProtocolElement[]>(`/api/protocols/${protocol.id}/elements`);
      const freshBlock = fresh.flatMap((element) => element.blocks).find((block) => block.id === blockId);
      if (!freshBlock) return;
      updateBlockInState(blockId, (block) => ({
        ...block,
        text_content: freshBlock.text_content,
        tracked_dirty: freshBlock.tracked_dirty,
        tracked_baseline_content: freshBlock.tracked_baseline_content,
      }));
      textDraftStore.set(blockId, freshBlock.text_content ?? "");
      textBaselineRef.current[blockId] = freshBlock.text_content ?? "";
      setStatus(blockId, "saved");
    } catch {
      // best-effort - the conflict toast already told the user to reload manually if this
      // silent refresh also fails.
    }
  }

  function currentConfigVersion(blockId: string): number | undefined {
    return elements.flatMap((element) => element.blocks).find((block) => block.id === blockId)?.config_version;
  }

  // 409 config_conflict: jemand anderes hat die Blockkonfiguration inzwischen gespeichert. Der
  // Server liefert seinen Stand mit - übernehmen und darauf hinweisen (Concurrency-Audit
  // CONC-005: vorher überschrieb das ganze JSON still die Änderung der anderen Person).
  function applyConfigConflict(blockId: string, err: unknown): boolean {
    if (!(err instanceof ApiError) || err.status !== 409) return false;
    const detail = err.detail as { code?: string; configuration_snapshot_json?: Record<string, unknown>; config_version?: number } | undefined;
    if (detail?.code !== "config_conflict" || !detail.configuration_snapshot_json) return false;
    updateBlockInState(blockId, (block) => ({
      ...block,
      configuration_snapshot_json: detail.configuration_snapshot_json!,
      config_version: detail.config_version,
    }));
    setStatus(blockId, "saved");
    showToast(t("configConflictReloaded"), "info");
    return true;
  }

  async function saveBlockConfiguration(blockId: string, configurationSnapshotJson: Record<string, unknown>) {
    setStatus(blockId, "saving");
    const expectedVersion = currentConfigVersion(blockId);
    updateBlockInState(blockId, (block) => ({ ...block, configuration_snapshot_json: configurationSnapshotJson }));
    try {
      const updated = await browserApiFetch<ProtocolElement["blocks"][number]>(`/api/protocol-element-blocks/${blockId}`, {
        method: "PATCH",
        body: JSON.stringify({ configuration_snapshot_json: configurationSnapshotJson, expected_config_version: expectedVersion }),
      });
      updateBlockInState(blockId, (block) => ({
        ...block,
        configuration_snapshot_json: updated.configuration_snapshot_json,
        config_version: updated.config_version,
      }));
      setStatus(blockId, "saved");
      collab.sendFieldUpdate(`block-${blockId}`, { configuration_snapshot_json: updated.configuration_snapshot_json, config_version: updated.config_version });
    } catch (err: unknown) {
      if (applyConfigConflict(blockId, err)) return;
      setStatus(blockId, "error");
      showToast(err instanceof Error ? err.message : t("changeSaveFailed"), "error");
    }
  }

  // Dedicated atomic single-participant save for the attendance block's status buttons - see
  // backend ProtocolElementService.set_attendance_status. saveBlockConfiguration above PATCHes
  // the whole configuration_snapshot_json; building attendance_entries through that generic
  // path round-trips the *entire* array taken from a local snapshot, so a second status click
  // fired before the first save's response/re-render had landed (the same person clicking
  // quickly through the list, or two people taking attendance together) based its "whole
  // array" on a stale copy and silently erased whoever was just saved. This talks to a
  // server-side merge endpoint instead, so each click only ever touches its own entry - and
  // unlike saveBlockConfiguration, failures are rethrown so callers (the fine-creation logic in
  // focused-element-editor.tsx) don't keep going as though the save had succeeded.
  async function saveAttendanceStatus(blockId: string, participantId: string, participantName: string, status: string) {
    const block = elements.flatMap((element) => element.blocks).find((b) => b.id === blockId);
    const previousEntry = (Array.isArray(block?.configuration_snapshot_json?.attendance_entries)
      ? (block!.configuration_snapshot_json.attendance_entries as Array<Record<string, unknown>>)
      : []
    ).find((entry) => String(entry.participant_id) === participantId);
    // Optimistisch auf dem aktuellen State aufbauen (nicht auf ``elements`` dieses Renders):
    // «Übrige auf anwesend» speichert mehrere Personen nacheinander mit derselben Closure.
    updateBlockInState(blockId, (b) => {
      const current = Array.isArray(b.configuration_snapshot_json?.attendance_entries)
        ? (b.configuration_snapshot_json.attendance_entries as Array<Record<string, unknown>>)
        : [];
      return {
        ...b,
        configuration_snapshot_json: {
          ...b.configuration_snapshot_json,
          attendance_entries: [
            ...current.filter((entry) => String(entry.participant_id) !== participantId),
            { participant_id: participantId, participant_name: participantName, status },
          ],
        },
      };
    });
    try {
      const updated = await browserApiFetch<ProtocolElement["blocks"][number]>(
        `/api/protocol-element-blocks/${blockId}/attendance/${participantId}`,
        { method: "POST", body: JSON.stringify({ status }) }
      );
      updateBlockInState(blockId, (b) => ({ ...b, configuration_snapshot_json: updated.configuration_snapshot_json, config_version: updated.config_version }));
      collab.sendFieldUpdate(`block-${blockId}`, { configuration_snapshot_json: updated.configuration_snapshot_json, config_version: updated.config_version });
    } catch (err: unknown) {
      // Nur den Eintrag dieser Person zurücksetzen, gleichzeitige Änderungen anderer bleiben.
      updateBlockInState(blockId, (b) => {
        const current = Array.isArray(b.configuration_snapshot_json?.attendance_entries)
          ? (b.configuration_snapshot_json.attendance_entries as Array<Record<string, unknown>>)
          : [];
        const others = current.filter((entry) => String(entry.participant_id) !== participantId);
        return {
          ...b,
          configuration_snapshot_json: { ...b.configuration_snapshot_json, attendance_entries: previousEntry ? [...others, previousEntry] : others },
        };
      });
      throw err;
    }
  }

  // See textBaselineRef's declaration.
  function knownServerText(protocolElementBlockId: string) {
    return (
      textBaselineRef.current[protocolElementBlockId] ??
      (elements.flatMap((element) => element.blocks).find((block) => block.id === protocolElementBlockId)?.text_content ?? "")
    );
  }

  function handleTextChange(protocolElementBlockId: string, content: string) {
    const mutationKey = textDraftKey(protocolElementBlockId);
    // Baseline nur beim ersten Tastendruck eines Entwurfs festhalten (siehe text-drafts.ts).
    if (readDraft(mutationKey) === null) saveDraft(textDraftBaseKey(protocolElementBlockId), knownServerText(protocolElementBlockId));
    saveDraft(mutationKey, content);
    queueMutation({
      key: mutationKey,
      path: `/api/protocol-element-blocks/${protocolElementBlockId}/text`,
      method: "PUT",
      body: JSON.stringify({ content, expected_content: knownServerText(protocolElementBlockId) }),
    });
    textDraftStore.set(protocolElementBlockId, content);
    setStatus(protocolElementBlockId, "saving");

    // Entprellt (700 ms) und pro Block serialisiert; flushPendingSaves() löst wartende
    // Speicherungen vor einem Statuswechsel sofort aus und wartet sie ab.
    textSaveQueue.schedule(protocolElementBlockId, content);
  }

  // Runs serialized per block (see textSaveChainRef), so expected_content is read only after
  // any previous save of this block has landed and updated the baseline.
  async function sendTextSave(protocolElementBlockId: string, content: string): Promise<boolean> {
    const mutationKey = `protocol-text:${protocolElementBlockId}`;
    const expectedContent = knownServerText(protocolElementBlockId);
    // The user may have kept typing while this save was waiting/in flight; that newer text
    // has its own draft, outbox entry and pending save, which this one must not clobber.
    const isLatestEdit = () => readDraft(mutationKey) === content;
    try {
      const result = await browserApiFetch<{ tracked_dirty: boolean; tracked_baseline_content: string | null }>(
        `/api/protocol-element-blocks/${protocolElementBlockId}/text`,
        { method: "PUT", body: JSON.stringify({ content, expected_content: expectedContent }) }
      );
      textBaselineRef.current[protocolElementBlockId] = content;
      updateBlockInState(protocolElementBlockId, (block) => ({
        ...block,
        text_content: content,
        tracked_dirty: result.tracked_dirty,
        tracked_baseline_content: result.tracked_baseline_content,
      }));
      if (isLatestEdit()) {
        setStatus(protocolElementBlockId, "saved");
        clearDraft(mutationKey);
        clearDraft(textDraftBaseKey(protocolElementBlockId));
        removeMutation(mutationKey);
      }
      collab.sendFieldUpdate(`block-${protocolElementBlockId}`, {
        text_content: content,
        tracked_dirty: result.tracked_dirty,
        tracked_baseline_content: result.tracked_baseline_content,
      });
      return true;
    } catch (err: unknown) {
      setStatus(protocolElementBlockId, "error");
      if (err instanceof ApiError && err.kind === "conflict") {
        // A real edit conflict, not a connectivity problem: someone else already saved a
        // newer version of this exact text since we last loaded it. `content` here is
        // already-rejected - re-queueing it (the generic path below) would just keep
        // losing to the same 409 on every future flush with the misleading "will save
        // automatically once back online" toast. Instead: drop it from the outbox so it
        // stops being retried (fix for the outbox-stall issue above applies to this item
        // too - it must end up explicitly discarded, not silently stuck), pull in the
        // current server content, and tell the user plainly what happened. Their locally
        // typed text isn't lost - saveDraft() above already wrote it to
        // `protocol-text:${id}` in localStorage as a fallback; it's just not queued for
        // silent resend anymore.
        discardMutation(mutationKey);
        void refreshBlockTextFromServer(protocolElementBlockId);
        showToast(
          t("conflictToast"),
          "error",
          { onMessageClick: () => void refreshBlockTextFromServer(protocolElementBlockId) }
        );
        return false;
      }
      // Ein neuerer Stand desselben Blocks ist schon unterwegs; dessen Ergebnis zählt.
      if (!isLatestEdit()) return true;
      queueMutation({
        key: mutationKey,
        path: `/api/protocol-element-blocks/${protocolElementBlockId}/text`,
        method: "PUT",
        body: JSON.stringify({ content, expected_content: expectedContent }),
        lastError: err instanceof Error ? err.message : t("textSaveFailed"),
      });
      showToast(t("textSavedLocallyOffline"), "error");
      return false;
    }
  }

  // "Ausblenden" for a text block's red tracked-change highlight (whole block at once -
  // see AutosaveService.accept_tracked_changes for why not per-word).
  async function acceptTextTrackedChanges(protocolElementBlockId: string) {
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
      if (err instanceof Error) showToast(err.message, "error");
    }
  }

  async function addTodo(protocolElementBlockId: string) {
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
      const next = [...(todosByBlockRef.current[protocolElementBlockId] ?? []), created].sort((left, right) => left.sort_index - right.sort_index);
      setTodosByBlock((current) => ({ ...current, [protocolElementBlockId]: next }));
      collab.sendFieldUpdate(`block-${protocolElementBlockId}-todos`, next);
      setNewTodoTask((current) => ({ ...current, [protocolElementBlockId]: "" }));
      setNewTodoTags((current) => ({ ...current, [protocolElementBlockId]: "" }));
      setStatus(protocolElementBlockId, "saved");
    } catch (err: unknown) {
      setStatus(protocolElementBlockId, "error");
      showToast(err instanceof Error ? err.message : t("todoCreateFailed"), "error");
    }
  }

  async function updateTodo(protocolElementBlockId: string, todoId: string, patch: Partial<ProtocolTodo>) {
    setStatus(protocolElementBlockId, "saving");
    try {
      const updated = await browserApiFetch<ProtocolTodo>(`/api/protocol-todos/${todoId}`, {
        method: "PATCH",
        body: JSON.stringify(patch)
      });
      const next = (todosByBlockRef.current[protocolElementBlockId] ?? []).map((todo) => (todo.id === todoId ? updated : todo));
      setTodosByBlock((current) => ({ ...current, [protocolElementBlockId]: next }));
      collab.sendFieldUpdate(`block-${protocolElementBlockId}-todos`, next);
      setStatus(protocolElementBlockId, "saved");
    } catch (err: unknown) {
      setStatus(protocolElementBlockId, "error");
      showToast(err instanceof Error ? err.message : t("todoSaveFailed"), "error");
    }
  }

  // «Als Abgabe einsammeln»: die Pendenz wird die Pendenz der neuen Einzelabgabe (Titel, Frist, Link
  // und Status führt ab jetzt der Abgleich der Abgabe)
  async function collectTodoAsSubmission(protocolElementBlockId: string, todoId: string) {
    setStatus(protocolElementBlockId, "saving");
    const result = await createSubmissionFromTodo(todoId);
    if (!result) {
      setStatus(protocolElementBlockId, "error");
      return;
    }
    const next = (todosByBlockRef.current[protocolElementBlockId] ?? []).map((todo) => (todo.id === todoId ? { ...todo, ...result.todo } : todo));
    setTodosByBlock((current) => ({ ...current, [protocolElementBlockId]: next }));
    collab.sendFieldUpdate(`block-${protocolElementBlockId}-todos`, next);
    setStatus(protocolElementBlockId, "saved");
  }

  async function deleteTodo(protocolElementBlockId: string, todoId: string) {
    const ok = await confirm({
      message: t("todoDeleteConfirm"),
      tone: "danger",
      confirmLabel: tCommon("delete")
    });
    if (!ok) return;
    setStatus(protocolElementBlockId, "saving");
    try {
      await browserApiFetch(`/api/protocol-todos/${todoId}`, { method: "DELETE" });
      const next = (todosByBlockRef.current[protocolElementBlockId] ?? []).filter((todo) => todo.id !== todoId);
      setTodosByBlock((current) => ({ ...current, [protocolElementBlockId]: next }));
      collab.sendFieldUpdate(`block-${protocolElementBlockId}-todos`, next);
      setStatus(protocolElementBlockId, "saved");
    } catch (err: unknown) {
      setStatus(protocolElementBlockId, "error");
      showToast(err instanceof Error ? err.message : t("todoDeleteFailed"), "error");
    }
  }

  // "Ausblenden" on a todo's red tracked-change highlight: keeps the todo, just stops
  // marking it as changed/added/pending-delete. A pending-delete ghost is hard-deleted
  // server-side, so it disappears from the list entirely.
  async function acceptTodoTrackedChange(protocolElementBlockId: string, todoId: string) {
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
      if (err instanceof Error) showToast(err.message, "error");
    }
  }

  async function uploadImage(protocolElementBlockId: string, includeGps = true) {
    const file = selectedFiles[protocolElementBlockId];
    if (!file) return;
    setStatus(protocolElementBlockId, "saving");
    try {
      // Vorab-Abgleich per SHA-256: ein im Mandanten schon vorhandenes Bild würde der Server
      // ohnehin als Duplikat ablehnen - dann gar nicht erst übertragen.
      if (await isAlreadyUploadedLazy(file, "protocol_image")) {
        setStatus(protocolElementBlockId, "error");
        showToast(t("imageAlreadyExists"), "error");
        return;
      }
      const body = new FormData();
      body.append("file", file);
      if (!includeGps) body.append("include_gps", "false");
      const created = await browserApiFetch<ProtocolImage>(`/api/protocol-element-blocks/${protocolElementBlockId}/images`, {
        method: "POST",
        body
      });
      const next = [...(imagesByBlock[protocolElementBlockId] ?? []), created].sort((left, right) => left.sort_index - right.sort_index);
      setImagesByBlock((current) => ({ ...current, [protocolElementBlockId]: next }));
      collab.sendFieldUpdate(`block-${protocolElementBlockId}-images`, next);
      setSelectedFiles((current) => ({ ...current, [protocolElementBlockId]: null }));
      setStatus(protocolElementBlockId, "saved");
      const similarNotice = imageSimilarityNotice(created, tRoot);
      if (similarNotice) showToast(similarNotice, "info");
    } catch (err: unknown) {
      setStatus(protocolElementBlockId, "error");
      showToast(err instanceof Error ? err.message : t("imageUploadFailed"), "error");
    }
  }

  async function deleteImage(protocolElementBlockId: string, imageId: string) {
    const ok = await confirm({
      message: t("imageDeleteConfirm"),
      tone: "danger",
      confirmLabel: tCommon("delete")
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
      showToast(err instanceof Error ? err.message : t("imageDeleteFailed"), "error");
    }
  }

  async function createEventFromBlock(protocolElementBlockId: string, blockConfig: Record<string, any>, draftOverride?: ProtocolEventDraft): Promise<EventSummary | null> { // i18n-ok: TS-Generic-Signatur, kein UI-Text
    // Tag aus dem Filter des Blocks (Terminliste: event_filter, Wiederholung: repeat_event_filter).
    const configuredTag = eventFilterTagText(normalizeEventFilter(blockConfig.event_filter ?? blockConfig.repeat_event_filter));
    const allowEndDate = blockConfig.event_allow_end_date === true;
    const draft = draftOverride ?? newEventDrafts[protocolElementBlockId] ?? createProtocolEventDraft(protocol.protocol_date, configuredTag);
    if (!draft.event_date.trim() || !draft.title.trim()) {
      setStatus(protocolElementBlockId, "error");
      return null;
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
          // Keine cycle_assignments: das Backend ordnet den Termin nach seinem eigenen Datum zu.
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
      showToast(err instanceof Error ? err.message : t("eventCreateFailed"), "error");
      return null;
    }
  }

  // Terminänderungen aus Terminübersicht/Detailformular kommen pro Tastendruck. Parallel
  // abgeschickt konnte eine ältere Anfrage die neuere überholen - auf dem Server und beim
  // Übernehmen der Antwort -, die Eingabe ging dann teilweise verloren (Bug 2026-11-08). Darum
  // je Termin: sofort lokal anzeigen, nacheinander speichern, und was während einer laufenden
  // Anfrage dazukommt, in einer einzigen Folgeanfrage zusammenfassen.
  const queuedEventPatches = useRef(new Map<string, EventPatch>());
  const queuedEventSaves = useRef(new Map<string, Promise<boolean>>());
  const confirmedEvents = useRef(new Map<string, EventSummary>());

  function updateEventFromBlock(protocolElementBlockId: string, eventId: string, patch: EventPatch): Promise<boolean> {  // i18n-ok: TS-Generic-Signatur, kein UI-Text
    setEvents((current) => current.map((event) => {
      if (event.id !== eventId) return event;
      if (!confirmedEvents.current.has(eventId)) confirmedEvents.current.set(eventId, event);
      return { ...event, ...patch };
    }));
    setStatus(protocolElementBlockId, "saving");
    const queued = queuedEventPatches.current.get(eventId);
    queuedEventPatches.current.set(eventId, mergeEventPatches(queued, patch));
    const pending = queuedEventSaves.current.get(eventId);
    if (queued && pending) return pending;
    const save = runSerializedByKey(`event:${eventId}`, async () => {
      const body = queuedEventPatches.current.get(eventId) ?? {};
      queuedEventPatches.current.delete(eventId);
      if (queuedEventSaves.current.get(eventId) === save) queuedEventSaves.current.delete(eventId);
      try {
        const updated = await browserApiFetch<EventSummary>(`/api/events/${eventId}`, {
          method: "PATCH",
          body: JSON.stringify(body),
        });
        // Steht schon die nächste Änderung an, bleibt die lokale (neuere) Fassung stehen.
        if (!queuedEventPatches.current.has(eventId)) {
          confirmedEvents.current.delete(eventId);
          setEvents((current) => current.map((event) => (event.id === eventId ? updated : event)));
        } else {
          confirmedEvents.current.set(eventId, updated);
        }
        collab.sendFieldUpdate("event-updated", updated);
        setStatus(protocolElementBlockId, "saved");
        return true;
      } catch (err: unknown) {
        setStatus(protocolElementBlockId, "error");
        showToast(err instanceof Error ? err.message : t("eventSaveFailed"), "error");
        // Lokal schon angezeigte Änderung auf den zuletzt bestätigten Stand zurücksetzen
        const confirmed = confirmedEvents.current.get(eventId);
        if (confirmed && !queuedEventPatches.current.has(eventId)) {
          confirmedEvents.current.delete(eventId);
          setEvents((list) => list.map((event) => (event.id === eventId ? confirmed : event)));
        }
        return false;
      }
    });
    queuedEventSaves.current.set(eventId, save);
    return save;
  }

  async function deleteEventFromBlock(protocolElementBlockId: string, eventId: string) {
    setStatus(protocolElementBlockId, "saving");
    try {
      await browserApiFetch(`/api/events/${eventId}`, { method: "DELETE" });
      setEvents((current) => current.filter((event) => event.id !== eventId));
      collab.sendFieldUpdate("event-deleted", { id: eventId });
      setStatus(protocolElementBlockId, "saved");
    } catch (err: unknown) {
      setStatus(protocolElementBlockId, "error");
      showToast(err instanceof Error ? err.message : t("eventDeleteFailed"), "error");
    }
  }

  function openEventContextMenu(nativeEvent: React.MouseEvent, eventRow: EventSummary, protocolElementBlockId: string) {
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
  async function refreshBlockListSnapshot(blockId: string) {
    try {
      const updated = await browserApiFetch<ProtocolElement["blocks"][number]>(
        `/api/protocol-element-blocks/${blockId}/list-snapshot/refresh`,
        { method: "POST" }
      );
      updateBlockInState(blockId, (block) => ({ ...block, configuration_snapshot_json: updated.configuration_snapshot_json, config_version: updated.config_version }));
      void refreshElementTitles();
      collab.sendFieldUpdate("element-titles", null);
    } catch (err: unknown) {
      if (err instanceof Error) showToast(err.message, "error");
    }
  }

  async function undoBlockListSnapshot(blockId: string) {
    try {
      const updated = await browserApiFetch<ProtocolElement["blocks"][number]>(
        `/api/protocol-element-blocks/${blockId}/list-snapshot/undo`,
        { method: "POST" }
      );
      updateBlockInState(blockId, (block) => ({ ...block, configuration_snapshot_json: updated.configuration_snapshot_json, config_version: updated.config_version }));
      void refreshElementTitles();
      collab.sendFieldUpdate("element-titles", null);
    } catch (err: unknown) {
      if (err instanceof Error) showToast(err.message, "error");
    }
  }

  // "Ausblenden" on one whole-list entry's or row-link row's red tracked-change highlight.
  async function acceptTrackedListEntry(blockId: string, entryId: string) {
    try {
      const updated = await browserApiFetch<ProtocolElement["blocks"][number]>(
        `/api/protocol-element-blocks/${blockId}/list-snapshot/entries/${entryId}/accept-tracked-change`,
        { method: "POST" }
      );
      updateBlockInState(blockId, (block) => ({ ...block, configuration_snapshot_json: updated.configuration_snapshot_json, config_version: updated.config_version }));
    } catch (err: unknown) {
      if (err instanceof Error) showToast(err.message, "error");
    }
  }

  async function acceptTrackedRow(blockId: string, rowId: string) {
    try {
      const updated = await browserApiFetch<ProtocolElement["blocks"][number]>(
        `/api/protocol-element-blocks/${blockId}/rows/${rowId}/accept-tracked-change`,
        { method: "POST" }
      );
      updateBlockInState(blockId, (block) => ({ ...block, configuration_snapshot_json: updated.configuration_snapshot_json, config_version: updated.config_version }));
    } catch (err: unknown) {
      if (err instanceof Error) showToast(err.message, "error");
    }
  }

  // Silent resync called right after this protocol itself writes to a linked list entry
  // (see createListEntryFromBlock/updateListEntryFromBlock/deleteListEntryFromBlock below),
  // so the editor never shows a stale hint for a change it just made itself. Best-effort:
  // a failure here just leaves a stale badge until the next sync/manual refresh, never
  // corrupts data.
  async function syncBlockListSnapshot(blockId: string) {
    try {
      const updated = await browserApiFetch<ProtocolElement["blocks"][number]>(
        `/api/protocol-element-blocks/${blockId}/list-snapshot/sync`,
        { method: "POST" }
      );
      updateBlockInState(blockId, (block) => ({ ...block, configuration_snapshot_json: updated.configuration_snapshot_json, config_version: updated.config_version }));
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
      if (err instanceof Error) showToast(err.message, "error");
    }
  }

  // The "Liste bearbeiten" planning popup intentionally manages the live list directly
  // (not the protocol's frozen snapshot) - but listEntriesByDefinition is otherwise only
  // ever populated once at page load and patched locally by this protocol's own writes,
  // so it goes stale the moment the list changes through any other route (another tab,
  // another protocol, or this block's own "Daten aktualisieren"). Refetch right before
  // opening the popup so it always starts from the real current list state.
  async function refreshListEntries(listDefinitionId: string) {
    try {
      const publicId = listPublicIds[listDefinitionId] ?? listDefinitionId;
      const fresh = await browserApiFetch<StructuredListEntry[]>(`/api/lists/${publicId}/entries`);
      setListEntriesByDefinition((current) => ({ ...current, [listDefinitionId]: fresh }));
    } catch {
      // best-effort - popup falls back to whatever was cached
    }
  }

  async function createListEntryFromBlock(
    protocolElementBlockId: string,
    listDefinitionId: string,
    payload: { sort_index: number; values: ListValues }
  ) {
    setStatus(protocolElementBlockId, "saving");
    try {
      const publicId = listPublicIds[listDefinitionId] ?? listDefinitionId;
      const created = await browserApiFetch<StructuredListEntry>(`/api/lists/${publicId}/entries`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setListEntriesByDefinition((current) => ({
        ...current,
        [listDefinitionId]: [...(current[listDefinitionId] ?? []), created].sort(
          (left, right) => left.sort_index - right.sort_index || left.created_at.localeCompare(right.created_at)
        ),
      }));
      setStatus(protocolElementBlockId, "saved");
      void syncBlockListSnapshot(protocolElementBlockId);
      return true;
    } catch (err: unknown) {
      setStatus(protocolElementBlockId, "error");
      showToast(err instanceof Error ? err.message : t("entryCreateFailed"), "error");
      return false;
    }
  }

  async function updateListEntryFromBlock(
    protocolElementBlockId: string,
    listDefinitionId: string,
    entryId: string,
    payload: Partial<{ sort_index: number; values: ListValues }>
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
      showToast(err instanceof Error ? err.message : t("entrySaveFailed"), "error");
      return false;
    }
  }

  async function deleteListEntryFromBlock(protocolElementBlockId: string, listDefinitionId: string, entryId: string) {
    const ok = await confirm({
      message: t("entryDeleteConfirm"),
      tone: "danger",
      confirmLabel: tCommon("delete")
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
      showToast(err instanceof Error ? err.message : t("entryDeleteFailed"), "error");
    }
  }

  // Termin einer Serie entfernen bzw. wieder anhaken. ``manually_hidden`` merkt sich die Wahl:
  // ein entfernter Termin bleibt als unsichtbarer Block stehen und wird in Folgeprotokollen
  // derselben Vorlage für diesen Punkt nicht neu erzeugt (protocol_service._manually_hidden_event_ids),
  // ein wieder angehakter schon. Vertagen löscht die Blöcke dagegen (removeEventBlock).
  async function setEventBlockVisible(blockId: string, visible: boolean) {
    const block = elements.flatMap((e) => e.blocks).find((b) => b.id === blockId);
    if (!block) return;
    const newConfig = { ...(block.configuration_snapshot_json ?? {}), manually_hidden: !visible };
    updateBlockInState(blockId, (b) => ({ ...b, is_visible_snapshot: visible, configuration_snapshot_json: newConfig }));
    try {
      const updated = await browserApiFetch<ProtocolElement["blocks"][number]>(`/api/protocol-element-blocks/${blockId}`, {
        method: "PATCH",
        body: JSON.stringify({ is_visible_snapshot: visible, configuration_snapshot_json: newConfig, expected_config_version: block.config_version }),
      });
      updateBlockInState(blockId, (b) => ({ ...b, config_version: updated.config_version }));
    } catch (err: unknown) {
      if (applyConfigConflict(blockId, err)) return;
      updateBlockInState(blockId, (b) => ({ ...b, is_visible_snapshot: block.is_visible_snapshot, configuration_snapshot_json: block.configuration_snapshot_json }));
      showToast(err instanceof Error ? err.message : t(visible ? "eventShowFailed" : "eventHideFailed"), "error");
    }
  }

  function unhideEventBlock(blockId: string) {
    return setEventBlockVisible(blockId, true);
  }

  function hideEventBlock(blockId: string) {
    return setEventBlockVisible(blockId, false);
  }

  async function removeEventBlock(blockId: string) {
    // Optimistic removal, rolled back on failure by re-inserting the removed block into its
    // original element at its original position - mirrors the rollback pattern used for todo
    // updates in todos/todo-list-view.tsx.
    let removedFrom: { elementId: string; block: ProtocolElement["blocks"][number]; index: number } | null = null;
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
      showToast(err instanceof Error ? err.message : t("eventRemoveFailed"), "error");
    }
  }

  async function handleQuickTodoCreated(blockId: string, _todoId: string, elementId: string) {
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

  // Transaktion im Block «Transaktionen» erfassen: verknüpft mit diesem Protokoll, Liste und
  // Kontostand (auch «am Protokolldatum») werden sofort nachgeführt
  async function addFinanceTransaction(
    accountId: string,
    values: { transaction_date: string; description: string; amount: number }
  ): Promise<boolean> {
    try {
      const created = await browserApiFetch<FinanceTransaction>(`/api/finance/accounts/${accountId}/transactions`, {
        method: "POST",
        body: JSON.stringify({ ...values, protocol_id: protocol.id }),
      });
      setFinanceTransactions((current) => ({
        ...current,
        [accountId]: [created, ...(current[accountId] ?? [])].sort((a, b) => b.transaction_date.localeCompare(a.transaction_date)),
      }));
      setAccounts((current) => current.map((account) => (account.id === accountId ? { ...account, balance: account.balance + created.amount } : account)));
      setFinanceVersion((value) => value + 1);
      showToast(tRoot("transactionAdded"), "success");
      return true;
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : tRoot("transactionAddFailed"), "error");
      return false;
    }
  }

  async function deleteFinanceTransaction(accountId: string, transactionId: string) {
    const transaction = (financeTransactions[accountId] ?? []).find((tx) => tx.id === transactionId);
    try {
      await browserApiFetch(`/api/finance/transactions/${transactionId}`, { method: "DELETE" });
      setFinanceTransactions((current) => ({ ...current, [accountId]: (current[accountId] ?? []).filter((tx) => tx.id !== transactionId) }));
      if (transaction) {
        setAccounts((current) => current.map((account) => (account.id === accountId ? { ...account, balance: account.balance - transaction.amount } : account)));
      }
      setFinanceVersion((value) => value + 1);
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : tRoot("transactionDeleteFailed"), "error");
    }
  }

  async function addEventBlockToElement(elementId: string, eventId: string): Promise<ProtocolElement["blocks"][number] | null> {
    try {
      // Alle Blöcke, die das Element pro Termin vorsieht (Vorlagen pro Termin)
      const newBlocks = await browserApiFetch<ProtocolElement["blocks"]>(
        `/api/protocol-elements/${elementId}/blocks/from-event`,
        {
          method: "POST",
          body: JSON.stringify({ event_id: eventId }),
        }
      );
      setElements((current) =>
        current.map((element) =>
          element.id === elementId
            ? { ...element, blocks: [...element.blocks, ...newBlocks] }
            : element
        )
      );
      return newBlocks[0] ?? null;
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : t("eventAddFailed"), "error");
      return null;
    }
  }

  // Stabile Handler fuer die memoisierten Punkte (FocusedElementEditor): ohne sie bekäme jeder
  // Punkt bei jedem Render neue Funktionen und renderte bei jedem Tastendruck mit.
  // Personen, auf die gespeicherte Formular-/Matrixwerte verweisen, die aber weder in der Vorlage
  // noch im Verzeichnis stehen: Namen liefert der Server je Block mit (participant_names), sonst
  // erschien nur «N ausgewählt». Über einen Schlüssel stabil gehalten, damit Tippen (neue
  // elements) nicht jedes Mal alle Leser des Kontexts neu rendert.
  const snapshotNamesKey = useMemo(() => {
    const names: Record<string, string> = {};
    for (const element of elements) {
      for (const block of element.blocks) Object.assign(names, block.participant_names ?? {});
    }
    return JSON.stringify(Object.entries(names).sort(([a], [b]) => a.localeCompare(b)));
  }, [elements]);
  const directoryWithSnapshotNames = useMemo(() => {
    const extra = (JSON.parse(snapshotNamesKey) as Array<[string, string]>)
      .filter(([id]) => !participantDirectory.some((participant) => participant.id === id))
      .map(([id, display_name]): ParticipantSummary => ({
        id, tenant_id: protocol.tenant_id ?? "", first_name: null, last_name: null, display_name, email: null,
        is_active: false, joined_at: null, left_at: null, created_at: "", updated_at: "",
      }));
    return extra.length ? [...participantDirectory, ...extra] : participantDirectory;
  }, [snapshotNamesKey, participantDirectory, protocol.tenant_id]);

  // «Nicht im PDF»: neu abfragen, wenn sich Struktur, Exportschalter oder Leer/Gefüllt ändern
  const pdfCoverageKey = useMemo(
    () => pdfCoverageSignature(elements, textDraftStore.getAll(), todosByBlock, imagesByBlock),
    // textDraftEmptiness: nur der Wechsel leer/gefüllt zählt, nicht jede Taste
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [elements, textDraftEmptiness, todosByBlock, imagesByBlock, textDraftStore]
  );
  const pdfCoverage = usePdfCoverage(protocol.id, pdfCoverageKey);

  // Gliederung (S5): eigene memoisierte Komponente mit stabilen Einträgen. Der Schlüssel hängt
  // nur an Titeln, Reihenfolge und Zählern (Pendenzen, Anwesenheit) - nie am getippten Text.
  const attendanceTotal = useMemo(
    () => attendanceParticipants(availableParticipants, protocol.protocol_date ?? undefined).length,
    [availableParticipants, protocol.protocol_date]
  );
  const outlineKey = visibleElements
    .map((element) => [
      element.id,
      element.section_name_snapshot,
      outlineSummary(element, {
        attendance: attendanceTally,
        attendanceTotal,
        todoCount: (blockId) => (todosByBlock[blockId] ?? []).filter((todo) => !todo.pending_delete).length,
        t: (key, values) => (key.startsWith("outline") ? t(key as "outlineSummaryTodos", values) : tRoot(key as "blockTypeText", values)),
      }),
      element.is_visible_snapshot ? "" : "1",
    ].join("\u0001"))
    .join("\u0002");
  const outlineItems = useMemo<OutlineItem[]>(
    () => (outlineKey ? outlineKey.split("\u0002").map((entry) => {
      const [id, title, summary, hidden] = entry.split("\u0001");
      return { id, title, summary, hidden: hidden === "1" };
    }) : []),
    [outlineKey]
  );
  const outlineHandlers = useStableCallbacks({
    // Schmales Fenster: nach der Wahl eines Punkts die überlagerte Gliederung schliessen
    selectElement: (elementId: string) => {
      setOutlineOpen(false);
      focusElement(elementId);
    },
    reorderElements,
  });

  const elementHandlers = useStableCallbacks({
    activateBlock,
    saveBlockConfiguration,
    saveAttendanceStatus,
    updateBlockInState,
    handleTextChange,
    addTodo,
    updateTodo,
    deleteTodo,
    collectTodoAsSubmission,
    acceptTodoTrackedChange,
    acceptTrackedListEntry,
    acceptTrackedRow,
    acceptTextTrackedChanges,
    createEventFromBlock,
    updateEventFromBlock,
    deleteEventFromBlock,
    uploadImage,
    deleteImage,
    createListEntryFromBlock,
    updateListEntryFromBlock,
    deleteListEntryFromBlock,
    refreshBlockListSnapshot,
    refreshListEntries,
    undoBlockListSnapshot,
    unhideEventBlock,
    hideEventBlock,
    removeEventBlock,
    addEventBlockToElement,
    addFinanceTransaction,
    deleteFinanceTransaction,
    openEventContextMenu,
    handleQuickTodoCreated,
    onPendingUpdate: (updated: Partial<TodoListItem> & { id: string }) => setPendingTodos((prev) => prev.map((t) => t.id === updated.id ? { ...t, ...updated } : t)),
    onPendingDone: (todoId: string) => setPendingTodos((prev) => prev.filter((t) => t.id !== todoId)),
  });

  const dockHandlers = useStableCallbacks({ toggleDrawer, closeDrawer });
  // Traktanden für «Zu Punkt» (Pendenz, Anliegen), ohne den festen Punkt «Sitzungsnotizen»
  const drawerSectionsKey = visibleElements
    .filter((element) => trimSectionName(element.section_name_snapshot).toLowerCase() !== "sitzungsnotizen") // i18n-ok: fester Elementname aus dem Backend
    .map((element) => `${element.id}\u0001${element.section_name_snapshot}`)
    .join("\u0002");
  const drawerSections = useMemo(
    () => (drawerSectionsKey ? drawerSectionsKey.split("\u0002").map((entry) => {
      const [id, name] = entry.split("\u0001");
      return { id, name };
    }) : []),
    [drawerSectionsKey]
  );

  // «Status zurücksetzen» (F22, wie im Menü der Protokollliste): mit meetings.edit; ein
  // abgeschlossenes Protokoll nur mit meetings.approve und nach Rückfrage
  const revertTarget = !forceReadOnly && (protocolStatus !== "abgeschlossen" || canApprove)
    ? (({ vorbereitet: "geplant", durchgeführt: "vorbereitet", abgeschlossen: "durchgeführt" } as Record<string, string>)[protocolStatus] ?? null)
    : null;
  async function revertStatus() {
    if (!revertTarget || reverting) return;
    const ok = await confirm({
      title: protocolStatus === "abgeschlossen" ? tBuilder("revertClosedConfirmTitle") : t("revertConfirmTitle"),
      message: protocolStatus === "abgeschlossen"
        ? tBuilder("revertClosedConfirmMessage")
        : t("revertConfirmMessage", { status: protocolStatusLabel(revertTarget, tRoot) }),
      tone: protocolStatus === "abgeschlossen" ? "danger" : undefined,
      confirmLabel: tBuilder("revertClosedConfirmLabel"),
    });
    if (!ok) return;
    setReverting(true);
    try {
      if (!(await flushPendingSaves())) {
        showToast(t("statusChangeUnsavedChanges"), "error");
        return;
      }
      const updated = await browserApiFetch<ProtocolSummary>(`/api/protocols/${protocol.id}/revert-status`, { method: "POST" });
      setProtocolStatus(updated.status);
      collab.sendStatusChanged(updated.status);
      showToast(tBuilder("statusChanged", { status: protocolStatusLabel(updated.status, tRoot) }), "success");
      router.refresh();
    } catch (err: unknown) {
      showToast(err instanceof Error && err.message ? err.message : tBuilder("revertFailed"), "error");
    } finally {
      setReverting(false);
    }
  }

  // Kopf (memoisiert): stabile Handler und Knoten, damit er beim Tippen nicht neu rendert (S5)
  const headerHandlers = useStableCallbacks({
    transitionStatus,
    setTrackChangesEnabled: (enabled: boolean) => void setTrackChangesEnabled(enabled),
    reloadFromTemplate: () => void reloadFromTemplate(),
    openSearch: () => setSearchOpen(true),
    openPdf: () => openOrGeneratePdf(protocol),
    showSaveError: () => {
      const element = errorBlockId ? visibleElements.find((item) => item.blocks.some((block) => block.id === errorBlockId)) : null;
      if (element) focusElement(element.id);
    },
  });
  const presenceBar = useMemo(
    () => <CollaborationPresenceBar users={collab.otherPresence} connected={collab.connected} />,
    [collab.otherPresence, collab.connected]
  );
  const outlineToggle = useMemo(
    () => (
      <button
        type="button"
        className="button-secondary protocol-outline-toggle"
        aria-expanded={outlineOpen}
        aria-controls="protocol-outline-pane"
        onClick={() => setOutlineOpen((open) => !open)}
      >
        {t("header.outlineToggle")}
      </button>
    ),
    [outlineOpen, t]
  );

  return (
    <ParticipantDateContext.Provider value={protocol.protocol_date ?? null}>
    <ParticipantDirectoryContext.Provider value={directoryWithSnapshotNames}>
    {/* data-own-find: Ctrl+F öffnet hier die Kapitelsuche des Editors, nicht die Listensuche der Shell */}
    <div className="grid protocol-editor" data-own-find>
      <ProtocolHeader
        title={protocol.title || protocol.protocol_number}
        protocolNumber={protocol.protocol_number}
        createdAt={protocol.created_at}
        templateVersion={protocol.template_version}
        status={protocolStatus}
        statusLabel={protocolStatusLabel(protocolStatus, tRoot)}
        modeLabel={workflowMeta[protocolStatus]?.modeLabel ?? ""}
        isReadOnly={isReadOnly}
        ctaLabel={!isReadOnly ? workflowMeta[protocolStatus]?.ctaLabel || undefined : undefined}
        ctaBusy={transitioningStatus}
        onCta={headerHandlers.transitionStatus}
        trackChangesVisible={protocolStatus === "geplant" && !isReadOnly}
        trackChangesEnabled={trackChangesEnabled}
        onTrackChangesChange={headerHandlers.setTrackChangesEnabled}
        // Vorlage seit Erstellen/letztem Abgleich geändert: nur solange noch nicht durchgeführt
        templateChangeVisible={!isReadOnly && templateChangedSinceSync({ ...protocol, status: protocolStatus })}
        templateChangeBusy={templateSyncing}
        onTemplateReload={headerHandlers.reloadFromTemplate}
        importSourceUrl={protocol.import_source_url ?? null}
        onOpenSearch={headerHandlers.openSearch}
        pdfBusy={!!pdfBusyByProtocol[protocol.id]}
        onOpenPdf={headerHandlers.openPdf}
        protocolId={protocol.id}
        presence={presenceBar}
        saveState={saveState}
        onShowSaveError={headerHandlers.showSaveError}
        outlineToggle={outlineToggle}
      />

      <StatusTransitionDialog
        open={transitionDialogOpen}
        title={transitionCopy.title}
        message={transitionCopy.message}
        confirmLabel={workflowMeta[protocolStatus]?.ctaLabel ?? ""}
        otherEditors={collab.otherPresence.map((user) => user.display_name)}
        busy={transitioningStatus}
        onCancel={() => setTransitionDialogOpen(false)}
        onConfirm={() => {
          setTransitionDialogOpen(false);
          void performStatusTransition();
        }}
      />

      <div className={`protocol-workspace${outlineOpen ? " protocol-workspace-outline-open" : ""}`}>
        <div
          className="protocol-outline-pane"
          id="protocol-outline-pane"
          onKeyDown={(event) => {
            if (event.key !== "Escape" || !outlineOpen || event.defaultPrevented) return;
            event.preventDefault();
            setOutlineOpen(false);
            document.querySelector<HTMLElement>(".protocol-outline-toggle")?.focus();
          }}
        >
          <ProtocolOutline
            items={outlineItems}
            selectedId={selectedElementId}
            canReorder={!isReadOnly}
            onSelect={outlineHandlers.selectElement}
            onReorder={outlineHandlers.reorderElements}
          />
        </div>

        <div className="protocol-main">
          <div className="protocol-doc" ref={documentRef}>
            <div className="protocol-doc-inner">
              {protocolStatus === "abgeschlossen" && (
                <div className="protocol-frozen-banner" role="status">
                  <strong>{t("frozenBannerTitle")}</strong>
                  <span>{t("frozenBannerText")}</span>
                </div>
              )}
              {visibleElements.length === 0 && (
                <div className="editor-panel-empty">
                  <div>
                    <div className="eyebrow">{t("noItemsEyebrow")}</div>
                    <h3>{t("noVisibleSectionsMessage")}</h3>
                  </div>
                </div>
              )}
              {visibleElements.map((element, index) => (
                <FocusedElementEditor
                  key={element.id}
                  pdfElementCoverage={pdfCoverage.elements[element.id]}
                  pdfBlockCoverage={pdfCoverage.blocks}
                  tagConfig={tagConfig}
                  updateTagColor={updateTagColor}
                  renameTag={renameTag}
                  collab={collab.fieldLocks}
                  trackChangesActive={trackChangesActive}
                  element={element}
                  elementIndex={index}
                  textDraftStore={textDraftStore}
                  activeBlockId={activeBlock?.elementId === element.id ? activeBlock.blockId : null}
                  onActivateBlock={elementHandlers.activateBlock}
                  todosByBlock={todosByBlock}
                  sessionTodos={sessionTodosByElement[element.id] ?? EMPTY_TODOS}
                  imagesByBlock={imagesByBlock}
                  newTodoTask={newTodoTask}
                  browserApiBaseUrl={browserApiBaseUrl}
                  protocol={protocol}
                  sessionNotes={sessionNotes}
                  availableParticipants={availableParticipants}
                  availableEvents={events}
                  availableTemplates={availableTemplates}
                  availableAccounts={accounts}
                  financeTransactions={financeTransactions}
                  financeVersion={financeVersion}
                  canManageFinances={canManageFinances}
                  addFinanceTransaction={elementHandlers.addFinanceTransaction}
                  deleteFinanceTransaction={elementHandlers.deleteFinanceTransaction}
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
                  saveBlockConfiguration={elementHandlers.saveBlockConfiguration}
                  saveAttendanceStatus={elementHandlers.saveAttendanceStatus}
                  updateBlockInState={elementHandlers.updateBlockInState}
                  handleTextChange={elementHandlers.handleTextChange}
                  forceEditable={forceEditable}
                  isReadOnly={isReadOnly}
                  addTodo={elementHandlers.addTodo}
                  updateTodo={elementHandlers.updateTodo}
                  deleteTodo={elementHandlers.deleteTodo}
                  collectTodoAsSubmission={canCollectSubmissions && !isReadOnly ? elementHandlers.collectTodoAsSubmission : undefined}
                  acceptTodoTrackedChange={elementHandlers.acceptTodoTrackedChange}
                  acceptTrackedListEntry={elementHandlers.acceptTrackedListEntry}
                  acceptTrackedRow={elementHandlers.acceptTrackedRow}
                  acceptTextTrackedChanges={elementHandlers.acceptTextTrackedChanges}
                  createEventFromBlock={elementHandlers.createEventFromBlock}
                  updateEventFromBlock={elementHandlers.updateEventFromBlock}
                  deleteEventFromBlock={elementHandlers.deleteEventFromBlock}
                  onEventContextMenu={elementHandlers.openEventContextMenu}
                  uploadImage={elementHandlers.uploadImage}
                  deleteImage={elementHandlers.deleteImage}
                  listDefinitionsById={listDefinitionsById}
                  listEntriesByDefinition={listEntriesByDefinition}
                  createListEntryFromBlock={elementHandlers.createListEntryFromBlock}
                  updateListEntryFromBlock={elementHandlers.updateListEntryFromBlock}
                  deleteListEntryFromBlock={elementHandlers.deleteListEntryFromBlock}
                  refreshBlockListSnapshot={elementHandlers.refreshBlockListSnapshot}
                  refreshListEntries={elementHandlers.refreshListEntries}
                  undoBlockListSnapshot={elementHandlers.undoBlockListSnapshot}
                  todoTagFilter={todoTagFilter}
                  setTodoTagFilter={setTodoTagFilter}
                  newTodoTags={newTodoTags}
                  setNewTodoTags={setNewTodoTags}
                  isPlanningMode={isPlanningMode}
                  unhideEventBlock={elementHandlers.unhideEventBlock}
                  hideEventBlock={elementHandlers.hideEventBlock}
                  removeEventBlock={elementHandlers.removeEventBlock}
                  addEventBlockToElement={elementHandlers.addEventBlockToElement}
                  onQuickTodoCreated={elementHandlers.handleQuickTodoCreated}
                  pendingTodos={pendingTodos}
                  onPendingUpdate={elementHandlers.onPendingUpdate}
                  onPendingDone={elementHandlers.onPendingDone}
                  agendaSlot={agendaSlots[element.id]}
                />
              ))}
              <AgendaItemsSection
                items={agendaByElement.other}
                isReadOnly={isReadOnly}
                heading={tAgenda("editor.otherTitle")}
                {...agendaSectionHandlers}
              />
            </div>
          </div>

          <ProtocolDock open={drawer} readOnly={isReadOnly} onToggle={dockHandlers.toggleDrawer} />
          <ProtocolDrawer open={drawer} onClose={dockHandlers.closeDrawer} handlesEscape={drawer === "agenda" || drawer === "status"} drawerRef={drawerRef}>
            {/* Notizen und Pendenz bleiben eingehängt (Entwürfe, wartende Speicherung), nur verborgen */}
            <SessionPanel
              ref={sessionPanelRef}
              protocol={protocol}
              participants={availableParticipants}
              dueEvents={sessionDueEvents}
              currentSectionName={selectedElement ? trimSectionName(selectedElement.section_name_snapshot) : null}
              onSessionNotesChange={setSessionNotes}
              onQuickTodoCreated={elementHandlers.handleQuickTodoCreated}
              todoFines={todoFines}
              canCollectSubmissions={canCollectSubmissions}
              active={drawer === "notes" || drawer === "todo" ? drawer : null}
              onClose={dockHandlers.closeDrawer}
              readOnly={isReadOnly}
              sections={drawerSections}
            />
            {drawer === "agenda" && !isReadOnly ? (
              <AgendaQuickCreateForm
                protocolId={protocol.id}
                sections={drawerSections}
                defaultSectionId={selectedElement?.id ?? null}
                onCreated={(created) => setAgendaItems((current) => [...current.filter((item) => item.id !== created.id), created])}
              />
            ) : null}
            {drawer === "status" ? (
              <ProtocolStatusDrawer
                others={collab.otherPresence}
                selfWhere={selectedElement ? selectedElement.section_name_snapshot : null}
                connected={collab.connected}
                attendance={attendanceTally}
                revertToLabel={revertTarget ? protocolStatusLabel(revertTarget, tRoot) : null}
                reverting={reverting}
                onRevert={() => void revertStatus()}
              />
            ) : null}
          </ProtocolDrawer>
        </div>
      </div>

      {agendaPostponeItem && (
        <AgendaPostponeModal
          item={agendaPostponeItem}
          onClose={() => setAgendaPostponeItem(null)}
          onPostponed={() => void reloadAgendaItems()}
        />
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
            {eventContextMenu.eventRow.is_cancelled ? t("uncancelEventOption") : t("markAsCancelledOption")}
          </button>
        </div>,
        document.body
      )}

      <ProtocolSearchModal
        open={searchOpen}
        onClose={() => setSearchOpen(false)}
        onSelect={focusElement}
        elements={visibleElements}
        todosByBlock={todosByBlock}
        textDrafts={searchOpen ? textDraftStore.getAll() : EMPTY_TEXT_DRAFTS}
        protocolNumber={protocol.protocol_number}
      />
    </div>
    </ParticipantDirectoryContext.Provider>
    </ParticipantDateContext.Provider>
  );
}
