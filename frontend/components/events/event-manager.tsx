"use client";

import { ChangeEvent, FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Badge } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal } from "@/components/ui/modal";
import { computePopoverPosition, Popover, usePopoverDismiss } from "@/components/ui/popover";
import { SearchInput } from "@/components/ui/search-input";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { EventDetailForm } from "@/components/protocol/planning/event-detail-form";
import { browserApiFetch } from "@/lib/api/client";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { useTableSort } from "@/lib/hooks/use-table-sort";
import { useTagConfig } from "@/lib/hooks/use-tag-config";
import { getCycleYear } from "@/lib/utils/cycle";
import { formatDate, formatDateRange } from "@/lib/utils/format";
import {
  CycleAssignment,
  CycleConfigSummary,
  CycleInfo,
  DocumentTemplate,
  EventImportPreview,
  EventSummary,
  ParticipantSummary,
  TemplateSummary,
} from "@/types/api";

const PAGE_SIZE = 100;

type CsvTargetField = "event_date" | "event_end_date" | "tag" | "title" | "description" | "participant_count";

const CSV_TARGET_FIELDS: { field: CsvTargetField; label: string; required?: boolean }[] = [
  { field: "event_date", label: "Startdatum", required: true },
  { field: "event_end_date", label: "Enddatum" },
  { field: "tag", label: "Tag" },
  { field: "title", label: "Titel", required: true },
  { field: "description", label: "Beschreibung" },
  { field: "participant_count", label: "Teilnehmerzahl" },
];

type OptionalColumnKey =
  | "is_cancelled"
  | "participant_count"
  | "location"
  | "organizer_ids"
  | "leadership_ids"
  | "participant_ids"
  | "spezial1_ids"
  | "spezial2_ids"
  | "spezial3_ids"
  | "spezial_text1"
  | "spezial_text2"
  | "spezial_text3";

const OPTIONAL_COLUMNS: { key: OptionalColumnKey; label: string }[] = [
  { key: "is_cancelled", label: "Abgesagt" },
  { key: "participant_count", label: "Teilnehmerzahl" },
  { key: "location", label: "Standort" },
  { key: "organizer_ids", label: "Organisatoren" },
  { key: "leadership_ids", label: "Leitungsteam" },
  { key: "participant_ids", label: "Teilnehmer (Liste)" },
  { key: "spezial1_ids", label: "Spezial 1" },
  { key: "spezial2_ids", label: "Spezial 2" },
  { key: "spezial3_ids", label: "Spezial 3" },
  { key: "spezial_text1", label: "Spezial Text 1" },
  { key: "spezial_text2", label: "Spezial Text 2" },
  { key: "spezial_text3", label: "Spezial Text 3" },
];

type Props = {
  initialEvents: EventSummary[];
  documentTemplates?: DocumentTemplate[];
  availableParticipants?: ParticipantSummary[];
};

type ParticipantPickerField = "organizer_ids" | "leadership_ids" | "participant_ids" | "spezial1_ids" | "spezial2_ids" | "spezial3_ids";

const PARTICIPANT_ROLE_FIELDS: { field: ParticipantPickerField; label: string }[] = [
  { field: "organizer_ids", label: "Organisatoren" },
  { field: "leadership_ids", label: "Leitungsteam" },
  { field: "participant_ids", label: "Teilnehmer" },
  { field: "spezial1_ids", label: "Spezial 1" },
  { field: "spezial2_ids", label: "Spezial 2" },
  { field: "spezial3_ids", label: "Spezial 3" },
];

type FlatCycle = CycleInfo & { cycle_config_id: string; config_name: string };

type EventFormState = {
  id?: string;
  event_date: string;
  event_end_date: string;
  tag: string;
  title: string;
  description: string;
  participant_count: string;
  is_cancelled: boolean;
  cycle_assignments: CycleAssignment[];
  organizer_ids: string[];
  leadership_ids: string[];
  participant_ids: string[];
  spezial1_ids: string[];
  spezial2_ids: string[];
  spezial3_ids: string[];
  location: string;
  spezial_text1: string;
  spezial_text2: string;
  spezial_text3: string;
};

function emptyForm(): EventFormState {
  return {
    event_date: new Date().toISOString().slice(0, 10),
    event_end_date: "",
    tag: "",
    title: "",
    description: "",
    participant_count: "0",
    is_cancelled: false,
    cycle_assignments: [],
    organizer_ids: [],
    leadership_ids: [],
    participant_ids: [],
    spezial1_ids: [],
    spezial2_ids: [],
    spezial3_ids: [],
    location: "",
    spezial_text1: "",
    spezial_text2: "",
    spezial_text3: "",
  };
}

