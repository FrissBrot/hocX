"use client";

import { ChangeEvent, Fragment, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLocale, useTranslations } from "next-intl";

import { EventCalendarModal } from "@/components/events/event-calendar-modal";
import { EventCreateModal } from "@/components/events/event-create-modal";
import { EventIcon } from "@/components/events/event-icons";
import { effectiveEndDate, fallbackTagColor, isoToUtcDate } from "@/components/events/event-utils";
import { ActionMenu } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
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
import { useTagConfig } from "@/lib/hooks/use-tag-config";
import { getCycleYear } from "@/lib/utils/cycle";
import { formatDate, formatDateRange, toIntlLocale } from "@/lib/utils/format";
import {
  CycleConfigSummary,
  DocumentTemplate,
  EventImportPreview,
  EventSummary,
  ParticipantSummary,
} from "@/types/api";

const PAGE_SIZE = 100;

type CsvTargetField = "event_date" | "event_end_date" | "tag" | "title" | "description" | "participant_count";
type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

function csvTargetFields(t: TFunc): { field: CsvTargetField; label: string; required?: boolean }[] {
  return [
    { field: "event_date", label: t("form.startDate"), required: true },
    { field: "event_end_date", label: t("form.endDate") },
    { field: "tag", label: t("form.tag") },
    { field: "title", label: t("form.title"), required: true },
    { field: "description", label: t("columns.description") },
    { field: "participant_count", label: t("columns.participantCount") },
  ];
}

// Felder, die in der Terminzeile zusätzlich angezeigt werden können (Menü „Ansicht").
type RowFieldKey = "description" | "location" | "participant_count" | "organizer_ids";

const DEFAULT_ROW_FIELDS: RowFieldKey[] = ["description", "location", "participant_count"];
const ROW_FIELDS_STORAGE_KEY = "hocx.events.rowFields";

function rowFieldOptions(t: TFunc): { key: RowFieldKey; label: string }[] {
  return [
    { key: "description", label: t("columns.description") },
    { key: "location", label: t("columns.location") },
    { key: "participant_count", label: t("columns.participantCount") },
    { key: "organizer_ids", label: t("columns.organizers") },
  ];
}

type TimeFilter = "upcoming" | "all" | "past";

// Sidebar-Eintrag für Termine ohne Tag.
const NO_TAG_FILTER = "__no_tag__";

type Props = {
  initialEvents: EventSummary[];
  documentTemplates?: DocumentTemplate[];
  availableParticipants?: ParticipantSummary[];
  tenantName?: string | null;
};

export function EventManager({ initialEvents, documentTemplates = [], availableParticipants = [], tenantName }: Props) {
  const t = useTranslations("events");
  const locale = useLocale();
  const CSV_TARGET_FIELDS = useMemo(() => csvTargetFields(t), [t]);
  const ROW_FIELD_OPTIONS = useMemo(() => rowFieldOptions(t), [t]);
  const showToast = useToast();
  const confirm = useConfirm();
  const [events, setEvents] = useState(initialEvents);
  const [hasMore, setHasMore] = useState(initialEvents.length === PAGE_SIZE);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [search, setSearch] = useState("");
  const [tagFilter, setTagFilter] = useState("all");
  const [timeFilter, setTimeFilter] = useState<TimeFilter>("all");
  const [rowFields, setRowFields] = useState<Set<RowFieldKey>>(() => new Set(DEFAULT_ROW_FIELDS));
  const [createDate, setCreateDate] = useState<string | null>(null);
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [todayIso, setTodayIso] = useState("0000-01-01");
  const [detailEvent, setDetailEvent] = useState<EventSummary | null>(null);
  const { tagConfig, updateTagColor, renameTag } = useTagConfig();
  const [cycleConfigs, setCycleConfigs] = useState<CycleConfigSummary[]>([]);
  const [showAllPeriods, setShowAllPeriods] = useState(false);


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
      showToast(error instanceof Error ? error.message : t("toasts.pdfExportFailed"), "error");
    } finally {
      setExportBusy(false);
    }
  }

  useEffect(() => {
    setTodayIso(new Date().toISOString().slice(0, 10));
  }, []);

  // Zeilen-Ansicht ist eine reine Komfort-Einstellung pro Browser.
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(ROW_FIELDS_STORAGE_KEY);
      if (!stored) return;
      const parsed: unknown = JSON.parse(stored);
      if (Array.isArray(parsed)) {
        const allowed = new Set<string>(["description", "location", "participant_count", "organizer_ids"]);
        setRowFields(new Set(parsed.filter((key): key is RowFieldKey => typeof key === "string" && allowed.has(key))));
      }
    } catch {
      // Ohne Speicher gilt die Standardansicht.
    }
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

  // Basis für Sidebar-Zähler und Liste: nur der Zyklus-Filter, noch ohne Tag/Zeit/Suche.
  const periodEvents = useMemo(
    () => (showAllPeriods ? events : events.filter((event) => isInCurrentPeriod(event))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [cycleConfigs, events, showAllPeriods, todayIso]
  );

  const tagCounts = useMemo(() => {
    const counts = new Map<string, number>();
    let untagged = 0;
    periodEvents.forEach((event) => {
      const tag = (event.tag ?? "").trim();
      if (tag) counts.set(tag, (counts.get(tag) ?? 0) + 1);
      else untagged += 1;
    });
    const tags = Array.from(counts.entries()).sort(([left], [right]) => left.localeCompare(right));
    return { tags, untagged };
  }, [periodEvents]);

  const upcomingCount = useMemo(() => events.filter((event) => effectiveEndDate(event) >= todayIso).length, [events, todayIso]);

  const filteredEvents = useMemo(() => {
    const query = search.trim().toLowerCase();
    return periodEvents
      .filter((event) => {
        const isPast = effectiveEndDate(event) < todayIso;
        if (timeFilter === "upcoming" && isPast) return false;
        if (timeFilter === "past" && !isPast) return false;
        const tag = (event.tag ?? "").trim();
        if (tagFilter === NO_TAG_FILTER ? tag !== "" : tagFilter !== "all" && tag !== tagFilter) {
          return false;
        }
        if (!query) {
          return true;
        }
        const haystack = `${event.title} ${event.tag ?? ""} ${event.description ?? ""} ${event.location ?? ""}`.toLowerCase();
        return haystack.includes(query);
      })
      .sort((left, right) => left.event_date.localeCompare(right.event_date) || left.title.localeCompare(right.title));
  }, [periodEvents, search, tagFilter, timeFilter, todayIso]);

  const monthFormatter = useMemo(
    () => new Intl.DateTimeFormat(toIntlLocale(locale), { month: "long", year: "numeric", timeZone: "UTC" }),
    [locale]
  );
  const weekdayFormatter = useMemo(
    () => new Intl.DateTimeFormat(toIntlLocale(locale), { weekday: "short", timeZone: "UTC" }),
    [locale]
  );
  const todayFormatter = useMemo(
    () => new Intl.DateTimeFormat(toIntlLocale(locale), { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }),
    [locale]
  );

  const monthGroups = useMemo(() => {
    const groups: { key: string; label: string; items: EventSummary[] }[] = [];
    filteredEvents.forEach((event) => {
      const key = event.event_date.slice(0, 7);
      const last = groups[groups.length - 1];
      if (last && last.key === key) {
        last.items.push(event);
      } else {
        groups.push({ key, label: monthFormatter.format(isoToUtcDate(event.event_date)), items: [event] });
      }
    });
    return groups;
  }, [filteredEvents, monthFormatter]);

  // Die „Heute"-Linie trennt vergangene und kommende Termine, nur wenn beide sichtbar sind.
  const todayMarkerEventId = useMemo(() => {
    if (timeFilter !== "all") return null;
    const index = filteredEvents.findIndex((event) => effectiveEndDate(event) >= todayIso);
    return index > 0 ? filteredEvents[index].id : null;
  }, [filteredEvents, timeFilter, todayIso]);

  // Beim ersten Anzeigen so scrollen, dass die „Heute"-Linie oben steht: darunter die kommenden,
  // darüber (per Hochscrollen) die vergangenen Termine.
  const todayMarkerRef = useRef<HTMLDivElement | null>(null);
  const scrolledToTodayRef = useRef(false);
  useEffect(() => {
    if (scrolledToTodayRef.current || !todayMarkerEventId || !todayMarkerRef.current) return;
    scrolledToTodayRef.current = true;
    todayMarkerRef.current.scrollIntoView({ block: "start" });
  }, [todayMarkerEventId]);

  function tagColor(tag: string): string {
    return tagConfig[tag]?.color ?? fallbackTagColor(tag);
  }

  const hasActiveFilter = tagFilter !== "all" || search.trim().length > 0;

  function resetFilters() {
    setTagFilter("all");
    setSearch("");
  }

  function filterSummary(): string {
    const count = filteredEvents.length;
    const query = search.trim();
    const tag = tagFilter === NO_TAG_FILTER ? t("noTag") : tagFilter;
    if (tagFilter !== "all" && query) return t("list.summaryTagQuery", { count, tag, query });
    if (tagFilter !== "all") return t("list.summaryTag", { count, tag });
    return t("list.summaryQuery", { count, query });
  }

  function openCreate(date?: string) {
    setCreateDate(date ?? todayIso);
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
      // Nur die Zyklen aus dem Server-Stand übernehmen (wandern beim Datumswechsel mit); übrige
      // Felder bleiben lokal, damit langsame Antworten keine laufende Eingabe überschreiben.
      setDetailEvent((current) =>
        current && current.id === eventId ? { ...current, cycle_assignments: updated.cycle_assignments } : current
      );
    } catch (error) {
      if (previous) {
        setEvents((current) => current.map((event) => (event.id === eventId ? previous : event)));
      }
      showToast(error instanceof Error ? error.message : t("toasts.eventUpdateFailed"), "error");
    }
  }

  function organizerNames(ids: string[] | null | undefined): string | null {
    if (!ids || ids.length === 0) return null;
    const names = ids
      .map((id) => availableParticipants.find((p) => p.id === id)?.display_name)
      .filter(Boolean);
    return names.length ? names.join(", ") : t("selectedCount", { count: ids.length });
  }

  async function deleteEvent(eventId: string) {
    const ok = await confirm({
      message: t("toasts.deleteConfirmMessage"),
      tone: "danger",
      confirmLabel: t("toasts.deleteConfirmLabel")
    });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/events/${eventId}`, { method: "DELETE" });
      setEvents((current) => current.filter((event) => event.id !== eventId));
      showToast(t("toasts.deleted"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.deleteFailed"), "error");
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
      showToast(error instanceof Error ? error.message : t("toasts.eventUpdateFailed"), "error");
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
      showToast(error instanceof Error ? error.message : t("toasts.loadMoreFailed"), "error");
    } finally {
      setIsLoadingMore(false);
    }
  }

  const loadMoreSentinelRef = useInfiniteScroll({
    hasMore,
    isLoading: isLoadingMore,
    onLoadMore: () => void loadMore(),
  });

  function toggleRowField(key: RowFieldKey) {
    setRowFields((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      try {
        window.localStorage.setItem(ROW_FIELDS_STORAGE_KEY, JSON.stringify(Array.from(next)));
      } catch {
        // Nicht speicherbar (z. B. privates Fenster): Einstellung gilt nur für diese Sitzung.
      }
      return next;
    });
  }

  function renderEventRow(item: EventSummary) {
    const isPast = effectiveEndDate(item) < todayIso;
    const tag = (item.tag ?? "").trim();
    const startDate = isoToUtcDate(item.event_date);
    const organizers = rowFields.has("organizer_ids") ? organizerNames(item.organizer_ids) : null;
    const participantCount = item.participant_count ?? 0;
    const rowClass = `event-list-row${isPast ? " event-list-row-past" : ""}${item.is_cancelled ? " event-list-row-cancelled" : ""}`;

    return (
      <Fragment key={item.id}>
        {item.id === todayMarkerEventId ? (
          <div ref={todayMarkerRef} className="event-today-marker">
            <span>{t("list.today", { date: todayFormatter.format(isoToUtcDate(todayIso)) })}</span>
          </div>
        ) : null}
        <div className={rowClass} onClick={() => setDetailEvent(item)} onContextMenu={(event) => openEventContextMenu(event, item)}>
          <div className="event-date-tile" aria-hidden="true">
            <span className="event-date-tile-weekday">{weekdayFormatter.format(startDate).replace(/\.$/, "")}</span>
            <span className="event-date-tile-day">{startDate.getUTCDate()}</span>
          </div>
          <div className="event-list-row-body">
            <button
              type="button"
              className="event-list-row-title"
              onClick={(clickEvent) => {
                clickEvent.stopPropagation();
                setDetailEvent(item);
              }}
            >
              {item.title}
            </button>
            <div className="event-list-row-meta">
              {tag ? (
                <span className="badge event-tag-badge" style={{ "--tag-color": tagColor(tag) } as React.CSSProperties}>
                  <span className="badge-dot" />
                  {tag}
                </span>
              ) : null}
              {item.is_cancelled ? <Badge variant="danger">{t("columns.cancelled")}</Badge> : null}
              {item.event_end_date && item.event_end_date !== item.event_date ? (
                <span className="event-list-meta-item">{formatDateRange(item.event_date, item.event_end_date)}</span>
              ) : null}
              {rowFields.has("description") && item.description ? (
                <span className="event-list-meta-item event-list-meta-description">{item.description}</span>
              ) : null}
              {rowFields.has("location") && item.location ? (
                <span className="event-list-meta-item">
                  <EventIcon name="pin" width={14} height={14} />
                  {item.location}
                </span>
              ) : null}
              {organizers ? (
                <span className="event-list-meta-item">
                  <EventIcon name="user" width={14} height={14} />
                  {organizers}
                </span>
              ) : null}
            </div>
          </div>
          <div className="event-list-row-aside">
            {rowFields.has("participant_count") && participantCount > 0 ? (
              <span className="event-list-count" title={t("columns.participantCount")}>
                <EventIcon name="users" width={15} height={15} />
                {participantCount}
              </span>
            ) : null}
            <ActionMenu
              items={[
                { label: t("list.open"), onClick: () => setDetailEvent(item) },
                {
                  label: item.is_cancelled ? t("contextMenu.uncancel") : t("contextMenu.markCancelled"),
                  onClick: () => void toggleCancelled(item),
                },
                { label: t("delete"), onClick: () => void deleteEvent(item.id), danger: true },
              ]}
            />
          </div>
        </div>
      </Fragment>
    );
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
      setImportError(error instanceof Error ? error.message : t("toasts.previewFailed"));
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
      showToast(t("toasts.importedCount", { count: imported.length }), "success");
      setShowImportModal(false);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.csvImportFailed"), "error");
    } finally {
      setImportCommitting(false);
    }
  }

  const hasNoEvents = events.length === 0 && !hasMore;

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("pageTitle")}</h1>
          <p className="muted">
            {hasNoEvents ? t("pageDescriptionEmpty") : t("pageSummary", { total: events.length, upcoming: upcomingCount })}
          </p>
        </div>
        {hasNoEvents ? null : (
          <div className="event-header-actions">
            <button type="button" className="button-secondary button-ghost event-calendar-button" onClick={() => setCalendarOpen(true)}>
              <EventIcon name="calendar" />
              {t("calendar.open")}
            </button>
            <div className="event-button-group">
              <button type="button" className="button-secondary button-ghost" onClick={openImportModal}>
                <EventIcon name="upload" />
                {t("csvImport")}
              </button>
              {landscapeTemplates.length > 0 && (
                <button type="button" className="button-secondary button-ghost" onClick={() => setExportModalOpen(true)}>
                  <EventIcon name="download" />
                  {t("export")}
                </button>
              )}
            </div>
            <button type="button" className="button-primary event-new-button" onClick={() => openCreate()}>
              <EventIcon name="plus" />
              {t("newEvent")}
            </button>
          </div>
        )}
      </div>

      {hasNoEvents ? (
        <EmptyState
          title={t("emptyState.title")}
          description={t("emptyState.description")}
          actions={
            <button type="button" className="button-primary" onClick={() => openCreate()}>
              {t("emptyState.add")}
            </button>
          }
          hint={t("emptyState.hint")}
        />
      ) : (
        <div className="event-layout">
          <aside className="event-tag-sidebar" aria-label={t("tagSidebar.title")}>
            <div className="event-tag-sidebar-title">{t("tagSidebar.title")}</div>
            <div className="event-tag-sidebar-list">
              <button
                type="button"
                className={`event-tag-sidebar-item${tagFilter === "all" ? " event-tag-sidebar-item-active" : ""}`}
                aria-pressed={tagFilter === "all"}
                onClick={() => setTagFilter("all")}
              >
                <span className="event-tag-dot event-tag-dot-all" />
                <span className="event-tag-sidebar-label">{t("tagSidebar.all")}</span>
                <span className="event-tag-sidebar-count">{periodEvents.length}</span>
              </button>
              {tagCounts.tags.map(([tag, count]) => (
                <button
                  key={tag}
                  type="button"
                  className={`event-tag-sidebar-item${tagFilter === tag ? " event-tag-sidebar-item-active" : ""}`}
                  aria-pressed={tagFilter === tag}
                  onClick={() => setTagFilter(tag)}
                >
                  <span className="event-tag-dot" style={{ "--tag-color": tagColor(tag) } as React.CSSProperties} />
                  <span className="event-tag-sidebar-label">{tag}</span>
                  <span className="event-tag-sidebar-count">{count}</span>
                </button>
              ))}
              {tagCounts.untagged > 0 && (
                <button
                  type="button"
                  className={`event-tag-sidebar-item${tagFilter === NO_TAG_FILTER ? " event-tag-sidebar-item-active" : ""}`}
                  aria-pressed={tagFilter === NO_TAG_FILTER}
                  onClick={() => setTagFilter(NO_TAG_FILTER)}
                >
                  <span className="event-tag-dot event-tag-dot-none" />
                  <span className="event-tag-sidebar-label">{t("noTag")}</span>
                  <span className="event-tag-sidebar-count">{tagCounts.untagged}</span>
                </button>
              )}
            </div>
          </aside>

          <div className="event-main">
            <div className="event-toolbar">
              <div className="event-toolbar-search">
                <SearchInput value={search} onChange={setSearch} placeholder={t("searchPlaceholder")} />
              </div>
              <FilterTabs<TimeFilter>
                options={[
                  { value: "upcoming", label: t("timeFilter.upcoming") },
                  { value: "all", label: t("timeFilter.all") },
                  { value: "past", label: t("timeFilter.past") },
                ]}
                value={timeFilter}
                onChange={setTimeFilter}
              />
              <button
                ref={viewMenuTriggerRef}
                type="button"
                className={`button-secondary button-ghost event-view-trigger${viewMenuOpen ? " event-view-trigger-open" : ""}`}
                onClick={() => setViewMenuOpen((value) => !value)}
                aria-haspopup="menu"
                aria-expanded={viewMenuOpen}
              >
                <EventIcon name="sliders" />
                {t("view")}
              </button>
              <Popover
                open={viewMenuOpen}
                onOpenChange={setViewMenuOpen}
                anchorRef={viewMenuTriggerRef}
                align="end"
                className="mini-menu-popover-portal event-view-popover"
              >
                {cycleConfigs.length > 0 && (
                  <div className="mini-menu-section">
                    <div className="mini-menu-section-title">{t("filterSection")}</div>
                    <label className="mini-menu-option mini-menu-switch-option">
                      <span>{t("showAllPeriods")}</span>
                      <input
                        type="checkbox"
                        className="mini-menu-switch-input"
                        checked={showAllPeriods}
                        onChange={(event) => setShowAllPeriods(event.target.checked)}
                      />
                      <span className="mini-menu-switch" aria-hidden="true" />
                    </label>
                  </div>
                )}
                <div className="mini-menu-section">
                  <div className="mini-menu-section-title">{t("rowFieldsSection")}</div>
                  {ROW_FIELD_OPTIONS.map((option) => (
                    <label key={option.key} className="mini-menu-option mini-menu-switch-option">
                      <span>{option.label}</span>
                      <input
                        type="checkbox"
                        className="mini-menu-switch-input"
                        checked={rowFields.has(option.key)}
                        onChange={() => toggleRowField(option.key)}
                      />
                      <span className="mini-menu-switch" aria-hidden="true" />
                    </label>
                  ))}
                </div>
              </Popover>
            </div>

            {hasActiveFilter && filteredEvents.length > 0 && (
              <div className="event-filter-summary">
                <span>{filterSummary()}</span>
                <button type="button" className="event-link-button" onClick={resetFilters}>
                  {t("list.resetFilters")}
                </button>
              </div>
            )}

            <div className="event-list">
              {monthGroups.length === 0 ? (
                <div className="event-list-empty">
                  <strong className="event-list-empty-title">{t("list.emptyTitle")}</strong>
                  {hasActiveFilter || timeFilter !== "all" ? (
                    <button
                      type="button"
                      className="event-link-button"
                      onClick={() => {
                        resetFilters();
                        setTimeFilter("all");
                      }}
                    >
                      {t("list.resetFilters")}
                    </button>
                  ) : null}
                </div>
              ) : (
                monthGroups.map((group) => (
                  <section key={group.key} className="event-month-group">
                    <h2 className="event-month-heading">
                      {group.label}
                      <span className="event-month-count">{t("list.monthCount", { count: group.items.length })}</span>
                    </h2>
                    {group.items.map((item) => renderEventRow(item))}
                  </section>
                ))
              )}
            </div>
          </div>
        </div>
      )}
      {hasMore && (
        <div className="load-more-row" ref={loadMoreSentinelRef}>
          {isLoadingMore ? (
            <span className="muted">{t("loadingMore")}</span>
          ) : (
            <button type="button" className="button-secondary button-ghost" onClick={() => void loadMore()}>
              {t("loadMore", { count: events.length })}
            </button>
          )}
        </div>
      )}

      <Modal
        open={showImportModal}
        onClose={() => setShowImportModal(false)}
        title={t("importModal.title")}
        description={t("importModal.description")}
        size="wide"
      >
        <div className="grid" style={{ gap: "var(--space-4)" }}>
          {!importFile ? (
            <label className="csv-import-dropzone" style={{ cursor: "pointer" }}>
              <strong>{t("importModal.selectFile")}</strong>
              <span className="muted">{t("importModal.requiredColumnsHint")}</span>
              <input type="file" accept=".csv,text/csv" onChange={handleImportFileChange} hidden />
            </label>
          ) : (
            <div className="csv-import-file-row">
              <span>
                <strong>{importFile.name}</strong>
                <span className="muted"> · {importPreview ? t("importModal.rowsDetected", { count: importPreview.rows.length }) : t("importModal.reading")}</span>
              </span>
              <label className="button-secondary button-ghost" style={{ width: "auto", minHeight: 0, padding: "var(--space-2) var(--space-4)", cursor: "pointer" }}>
                {t("importModal.otherFile")}
                <input type="file" accept=".csv,text/csv" onChange={handleImportFileChange} hidden />
              </label>
            </div>
          )}

          <details className="card import-help-card">
            <summary className="import-help-summary">
              <span>{t("importModal.showFormat")}</span>
              <span className="muted">{t("importModal.requiredFields")}</span>
            </summary>
            <div className="import-help-body">
              <p className="muted">
                {t("importModal.formatHelp")}
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
                      nullLabel={t("importModal.doNotMap")}
                    />
                  </label>
                ))}
              </div>

              <div className="status-row">
                <Badge variant="success">{t("importModal.valid", { count: importPreview.valid_count })}</Badge>
                {importPreview.error_count > 0 && <Badge variant="danger">{t("importModal.withErrors", { count: importPreview.error_count })}</Badge>}
                <span className="pill">{t("importModal.totalRows", { count: importPreview.rows.length })}</span>
                {importPreviewLoading && <span className="muted">{t("importModal.updatingPreview")}</span>}
              </div>

              <DataTable columns={[
                t("importModal.previewColumns.number"),
                t("importModal.previewColumns.startDate"),
                t("importModal.previewColumns.endDate"),
                t("importModal.previewColumns.tag"),
                t("importModal.previewColumns.title"),
                t("importModal.previewColumns.description"),
                t("importModal.previewColumns.participants"),
                t("importModal.previewColumns.status"),
              ]}>
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
                        <Badge variant="success">{t("importModal.rowValid")}</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </DataTable>

              <div className="table-actions" style={{ justifyContent: "flex-end" }}>
                <button type="button" className="button-secondary button-ghost" onClick={() => setShowImportModal(false)}>
                  {t("importModal.cancel")}
                </button>
                <button
                  type="button"
                  className="button-secondary"
                  disabled={
                    importCommitting ||
                    importPreviewLoading ||
                    importPreview.rows.length === 0 ||
                    importPreview.error_count > 0
                  }
                  onClick={() => void confirmImport()}
                >
                  {importCommitting ? t("importModal.importing") : t("importModal.importRows", { count: importPreview.valid_count })}
                </button>
              </div>
            </>
          )}
        </div>
      </Modal>

      <EventCreateModal
        open={createDate !== null}
        onClose={() => setCreateDate(null)}
        initialDate={createDate ?? todayIso}
        knownTags={knownTags}
        availableParticipants={availableParticipants}
        cycleConfigs={cycleConfigs}
        tenantName={tenantName}
        onCreated={(saved) => setEvents((current) => [saved, ...current])}
      />

      <EventCalendarModal
        open={calendarOpen}
        onClose={() => setCalendarOpen(false)}
        events={events}
        todayIso={todayIso}
        tagColor={tagColor}
        onOpenEvent={setDetailEvent}
        onCreateForDate={(iso) => openCreate(iso)}
      />

      <Modal
        open={Boolean(detailEvent)}
        onClose={() => setDetailEvent(null)}
        title={detailEvent?.title || t("detailModal.fallbackTitle")}
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

      <Modal open={exportModalOpen} title={t("exportModal.title")} onClose={() => setExportModalOpen(false)}>
        <div style={{ display: "grid", gap: "var(--space-5)" }}>

          {knownExportTags.length > 0 && (
            <div className="field-stack">
              <span className="field-label">{t("exportModal.tags")}</span>
              <div style={{ position: "relative" }}>
                <input
                  className="dropdown-search-input"
                  placeholder={t("exportModal.tagSearchPlaceholder")}
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
                  <div className="dropdown-panel dropdown-panel-down">
                    {tagSuggestions.map((tag, i) => (
                      <button
                        key={tag}
                        type="button"
                        onMouseDown={(e) => { e.preventDefault(); toggleExportTag(tag); setExportTagSearch(""); }}
                        className={i === 0 ? "dropdown-option dropdown-option-active dropdown-option-row" : "dropdown-option dropdown-option-row"}
                      >
                        <span>{tag}</span>
                        {i === 0 && <span className="dropdown-hint">{t("exportModal.tabHint")}</span>}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <div className="tag-filter-bar">
                {exportTagFilters.map((tag) => (
                  <button key={tag} type="button" className="tag-filter-chip tag-filter-chip-active"
                    onClick={() => toggleExportTag(tag)}
                    style={{ width: "auto", minHeight: 0, padding: "var(--space-1) var(--space-3)", display: "inline-flex", fontSize: "var(--text-base)" }}
                  >{tag} ×</button>
                ))}
                {knownExportTags.filter((t) => !exportTagFilters.includes(t)).map((tag) => (
                  <button key={tag} type="button" className="tag-filter-chip"
                    onClick={() => toggleExportTag(tag)}
                    style={{ width: "auto", minHeight: 0, padding: "var(--space-1) var(--space-3)", display: "inline-flex", fontSize: "var(--text-base)" }}
                  >{tag}</button>
                ))}
              </div>
            </div>
          )}

          <div className="field-stack">
            <span className="field-label">{t("exportModal.period")}</span>
            <div className="filter-pill-row">
              {(["all", "next-session", "until-event"] as const).map((mode) => {
                const label = mode === "all" ? t("exportModal.periodAll") : mode === "next-session" ? t("exportModal.periodNextSession") : t("exportModal.periodUntilEvent");
                return (
                  <button key={mode} type="button"
                    className={`button-pill${exportDateMode === mode ? " button-pill-active" : ""}`}
                    onClick={() => { setExportDateMode(mode); setExportUrl(null); }}
                  >{label}</button>
                );
              })}
            </div>
            {exportDateMode === "next-session" && (
              <span className="muted" style={{ fontSize: "var(--text-sm)", paddingLeft: "2px" }}>
                {nextSessionEvent
                  ? t("exportModal.untilLabel", { title: nextSessionEvent.title, date: formatDate(nextSessionEvent.event_date) })
                  : t("exportModal.noSessionFound")}
              </span>
            )}
            {exportDateMode === "until-event" && (
              <SearchableSelect
                options={sortedEvents}
                getId={(ev) => ev.id}
                getLabel={(ev) => `${formatDate(ev.event_date)}${ev.tag ? ` · ${ev.tag}` : ""} — ${ev.title}`}
                value={exportUntilEventId === "" ? null : exportUntilEventId}
                onChange={(ev) => { setExportUntilEventId(ev ? ev.id : ""); setExportUrl(null); }}
                nullLabel={t("exportModal.noEventChosen")}
              />
            )}
          </div>

          <div style={{ display: "flex", gap: "var(--space-3)", alignItems: "center", justifyContent: "space-between", borderTop: "1px solid var(--border)", paddingTop: "var(--space-5)" }}>
            <div style={{ display: "flex", gap: "var(--space-3)", alignItems: "center" }}>
            <button
              type="button"
              className={`pdf-icon-link pdf-icon-link-success${exportBusy || (!exportUrl && (!exportTemplateId || (exportDateMode === "until-event" && !exportUntilEventId) || (exportDateMode === "next-session" && !nextSessionEvent))) ? " pdf-icon-disabled" : ""}`}
              disabled={exportBusy || (!exportUrl && (!exportTemplateId || (exportDateMode === "until-event" && !exportUntilEventId) || (exportDateMode === "next-session" && !nextSessionEvent)))}
              onClick={() => void handlePdfClick()}
              title={exportUrl ? t("exportModal.redownloadPdf") : t("exportModal.generatePdf")}
              style={{ width: "auto", minWidth: "56px", minHeight: 0, padding: "0 var(--space-4)", display: "inline-flex", justifyContent: "center" }}
            >
              {exportBusy ? "..." : "PDF"}
            </button>
            <button
              type="button"
              className="pdf-icon-link pdf-icon-link-soon"
              disabled
              title={t("exportModal.markdownSoon")}
              style={{ width: "auto", minWidth: "56px", minHeight: 0, padding: "0 var(--space-4)", display: "inline-flex", justifyContent: "center" }}
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
                    width: "auto", minHeight: 0, height: "42px", padding: "0 var(--space-6) 0 var(--space-3)",
                    borderRadius: "var(--radius-md)", fontSize: "var(--text-sm)",
                    border: "1px solid var(--border)", backgroundColor: "transparent",
                    color: "var(--text)", display: "flex", alignItems: "center", whiteSpace: "nowrap",
                    backgroundImage: "linear-gradient(45deg, transparent 50%, var(--muted) 50%), linear-gradient(135deg, var(--muted) 50%, transparent 50%)",
                    backgroundPosition: "calc(100% - 14px) calc(50% - 2px), calc(100% - 8px) calc(50% - 2px)",
                    backgroundSize: "6px 6px, 6px 6px", backgroundRepeat: "no-repeat",
                  }}
                >
                  {landscapeTemplates.find((tpl) => tpl.id === exportTemplateId)?.name ?? t("exportModal.templateFallback")}
                </button>
                {templateDropdownOpen && (
                  <div className="dropdown-panel dropdown-panel-up" style={{ minWidth: "100%" }}>
                    {landscapeTemplates.map((t, i) => (
                      <button
                        key={t.id}
                        type="button"
                        onMouseDown={() => { setExportTemplateId(t.id); setExportUrl(null); setTemplateDropdownOpen(false); }}
                        className={t.id === exportTemplateId ? "dropdown-option dropdown-option-selected" : "dropdown-option"}
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
            {eventContextMenu.event.is_cancelled ? t("contextMenu.uncancel") : t("contextMenu.markCancelled")}
          </button>
        </div>,
        document.body
      )}
    </div>
  );
}