export function EventManager({ initialEvents, documentTemplates = [], availableParticipants = [] }: Props) {
  const showToast = useToast();
  const confirm = useConfirm();
  const [events, setEvents] = useState(initialEvents);
  const [hasMore, setHasMore] = useState(initialEvents.length === PAGE_SIZE);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [search, setSearch] = useState("");
  const [tagFilter, setTagFilter] = useState("all");
  const [showPast, setShowPast] = useState(true);
  const { sortKey, sortDirection, toggleSort, sortIndicator } = useTableSort<"event_date" | "title" | "tag" | "description" | "participant_count">("event_date");
  const [visibleColumns, setVisibleColumns] = useState<Set<OptionalColumnKey>>(new Set());
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState<EventFormState>(emptyForm);
  const [todayIso, setTodayIso] = useState("0000-01-01");
  const [detailEvent, setDetailEvent] = useState<EventSummary | null>(null);
  const { tagConfig, updateTagColor, renameTag } = useTagConfig();
  const [cycleConfigs, setCycleConfigs] = useState<CycleConfigSummary[]>([]);
  const [showAllPeriods, setShowAllPeriods] = useState(false);
  const [availableCycles, setAvailableCycles] = useState<FlatCycle[]>([]);
  const [cyclesLoading, setCyclesLoading] = useState(false);
  const cyclesLoadedRef = useRef(false);

  const [pickerField, setPickerField] = useState<ParticipantPickerField | null>(null);
  const [pickerSelected, setPickerSelected] = useState<string[]>([]);
  const [pickerSearch, setPickerSearch] = useState("");

  const [eventContextMenu, setEventContextMenu] = useState<{ x: number; y: number; event: EventSummary } | null>(null);

  const [viewMenuOpen, setViewMenuOpen] = useState(false);
  const viewMenuTriggerRef = useRef<HTMLButtonElement | null>(null);

  const [showImportModal, setShowImportModal] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importColumnMap, setImportColumnMap] = useState<Partial<Record<CsvTargetField, string>>>({});
  const [importPreview, setImportPreview] = useState<EventImportPreview | null>(null);
  const [importPreviewLoading, setImportPreviewLoading] = useState(false);
  const [importCommitting, setImportCommitting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);

  const landscapeTemplates = documentTemplates.filter(
    (t) => t.is_active && (t.configuration_json as { options?: { orientation?: string } })?.options?.orientation === "landscape"
  );

  // Export modal state
  const [exportModalOpen, setExportModalOpen] = useState(false);
  const [exportTemplateId, setExportTemplateId] = useState<string | "">(landscapeTemplates[0]?.id ?? "");
  const [exportBusy, setExportBusy] = useState(false);
  const [exportUrl, setExportUrl] = useState<string | null>(null);
  const [templateDropdownOpen, setTemplateDropdownOpen] = useState(false);
  const templateDropdownRef = useRef<HTMLDivElement>(null);

  usePopoverDismiss(templateDropdownOpen, () => setTemplateDropdownOpen(false), [templateDropdownRef]);
  const [exportTagFilters, setExportTagFilters] = useState<string[]>([]);
  const [exportTagSearch, setExportTagSearch] = useState("");
  const [exportDateMode, setExportDateMode] = useState<"all" | "next-session" | "until-event">("all");
  const [exportUntilEventId, setExportUntilEventId] = useState<string | "">("");

  const knownExportTags = useMemo(() => {
    const set = new Set<string>();
    events.forEach((e) => { if (e.tag) set.add(e.tag); });
    return Array.from(set).sort();
  }, [events]);

  const tagSuggestions = useMemo(() => {
    if (!exportTagSearch.trim()) return [];
    const q = exportTagSearch.toLowerCase();
    return knownExportTags.filter((t) => t.toLowerCase().includes(q) && !exportTagFilters.includes(t));
  }, [exportTagSearch, knownExportTags, exportTagFilters]);

  const nextSessionEvent = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10);
    return events.find((e) => e.event_date >= today && e.tag?.toLowerCase().includes("sitzung")) ?? null;
  }, [events]);

  const sortedEvents = useMemo(() => [...events].sort((a, b) => a.event_date.localeCompare(b.event_date)), [events]);

  function toggleExportTag(tag: string) {
    setExportTagFilters((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]
    );
    setExportUrl(null);
  }

  function getUntilDate(): string | null {
    if (exportDateMode === "all") return null;
    if (exportDateMode === "next-session") return nextSessionEvent?.event_date ?? null;
    if (exportDateMode === "until-event" && exportUntilEventId) {
      const ev = events.find((e) => e.id === exportUntilEventId);
      return ev?.event_date ?? null;
    }
    return null;
  }

  function triggerDownload(url: string) {
    const a = document.createElement("a");
    a.href = `${url}?download=1`;
    a.target = "_blank";
    a.rel = "noreferrer";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  async function handlePdfClick() {
    if (exportBusy) return;
    if (exportUrl) { triggerDownload(exportUrl); return; }
    if (!exportTemplateId) return;
    setExportBusy(true);
    try {
      const result = await browserApiFetch<{ content_url?: string | null }>("/api/exports/events", {
        method: "POST",
        body: JSON.stringify({
          template_id: exportTemplateId,
          tag_filters: exportTagFilters,
          until_date: getUntilDate(),
        }),
      });
      const url = result.content_url ?? null;
      setExportUrl(url);
      if (url) triggerDownload(url);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "PDF-Export fehlgeschlagen", "error");
    } finally {
      setExportBusy(false);
    }
  }

  useEffect(() => {
    setTodayIso(new Date().toISOString().slice(0, 10));
  }, []);

  useEffect(() => {
    browserApiFetch<CycleConfigSummary[]>("/api/cycle-configs")
      .then((configs) => setCycleConfigs(configs ?? []))
      .catch(() => setCycleConfigs([]));
  }, []);

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

  async function ensureCyclesLoaded() {
    if (cyclesLoadedRef.current) return;
    cyclesLoadedRef.current = true;
    setCyclesLoading(true);
    try {
      const configs = cycleConfigs.length > 0 ? cycleConfigs : await browserApiFetch<CycleConfigSummary[]>("/api/cycle-configs");
      const cycleGroups = await Promise.all(
        (configs ?? []).map((cfg) =>
          browserApiFetch<CycleInfo[]>(`/api/cycle-configs/${cfg.id}/cycles`).then((cycles) =>
            (cycles ?? []).map((c) => ({ ...c, cycle_config_id: cfg.id, config_name: cfg.name }))
          ).catch(() => [] as FlatCycle[])
        )
      );
      setAvailableCycles(cycleGroups.flat());
    } catch (error) {
      cyclesLoadedRef.current = false;
      showToast(error instanceof Error ? error.message : "Zyklen konnten nicht geladen werden", "error");
    } finally {
      setCyclesLoading(false);
    }
  }

  const knownTags = useMemo(
    () =>
      Array.from(
        new Set(
          events
            .map((event) => (event.tag ?? "").trim())
            .filter((tag) => tag.length > 0)
        )
      ).sort((left, right) => left.localeCompare(right)),
    [events]
  );
  function isInCurrentPeriod(event: EventSummary): boolean {
    if (!event.cycle_assignments || event.cycle_assignments.length === 0 || cycleConfigs.length === 0) {
      return true;
    }
    return event.cycle_assignments.some((assignment) => {
      const config = cycleConfigs.find((c) => c.id === assignment.cycle_config_id);
      if (!config) return true;
      return assignment.cycle_year === getCycleYear(todayIso, config.reset_month, config.reset_day);
    });
  }

  const filteredEvents = useMemo(() => {
    const query = search.trim().toLowerCase();
    return [...events]
      .filter((event) => {
        if (!showPast) {
          const effectiveEndDate = event.event_end_date || event.event_date;
          if (effectiveEndDate < todayIso) {
            return false;
          }
        }
        if (!showAllPeriods && !isInCurrentPeriod(event)) {
          return false;
        }
        if (tagFilter !== "all" && (event.tag ?? "") !== tagFilter) {
          return false;
        }
        if (!query) {
          return true;
        }
        const haystack = `${event.title} ${event.tag ?? ""} ${event.description ?? ""}`.toLowerCase();
        return haystack.includes(query);
      })
      .sort((left, right) => {
        const direction = sortDirection === "asc" ? 1 : -1;
        if (sortKey === "event_date") {
          const leftValue = left.event_date;
          const rightValue = right.event_date;
          return leftValue.localeCompare(rightValue) * direction;
        }
        if (sortKey === "participant_count") {
          return ((left.participant_count ?? 0) - (right.participant_count ?? 0)) * direction;
        }
        const leftValue = String(left[sortKey] ?? "").toLowerCase();
        const rightValue = String(right[sortKey] ?? "").toLowerCase();
        return leftValue.localeCompare(rightValue) * direction;
      });
  }, [cycleConfigs, events, search, showAllPeriods, showPast, sortDirection, sortKey, tagFilter, todayIso]);

  function openCreate() {
    setForm(emptyForm());
    void ensureCyclesLoaded();
    setModalOpen(true);
  }

  async function updateEventDetail(eventId: string, patch: Partial<EventSummary>) {
    const previous = events.find((event) => event.id === eventId) ?? null;
    setEvents((current) => current.map((event) => (event.id === eventId ? { ...event, ...patch } : event)));
    try {
      const updated = await browserApiFetch<EventSummary>(`/api/events/${eventId}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      setEvents((current) => current.map((event) => (event.id === eventId ? updated : event)));
    } catch (error) {
      if (previous) {
        setEvents((current) => current.map((event) => (event.id === eventId ? previous : event)));
      }
      showToast(error instanceof Error ? error.message : "Termin konnte nicht aktualisiert werden", "error");
    }
  }

  function openParticipantPicker(field: ParticipantPickerField) {
    setPickerField(field);
    setPickerSelected([...(form[field] as string[])]);
    setPickerSearch("");
  }

  function applyParticipantPicker() {
    if (!pickerField) return;
    setForm((current) => ({ ...current, [pickerField]: pickerSelected }));
    setPickerField(null);
  }

  function participantLabel(ids: string[]): string {
    if (!ids.length) return "Auswählen…";
    const names = ids
      .map((id) => availableParticipants.find((p) => p.id === id)?.display_name)
      .filter(Boolean);
    return names.length ? names.join(", ") : `${ids.length} ausgewählt`;
  }

  function formatParticipantNames(ids: string[] | null | undefined): ReactNode {
    if (!ids || ids.length === 0) return <span className="muted">–</span>;
    const names = ids
      .map((id) => availableParticipants.find((p) => p.id === id)?.display_name)
      .filter(Boolean);
    return names.length ? names.join(", ") : <span className="muted">{ids.length} ausgewählt</span>;
  }

  const optionalColumnRenderers: Record<OptionalColumnKey, (item: EventSummary) => ReactNode> = {
    is_cancelled: (item) =>
      item.is_cancelled ? <Badge variant="danger">Abgesagt</Badge> : <span className="muted">–</span>,
    participant_count: (item) => item.participant_count ?? 0,
    location: (item) => item.location || <span className="muted">–</span>,
    organizer_ids: (item) => formatParticipantNames(item.organizer_ids),
    leadership_ids: (item) => formatParticipantNames(item.leadership_ids),
    participant_ids: (item) => formatParticipantNames(item.participant_ids),
    spezial1_ids: (item) => formatParticipantNames(item.spezial1_ids),
    spezial2_ids: (item) => formatParticipantNames(item.spezial2_ids),
    spezial3_ids: (item) => formatParticipantNames(item.spezial3_ids),
    spezial_text1: (item) => item.spezial_text1 || <span className="muted">–</span>,
    spezial_text2: (item) => item.spezial_text2 || <span className="muted">–</span>,
    spezial_text3: (item) => item.spezial_text3 || <span className="muted">–</span>,
  };

  const activeOptionalColumns = OPTIONAL_COLUMNS.filter((column) => visibleColumns.has(column.key));

  function toggleCycle(cycleConfigId: string, cycleYear: number) {
    setForm((current) => {
      const exists = current.cycle_assignments.some(
        (a) => a.cycle_config_id === cycleConfigId && a.cycle_year === cycleYear
      );
      const next = exists
        ? current.cycle_assignments.filter((a) => !(a.cycle_config_id === cycleConfigId && a.cycle_year === cycleYear))
        : [...current.cycle_assignments, { cycle_config_id: cycleConfigId, cycle_year: cycleYear }];
      return { ...current, cycle_assignments: next };
    });
  }

  async function saveEvent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const payload = {
        event_date: form.event_date,
        event_end_date: form.event_end_date || null,
        tag: form.tag || null,
        title: form.title,
        description: form.description || null,
        participant_count: Math.max(0, Number(form.participant_count || "0")),
        is_cancelled: form.is_cancelled,
        cycle_assignments: form.cycle_assignments,
        organizer_ids: form.organizer_ids,
        leadership_ids: form.leadership_ids,
        participant_ids: form.participant_ids,
        spezial1_ids: form.spezial1_ids,
        spezial2_ids: form.spezial2_ids,
        spezial3_ids: form.spezial3_ids,
        location: form.location || null,
        spezial_text1: form.spezial_text1 || null,
        spezial_text2: form.spezial_text2 || null,
        spezial_text3: form.spezial_text3 || null,
      };
      const saved = form.id
        ? await browserApiFetch<EventSummary>(`/api/events/${form.id}`, {
            method: "PATCH",
            body: JSON.stringify(payload),
          })
        : await browserApiFetch<EventSummary>("/api/events", {
            method: "POST",
            body: JSON.stringify(payload),
          });

      setEvents((current) =>
        form.id ? current.map((item) => (item.id === saved.id ? saved : item)) : [saved, ...current]
      );
      setModalOpen(false);
      showToast(form.id ? "Termin gespeichert" : "Termin erstellt", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Termin konnte nicht gespeichert werden", "error");
    }
  }

  async function deleteEvent(eventId: string) {
    const ok = await confirm({
      message: "Termin endgültig löschen? Das entfernt ihn aus allen Protokollen.",
      tone: "danger",
      confirmLabel: "Löschen"
    });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/events/${eventId}`, { method: "DELETE" });
      setEvents((current) => current.filter((event) => event.id !== eventId));
      showToast("Termin gelöscht", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Termin konnte nicht gelöscht werden", "error");
    }
  }

  async function toggleCancelled(item: EventSummary) {
    const nextValue = !item.is_cancelled;
    setEvents((current) => current.map((event) => (event.id === item.id ? { ...event, is_cancelled: nextValue } : event)));
    try {
      await browserApiFetch<EventSummary>(`/api/events/${item.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_cancelled: nextValue }),
      });
    } catch (error) {
      setEvents((current) => current.map((event) => (event.id === item.id ? { ...event, is_cancelled: item.is_cancelled } : event)));
      showToast(error instanceof Error ? error.message : "Termin konnte nicht aktualisiert werden", "error");
    }
  }

  function openEventContextMenu(nativeEvent: React.MouseEvent, item: EventSummary) {
    nativeEvent.preventDefault();
    nativeEvent.stopPropagation();
    setEventContextMenu({ x: nativeEvent.clientX, y: nativeEvent.clientY, event: item });
  }

  async function loadMore() {
    setIsLoadingMore(true);
    try {
      const next = await browserApiFetch<EventSummary[]>(`/api/events?skip=${events.length}&limit=${PAGE_SIZE}`);
      setEvents((current) => [...current, ...next]);
      setHasMore(next.length === PAGE_SIZE);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Weitere Termine konnten nicht geladen werden", "error");
    } finally {
      setIsLoadingMore(false);
    }
  }

  const loadMoreSentinelRef = useInfiniteScroll({
    hasMore,
    isLoading: isLoadingMore,
    onLoadMore: () => void loadMore(),
  });

  function toggleColumn(key: OptionalColumnKey) {
    setVisibleColumns((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  function openImportModal() {
    setImportFile(null);
    setImportPreview(null);
    setImportColumnMap({});
    setImportError(null);
    setShowImportModal(true);
  }

  async function requestImportPreview(file: File, columnMap: Partial<Record<CsvTargetField, string>>) {
    setImportPreviewLoading(true);
    setImportError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      if (Object.keys(columnMap).length > 0) {
        body.append("column_map", JSON.stringify(columnMap));
      }
      const preview = await browserApiFetch<EventImportPreview>("/api/events/import-csv/preview", {
        method: "POST",
        body,
      });
      setImportPreview(preview);
      if (Object.keys(columnMap).length === 0) {
        setImportColumnMap(preview.resolved_map as Partial<Record<CsvTargetField, string>>);
      }
    } catch (error) {
      setImportError(error instanceof Error ? error.message : "Vorschau fehlgeschlagen");
      setImportPreview(null);
    } finally {
      setImportPreviewLoading(false);
    }
  }

  function handleImportFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setImportFile(file);
    setImportColumnMap({});
    setImportPreview(null);
    void requestImportPreview(file, {});
  }

  function updateColumnMapping(field: CsvTargetField, header: string) {
    if (!importFile) return;
    const next = { ...importColumnMap, [field]: header };
    setImportColumnMap(next);
    void requestImportPreview(importFile, next);
  }

  async function confirmImport() {
    if (!importFile || !importPreview) return;
    setImportCommitting(true);
    try {
      const body = new FormData();
      body.append("file", importFile);
      body.append("column_map", JSON.stringify(importColumnMap));
      const imported = await browserApiFetch<EventSummary[]>("/api/events/import-csv", {
        method: "POST",
        body,
      });
      setEvents((current) => [...imported, ...current]);
      showToast(`${imported.length} Termine importiert`, "success");
      setShowImportModal(false);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "CSV-Import fehlgeschlagen", "error");
    } finally {
      setImportCommitting(false);
    }
  }

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">Termine</h1>
          <p className="muted">Alle Termine dieses Mandanten.</p>
        </div>
        <div className="table-toolbar-actions">
          <button type="button" className="button-inline button-ghost" onClick={openImportModal}>
            CSV Import
          </button>
          {landscapeTemplates.length > 0 && (
            <button type="button" className="button-inline button-ghost" onClick={() => setExportModalOpen(true)}>
              Export
            </button>
          )}
          <div className="mini-menu mini-menu-compact mini-menu-end">
            <button
              ref={viewMenuTriggerRef}
              type="button"
              className={`mini-menu-trigger${viewMenuOpen ? " mini-menu-trigger-open" : ""}`}
              onClick={() => setViewMenuOpen((value) => !value)}
              aria-haspopup="menu"
              aria-expanded={viewMenuOpen}
            >
              <span className="mini-menu-trigger-label">Ansicht</span>
              <span className="mini-menu-trigger-icon">⌄</span>
            </button>
            <Popover open={viewMenuOpen} onOpenChange={setViewMenuOpen} anchorRef={viewMenuTriggerRef} align="end" className="mini-menu-popover-portal">
              <div className="mini-menu-section">
                <div className="mini-menu-section-title">Filter</div>
                <label className="mini-menu-option">
                  <span>Vergangene Termine anzeigen</span>
                  <input type="checkbox" checked={showPast} onChange={(event) => setShowPast(event.target.checked)} />
                </label>
                {cycleConfigs.length > 0 && (
                  <label className="mini-menu-option">
                    <span>Alle Zyklus-Perioden anzeigen</span>
                    <input
                      type="checkbox"
                      checked={showAllPeriods}
                      onChange={(event) => setShowAllPeriods(event.target.checked)}
                    />
                  </label>
                )}
              </div>
              <div className="mini-menu-section">
                <div className="mini-menu-section-title">Zusätzliche Spalten</div>
                {OPTIONAL_COLUMNS.map((column) => (
                  <label key={column.key} className="mini-menu-option">
                    <span>{column.label}</span>
                    <input
                      type="checkbox"
                      checked={visibleColumns.has(column.key)}
                      onChange={() => toggleColumn(column.key)}
                    />
                  </label>
                ))}
              </div>
            </Popover>
          </div>
          <button type="button" className="button-inline" onClick={openCreate}>
            Neuer Termin
          </button>
        </div>
      </div>

      <div className="list-filter-row">
        <FilterTabs
          options={[{ value: "all", label: "Alle" }, ...knownTags.map((tag) => ({ value: tag, label: tag }))]}
          value={tagFilter}
          onChange={setTagFilter}
        />
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder="Termine durchsuchen" />
        </div>
      </div>

      <div className="status-row">
        <span className="pill">{filteredEvents.length} sichtbar</span>
        <span className="pill">{events.length} gesamt</span>
        <span className="pill">{knownTags.length} Tags</span>
      </div>

      <DataTable
        className="data-table-lg"
        columns={[
          { key: "event_date", label: "Datum", sortable: true, sortDirection: sortIndicator("event_date"), onSort: () => toggleSort("event_date") },
          { key: "title", label: "Titel", sortable: true, sortDirection: sortIndicator("title"), onSort: () => toggleSort("title") },
          { key: "tag", label: "Tag", sortable: true, sortDirection: sortIndicator("tag"), onSort: () => toggleSort("tag") },
          ...activeOptionalColumns.map((column) =>
            column.key === "participant_count"
              ? {
                  key: column.key,
                  label: column.label,
                  sortable: true,
                  sortDirection: sortIndicator("participant_count"),
                  onSort: () => toggleSort("participant_count"),
                }
              : { key: column.key, label: column.label }
          ),
          { key: "description", label: "Beschreibung", sortable: true, sortDirection: sortIndicator("description"), onSort: () => toggleSort("description") },
          "Aktionen",
        ]}
      >
        {filteredEvents.map((item) => (
          <tr
            key={item.id}
            className={`table-row-clickable${visibleColumns.has("is_cancelled") && item.is_cancelled ? " table-row-cancelled" : ""}`}
            onClick={() => setDetailEvent(item)}
            onContextMenu={(event) => openEventContextMenu(event, item)}
          >
            <td>{formatDateRange(item.event_date, item.event_end_date)}</td>
            <td>
              <strong>{item.title}</strong>
            </td>
            <td>{item.tag ? <span className="pill">{item.tag}</span> : <span className="muted">Kein Tag</span>}</td>
            {activeOptionalColumns.map((column) => (
              <td key={column.key}>{optionalColumnRenderers[column.key](item)}</td>
            ))}
            <td className="table-cell-wrap">{item.description ?? <span className="muted">Keine Beschreibung</span>}</td>
            <td>
              <div className="table-actions table-actions-start">
                <button
                  type="button"
                  className="button-inline button-danger"
                  onClick={(clickEvent) => {
                    clickEvent.stopPropagation();
                    void deleteEvent(item.id);
                  }}
                >
                  Löschen
                </button>
              </div>
            </td>
          </tr>
        ))}
      </DataTable>

      {hasMore && (
        <div className="load-more-row" ref={loadMoreSentinelRef}>
          {isLoadingMore ? (
            <span className="muted">Lädt weitere Termine…</span>
          ) : (
            <button type="button" className="button-inline button-ghost" onClick={() => void loadMore()}>
              Mehr laden ({events.length} geladen)
            </button>
          )}
        </div>
      )}

      <Modal
        open={showImportModal}
        onClose={() => setShowImportModal(false)}
        title="Termine aus CSV importieren"
        description="Ordne die Spalten deiner Datei den Termin-Feldern zu und prüfe die Vorschau, bevor du importierst."
        size="wide"
      >
        <div className="grid" style={{ gap: "18px" }}>
          {!importFile ? (
            <label className="csv-import-dropzone" style={{ cursor: "pointer" }}>
              <strong>CSV-Datei auswählen</strong>
              <span className="muted">Pflichtspalten: Startdatum und Titel. Trennzeichen Komma, Semikolon oder Tab.</span>
              <input type="file" accept=".csv,text/csv" onChange={handleImportFileChange} hidden />
            </label>
          ) : (
            <div className="csv-import-file-row">
              <span>
                <strong>{importFile.name}</strong>
                <span className="muted"> · {importPreview ? `${importPreview.rows.length} Zeile(n) erkannt` : "wird gelesen…"}</span>
              </span>
              <label className="button-inline button-ghost" style={{ width: "auto", minHeight: 0, padding: "6px 14px", cursor: "pointer" }}>
                Andere Datei
                <input type="file" accept=".csv,text/csv" onChange={handleImportFileChange} hidden />
              </label>
            </div>
          )}

          <details className="card import-help-card">
            <summary className="import-help-summary">
              <span>CSV-Format anzeigen</span>
              <span className="muted">Pflicht: Startdatum und Titel</span>
            </summary>
            <div className="import-help-body">
              <p className="muted">
                Unterstützte Spalten sind z. B. `Startdatum` oder `Datum`, optional `Enddatum`, `Tag`, `Titel`, `Beschreibung` und `Teilnehmerzahl`.
                Die Spaltennamen müssen nicht exakt passen – ordne sie unten einfach den passenden Termin-Feldern zu.
              </p>
              <pre>{`Startdatum;Enddatum;Tag;Titel;Beschreibung;Teilnehmerzahl
2026-04-29;;Sitzung;Leiterrunde;Planung Sommerlager;8
12.07.2026;18.07.2026;Lager;Sommerlager;;42`}</pre>
            </div>
          </details>

          {importError && <p style={{ color: "var(--danger)" }}>{importError}</p>}

          {importFile && importPreview && (
            <>
              <div className="csv-import-mapping-grid">
                {CSV_TARGET_FIELDS.map((target) => (
                  <label key={target.field} className="field-stack csv-import-mapping-field">
                    <span className="field-label">
                      {target.label}
                      {target.required && <span className="csv-import-required">*</span>}
                    </span>
                    <SearchableSelect
                      className={!importColumnMap[target.field] ? "mapping-unmapped" : undefined}
                      options={importPreview.detected_columns}
                      getId={(column) => column}
                      getLabel={(column) => column}
                      value={importColumnMap[target.field] ?? null}
                      onChange={(column) => updateColumnMapping(target.field, column ?? "")}
                      nullLabel="– nicht zuordnen –"
                    />
                  </label>
                ))}
              </div>

              <div className="status-row">
                <Badge variant="success">{importPreview.valid_count} gültig</Badge>
                {importPreview.error_count > 0 && <Badge variant="danger">{importPreview.error_count} mit Fehlern</Badge>}
                <span className="pill">{importPreview.rows.length} Zeile(n) gesamt</span>
                {importPreviewLoading && <span className="muted">Aktualisiere Vorschau…</span>}
              </div>

              <DataTable columns={["#", "Startdatum", "Enddatum", "Tag", "Titel", "Beschreibung", "Teilnehmer", "Status"]}>
                {importPreview.rows.map((row) => (
                  <tr key={row.row_number} className={row.error ? "table-row-error" : undefined}>
                    <td>{row.row_number}</td>
                    <td>{row.event_date ? formatDate(row.event_date) : <span className="muted">–</span>}</td>
                    <td>{row.event_end_date ? formatDate(row.event_end_date) : <span className="muted">–</span>}</td>
                    <td>{row.tag ? <span className="pill">{row.tag}</span> : <span className="muted">–</span>}</td>
                    <td>{row.title ?? <span className="muted">–</span>}</td>
                    <td>{row.description ?? <span className="muted">–</span>}</td>
                    <td>{row.participant_count ?? <span className="muted">–</span>}</td>
                    <td>
                      {row.error ? (
                        <Badge variant="danger">{row.error}</Badge>
                      ) : (
                        <Badge variant="success">Gültig</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </DataTable>

              <div className="table-actions" style={{ justifyContent: "flex-end" }}>
                <button type="button" className="button-inline button-ghost" onClick={() => setShowImportModal(false)}>
                  Abbrechen
                </button>
                <button
                  type="button"
                  className="button-inline"
                  disabled={
                    importCommitting ||
                    importPreviewLoading ||
                    importPreview.rows.length === 0 ||
                    importPreview.error_count > 0
                  }
                  onClick={() => void confirmImport()}
                >
                  {importCommitting ? "Importiert…" : `${importPreview.valid_count} Termine importieren`}
                </button>
              </div>
            </>
          )}
        </div>
      </Modal>

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={form.id ? "Termin bearbeiten" : "Termin erstellen"}
        description="Der Tag hilft spaeter beim Verknuepfen mit passenden Protokollpunkten."
      >
        <form className="grid" onSubmit={saveEvent}>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Startdatum</span>
              <DateInput value={form.event_date} onChange={(value) => setForm((current) => ({ ...current, event_date: value }))} required />
            </label>
            <label className="field-stack">
              <span className="field-label">Enddatum</span>
              <DateInput value={form.event_end_date} onChange={(value) => setForm((current) => ({ ...current, event_end_date: value }))} />
              <span className="field-help">Leer lassen fuer einen einzelnen Tag.</span>
            </label>
          </div>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Tag</span>
              <input
                value={form.tag}
                onChange={(event) => setForm((current) => ({ ...current, tag: event.target.value }))}
                placeholder="z. B. Sitzung, Lager, Elternabend"
                list="event-tag-suggestions"
              />
              <datalist id="event-tag-suggestions">
                {knownTags.map((tag) => (
                  <option key={tag} value={tag} />
                ))}
              </datalist>
            </label>
            <label className="field-stack">
              <span className="field-label">Titel</span>
              <input value={form.title} onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))} required />
            </label>
          </div>
          <label className="field-stack">
            <span className="field-label">Anzahl Teilnehmer</span>
            <input
              type="number"
              min="0"
              value={form.participant_count}
              onChange={(event) => setForm((current) => ({ ...current, participant_count: event.target.value }))}
            />
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={form.is_cancelled}
              onChange={(event) => setForm((current) => ({ ...current, is_cancelled: event.target.checked }))}
            />
            Termin abgesagt
          </label>
          <label className="field-stack">
            <span className="field-label">Beschreibung</span>
            <textarea rows={5} value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} />
          </label>
          <label className="field-stack">
            <span className="field-label">Standort</span>
            <input value={form.location} onChange={(e) => setForm((current) => ({ ...current, location: e.target.value }))} placeholder="z. B. Gemeinschaftshaus, Sportplatz" />
          </label>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Spezial Text 1</span>
              <input value={form.spezial_text1} onChange={(e) => setForm((current) => ({ ...current, spezial_text1: e.target.value }))} />
            </label>
            <label className="field-stack">
              <span className="field-label">Spezial Text 2</span>
              <input value={form.spezial_text2} onChange={(e) => setForm((current) => ({ ...current, spezial_text2: e.target.value }))} />
            </label>
          </div>
          <label className="field-stack">
            <span className="field-label">Spezial Text 3</span>
            <input value={form.spezial_text3} onChange={(e) => setForm((current) => ({ ...current, spezial_text3: e.target.value }))} />
          </label>
          {availableParticipants.length > 0 && (
            <div className="field-stack">
              <span className="field-label">Personen</span>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                {PARTICIPANT_ROLE_FIELDS.map(({ field, label }) => (
                  <div key={field} className="field-stack" style={{ gap: 4 }}>
                    <span className="field-label" style={{ fontSize: "0.78rem" }}>{label}</span>
                    <button
                      type="button"
                      className="button-ghost structured-list-picker"
                      onClick={() => openParticipantPicker(field)}
                      style={{ textAlign: "left", minHeight: 36, padding: "6px 10px", fontSize: "0.85rem" }}
                    >
                      {participantLabel(form[field] as string[])}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="field-stack">
            <span className="field-label">Zyklen</span>
            {cyclesLoading ? (
              <span className="muted" style={{ fontSize: "0.85rem" }}>Zyklen werden geladen…</span>
            ) : availableCycles.length === 0 ? (
              <span className="muted" style={{ fontSize: "0.85rem" }}>Keine Zyklen verfügbar (Zyklen unter Struktur → Zyklen anlegen)</span>
            ) : (
              <div className="cycle-chip-list">
                {availableCycles.map((cycle) => {
                  const active = form.cycle_assignments.some(
                    (a) => a.cycle_config_id === cycle.cycle_config_id && a.cycle_year === cycle.cycle_year
                  );
                  return (
                    <button
                      key={`${cycle.cycle_config_id}-${cycle.cycle_year}`}
                      type="button"
                      className={`cycle-chip${active ? " cycle-chip-active" : ""}`}
                      onClick={() => toggleCycle(cycle.cycle_config_id, cycle.cycle_year)}
                    >
                      {cycle.name}
                    </button>
                  );
                })}
              </div>
            )}
            <span className="field-help">Zyklen, denen dieser Termin zugeordnet werden soll. Optional.</span>
          </div>
          <button type="submit">{form.id ? "Termin speichern" : "Termin erstellen"}</button>
        </form>
      </Modal>

      <Modal
        open={Boolean(detailEvent)}
        onClose={() => setDetailEvent(null)}
        title={detailEvent?.title || "Termin"}
        description={detailEvent ? formatDateRange(detailEvent.event_date, detailEvent.event_end_date) : undefined}
        size="wide"
      >
        {detailEvent ? (
          <EventDetailForm
            event={detailEvent}
            allowEndDate
            availableParticipants={availableParticipants}
            knownEventTags={knownTags}
            tagConfig={tagConfig}
            onTagColorChange={updateTagColor}
            onTagRename={renameTag}
            onUpdate={(patch) => {
              setDetailEvent((current) => (current ? { ...current, ...patch } : current));
              return updateEventDetail(detailEvent.id, patch);
            }}
          />
        ) : null}
      </Modal>

      <Modal
        open={Boolean(pickerField)}
        onClose={() => setPickerField(null)}
        title={PARTICIPANT_ROLE_FIELDS.find((r) => r.field === pickerField)?.label ?? "Teilnehmer wählen"}
        description="Mehrfachauswahl"
      >
        <div className="grid">
          <label className="field-stack">
            <span className="field-label">Suche</span>
            <input
              value={pickerSearch}
              onChange={(e) => setPickerSearch(e.target.value)}
              placeholder="Teilnehmer filtern"
            />
          </label>
          <div className="participant-check-grid">
            {availableParticipants
              .filter((p) => !pickerSearch.trim() || p.display_name.toLowerCase().includes(pickerSearch.toLowerCase()))
              .map((p) => {
                const checked = pickerSelected.includes(p.id);
                return (
                  <label key={p.id} className={`participant-check-card${checked ? " participant-check-card-active" : ""}`}>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) =>
                        setPickerSelected((current) =>
                          e.target.checked ? [...current, p.id] : current.filter((id) => id !== p.id)
                        )
                      }
                    />
                    <span>{p.display_name}</span>
                  </label>
                );
              })}
          </div>
          <div className="table-toolbar-actions">
            <button type="button" className="button-inline" onClick={applyParticipantPicker}>
              Auswahl übernehmen
            </button>
          </div>
        </div>
      </Modal>

      <Modal open={exportModalOpen} title="Termine exportieren" onClose={() => setExportModalOpen(false)}>
        <div style={{ display: "grid", gap: "24px" }}>

          {knownExportTags.length > 0 && (
            <div className="field-stack">
              <span className="field-label">Tags</span>
              <div style={{ position: "relative" }}>
                <input
                  style={{ width: "100%", minHeight: 0, padding: "7px 12px", borderRadius: "10px", fontSize: "0.875rem", border: "1px solid var(--border)", background: "var(--surface, var(--panel-solid))", color: "var(--text)", outline: "none" }}
                  placeholder="Tag suchen…"
                  value={exportTagSearch}
                  onChange={(e) => setExportTagSearch(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Tab" && tagSuggestions.length > 0) {
                      e.preventDefault();
                      toggleExportTag(tagSuggestions[0]);
                      setExportTagSearch("");
                    } else if (e.key === "Enter" && tagSuggestions.length > 0) {
                      toggleExportTag(tagSuggestions[0]);
                      setExportTagSearch("");
                    } else if (e.key === "Escape") {
                      setExportTagSearch("");
                    }
                  }}
                />
                {tagSuggestions.length > 0 && (
                  <div style={{
                    position: "absolute", top: "calc(100% + 4px)", left: 0, right: 0, zIndex: 100,
                    background: "var(--panel-solid)", border: "1px solid var(--border)",
                    borderRadius: "10px", boxShadow: "0 8px 24px rgba(0,0,0,0.28)",
                    overflow: "hidden",
                  }}>
                    {tagSuggestions.map((tag, i) => (
                      <button
                        key={tag}
                        type="button"
                        onMouseDown={(e) => { e.preventDefault(); toggleExportTag(tag); setExportTagSearch(""); }}
                        style={{
                          display: "flex", alignItems: "center", justifyContent: "space-between",
                          width: "100%", minHeight: 0, padding: "9px 12px", textAlign: "left",
                          background: i === 0 ? "color-mix(in srgb, var(--accent) 12%, var(--panel-solid) 88%)" : "var(--panel-solid)",
                          color: "var(--text)", fontSize: "0.9rem", border: "none",
                          borderBottom: i < tagSuggestions.length - 1 ? "1px solid var(--border)" : "none",
                          cursor: "pointer", borderRadius: 0,
                        }}
                      >
                        <span>{tag}</span>
                        {i === 0 && <span style={{ fontSize: "0.72rem", color: "var(--muted)", background: "var(--surface, var(--accent-soft))", padding: "2px 6px", borderRadius: "4px", border: "1px solid var(--border)" }}>Tab</span>}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <div className="tag-filter-bar">
                {exportTagFilters.map((tag) => (
                  <button key={tag} type="button" className="tag-filter-chip tag-filter-chip-active"
                    onClick={() => toggleExportTag(tag)}
                    style={{ width: "auto", minHeight: 0, padding: "4px 12px", display: "inline-flex", fontSize: "0.85rem" }}
                  >{tag} ×</button>
                ))}
                {knownExportTags.filter((t) => !exportTagFilters.includes(t)).map((tag) => (
                  <button key={tag} type="button" className="tag-filter-chip"
                    onClick={() => toggleExportTag(tag)}
                    style={{ width: "auto", minHeight: 0, padding: "4px 12px", display: "inline-flex", fontSize: "0.85rem" }}
                  >{tag}</button>
                ))}
              </div>
            </div>
          )}

          <div className="field-stack">
            <span className="field-label">Zeitraum</span>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
              {(["all", "next-session", "until-event"] as const).map((mode) => {
                const label = mode === "all" ? "Alle Termine" : mode === "next-session" ? "Nächste Sitzung" : "Bis Termin";
                return (
                  <button key={mode} type="button"
                    className={`button-pill${exportDateMode === mode ? " button-pill-active" : ""}`}
                    onClick={() => { setExportDateMode(mode); setExportUrl(null); }}
                    style={{ width: "auto", minHeight: 0 }}
                  >{label}</button>
                );
              })}
            </div>
            {exportDateMode === "next-session" && (
              <span className="muted" style={{ fontSize: "0.82rem", paddingLeft: "2px" }}>
                {nextSessionEvent
                  ? `Bis ${nextSessionEvent.title} · ${formatDate(nextSessionEvent.event_date)}`
                  : "Keine Sitzung gefunden"}
              </span>
            )}
            {exportDateMode === "until-event" && (
              <SearchableSelect
                options={sortedEvents}
                getId={(ev) => ev.id}
                getLabel={(ev) => `${formatDate(ev.event_date)}${ev.tag ? ` · ${ev.tag}` : ""} — ${ev.title}`}
                value={exportUntilEventId === "" ? null : exportUntilEventId}
                onChange={(ev) => { setExportUntilEventId(ev ? ev.id : ""); setExportUrl(null); }}
                nullLabel="— Termin wählen —"
              />
            )}
          </div>

          <div style={{ display: "flex", gap: "10px", alignItems: "center", justifyContent: "space-between", borderTop: "1px solid var(--border)", paddingTop: "20px" }}>
            <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
            <button
              type="button"
              className={`pdf-icon-link pdf-icon-link-success${exportBusy || (!exportUrl && (!exportTemplateId || (exportDateMode === "until-event" && !exportUntilEventId) || (exportDateMode === "next-session" && !nextSessionEvent))) ? " pdf-icon-disabled" : ""}`}
              disabled={exportBusy || (!exportUrl && (!exportTemplateId || (exportDateMode === "until-event" && !exportUntilEventId) || (exportDateMode === "next-session" && !nextSessionEvent)))}
              onClick={() => void handlePdfClick()}
              title={exportUrl ? "PDF erneut herunterladen" : "PDF generieren"}
              style={{ width: "auto", minWidth: "56px", minHeight: 0, padding: "0 14px", display: "inline-flex", justifyContent: "center" }}
            >
              {exportBusy ? "..." : "PDF"}
            </button>
            <button
              type="button"
              className="pdf-icon-link pdf-icon-disabled"
              disabled
              title="Markdown-Export – kommt bald"
              style={{
                width: "auto", minWidth: "56px", minHeight: 0, padding: "0 14px", display: "inline-flex", justifyContent: "center",
                borderColor: "color-mix(in srgb, #a78bfa 28%, transparent 72%)",
                background: "color-mix(in srgb, #a78bfa 10%, transparent 90%)",
                color: "#a78bfa",
              }}
            >
              MD
            </button>
            </div>
            {landscapeTemplates.length > 0 && (
              <div ref={templateDropdownRef} style={{ position: "relative" }}>
                <button
                  type="button"
                  onClick={() => setTemplateDropdownOpen((v) => !v)}
                  style={{
                    width: "auto", minHeight: 0, height: "42px", padding: "0 32px 0 12px",
                    borderRadius: "14px", fontSize: "0.8rem",
                    border: "1px solid var(--border)", backgroundColor: "transparent",
                    color: "var(--text)", display: "flex", alignItems: "center", whiteSpace: "nowrap",
                    backgroundImage: "linear-gradient(45deg, transparent 50%, var(--muted) 50%), linear-gradient(135deg, var(--muted) 50%, transparent 50%)",
                    backgroundPosition: "calc(100% - 14px) calc(50% - 2px), calc(100% - 8px) calc(50% - 2px)",
                    backgroundSize: "6px 6px, 6px 6px", backgroundRepeat: "no-repeat",
                  }}
                >
                  {landscapeTemplates.find((t) => t.id === exportTemplateId)?.name ?? "Vorlage"}
                </button>
                {templateDropdownOpen && (
                  <div style={{
                    position: "absolute", bottom: "calc(100% + 4px)", right: 0, zIndex: 50,
                    backgroundColor: "var(--panel-solid)", border: "1px solid var(--border)",
                    borderRadius: "12px", boxShadow: "0 4px 20px rgba(0,0,0,0.22)",
                    overflow: "hidden", minWidth: "100%",
                  }}>
                    {landscapeTemplates.map((t, i) => (
                      <button
                        key={t.id}
                        type="button"
                        onMouseDown={() => { setExportTemplateId(t.id); setExportUrl(null); setTemplateDropdownOpen(false); }}
                        style={{
                          width: "100%", minHeight: 0, padding: "9px 14px",
                          textAlign: "left", fontSize: "0.88rem",
                          backgroundColor: "var(--panel-solid)",
                          color: "var(--text)",
                          fontWeight: t.id === exportTemplateId ? 700 : 400,
                          border: "none", borderRadius: 0,
                          borderBottom: i < landscapeTemplates.length - 1 ? "1px solid var(--border)" : "none",
                          cursor: "pointer", whiteSpace: "nowrap",
                        }}
                      >
                        {t.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

        </div>
      </Modal>

      {eventContextMenu && typeof document !== "undefined" && createPortal(
        <div
          ref={eventContextMenuRef}
          id="event-context-menu-portal"
          className="mini-menu-popover-portal"
          style={computePopoverPosition(new DOMRect(eventContextMenu.x, eventContextMenu.y, 0, 0), "start", 6, { minWidth: 220, estimatedHeight: 80 })}
          role="menu"
        >
          <button
            type="button"
            className="mini-menu-option"
            onClick={() => {
              void toggleCancelled(eventContextMenu.event);
              setEventContextMenu(null);
            }}
          >
            {eventContextMenu.event.is_cancelled ? "Absage aufheben" : "Als abgesagt markieren"}
          </button>
        </div>,
        document.body
      )}
    </div>
  );
}
