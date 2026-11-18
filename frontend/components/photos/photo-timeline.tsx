"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { groupPhotosByDate } from "./grouping";
import { dateMarkersFor, PhotoDateMarker } from "./photo-date-marker";
import { PhotoTile } from "./photo-tile";
import { browserApiFetch } from "@/lib/api/client";
import { formatWeekdayDate } from "@/lib/utils/format";
import { FileOverviewItem } from "@/types/api";
import {
  buildTimelineLayout,
  chunkDaysForLoading,
  dayIndexAt,
  scrubberMarks,
  type TimelineDay,
} from "./timeline-layout";

// Fotogalerie nach Datum (Nextcloud-Prinzip): das Backend liefert zuerst nur die Anzahl Fotos je
// Tag (GET /api/files/timeline). Daraus stehen Höhe und Position jedes Tages fest, bevor ein Bild
// geladen ist - geladen werden nur die sichtbaren Tage (GET /api/files?date_from&date_to), die
// Kacheln sind quadratisch. So springt beim Scrollen nichts, und der Zeitstrahl rechts bildet
// den ganzen Bestand ab: Klicken oder Ziehen springt direkt zu einem Jahr oder Datum.

const BUFFER_PX = 900;
const REFRESH_MS = 30000;

type Props = {
  /** Gefilterte Basis-Query ohne skip/limit/sort (search, tags, only_images). */
  filterQuery: string;
  sortDir: "asc" | "desc";
  /** Erhöhen = Zählung und geladene Tage neu holen (nach Upload, Löschen, Datumsänderung). */
  reloadKey: number;
  /** Erhöhen = nur die Zählung prüfen, sichtbare Position bleibt (nach Upload, Löschen). */
  refreshKey?: number;
  items: FileOverviewItem[];
  selectedIds: Set<string>;
  onItemsLoaded: (days: string[], items: FileOverviewItem[]) => void;
  onTotalChange?: (total: number) => void;
  onOpen: (item: FileOverviewItem) => void;
  onToggleSelect: (id: string) => void;
  onToggleGroup: (ids: string[]) => void;
};

function useContainerWidth(ref: React.RefObject<HTMLElement | null>) {
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => setWidth(element.clientWidth);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

/** Abstand vom Dokumentanfang bis zum Inhalt der Zeitleiste (die Seite scrollt als Ganzes). */
function documentTop(element: HTMLElement | null): number {
  return element ? element.getBoundingClientRect().top + window.scrollY : 0;
}

export function PhotoTimeline({
  filterQuery,
  sortDir,
  reloadKey,
  refreshKey = 0,
  items,
  selectedIds,
  onItemsLoaded,
  onTotalChange,
  onOpen,
  onToggleSelect,
  onToggleGroup,
}: Props) {
  const t = useTranslations("photos.timeline");
  const tGroups = useTranslations("photos.dateGroups");
  const locale = useLocale();
  const contentRef = useRef<HTMLDivElement>(null);
  const width = useContainerWidth(contentRef);
  const [days, setDays] = useState<TimelineDay[] | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(800);
  const loadedRef = useRef<Set<string>>(new Set());
  const loadingRef = useRef<Set<string>>(new Set());
  const [loadTick, setLoadTick] = useState(0);
  const generationRef = useRef(0);
  const layoutRef = useRef<ReturnType<typeof buildTimelineLayout> | null>(null);

  const layout = useMemo(() => (days && width > 0 ? buildTimelineLayout(days, width) : null), [days, width]);
  layoutRef.current = layout;

  // Zählung holen; bei einer Aktualisierung bleibt der oberste sichtbare Tag an seinem Platz
  // (geänderte Tage davor verschieben den Inhalt nicht unter dem Blick weg).
  const fetchDays = useCallback(async (mode: "reset" | "refresh") => {
    const generation = mode === "reset" ? ++generationRef.current : generationRef.current;
    const next = await browserApiFetch<TimelineDay[]>(`/api/files/timeline?${filterQuery}&sort_dir=${sortDir}`).catch(() => null);
    if (!next || generation !== generationRef.current) return;
    const previous = layoutRef.current;
    const top = window.scrollY - documentTop(contentRef.current);
    let anchor: { date: string; delta: number } | null = null;
    if (mode === "refresh" && previous && top > 0) {
      const index = dayIndexAt(previous.offsets, top);
      if (index >= 0) anchor = { date: previous.days[index].date, delta: top - previous.offsets[index] };
    }
    setDays((current) => {
      if (mode === "reset") {
        loadedRef.current = new Set();
        loadingRef.current = new Set();
      } else if (current) {
        // Tage mit geänderter Anzahl neu laden
        const before = new Map(current.map((day) => [day.date, day.count]));
        for (const day of next) {
          if (before.get(day.date) !== day.count) loadedRef.current.delete(day.date);
        }
        if (current.length === next.length && current.every((day, index) => day.date === next[index].date && day.count === next[index].count)) {
          return current;
        }
      }
      return next;
    });
    onTotalChange?.(next.reduce((sum, day) => sum + day.count, 0));
    if (anchor) {
      requestAnimationFrame(() => {
        const updated = layoutRef.current;
        const index = updated?.days.findIndex((day) => day.date === anchor!.date) ?? -1;
        if (updated && index >= 0) {
          window.scrollTo({ top: documentTop(contentRef.current) + updated.offsets[index] + anchor!.delta });
        }
      });
    }
    setLoadTick((tick) => tick + 1);
  }, [filterQuery, sortDir, onTotalChange]);

  useEffect(() => {
    void fetchDays("reset");
  }, [fetchDays, reloadKey]);

  const refreshSeenRef = useRef(refreshKey);
  useEffect(() => {
    if (refreshSeenRef.current === refreshKey) return;
    refreshSeenRef.current = refreshKey;
    void fetchDays("refresh");
  }, [fetchDays, refreshKey]);

  useEffect(() => {
    const tick = () => {
      if (document.visibilityState === "visible") void fetchDays("refresh");
    };
    const timer = setInterval(tick, REFRESH_MS);
    document.addEventListener("visibilitychange", tick);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [fetchDays]);

  useEffect(() => {
    let frame = 0;
    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        setScrollTop(window.scrollY - documentTop(contentRef.current));
        setViewportHeight(window.innerHeight);
      });
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, []);

  // Sichtbarer Bereich (mit Vorlauf) -> Tage
  const visible = useMemo(() => {
    if (!layout) return { start: 0, end: -1 };
    const from = Math.max(0, scrollTop - BUFFER_PX);
    const to = scrollTop + viewportHeight + BUFFER_PX;
    const start = Math.max(0, dayIndexAt(layout.offsets, from));
    let end = start;
    while (end + 1 < layout.days.length && layout.offsets[end + 1] < to) end += 1;
    return { start, end };
  }, [layout, scrollTop, viewportHeight]);

  // Fehlende sichtbare Tage laden, in Blöcken von höchstens 200 Fotos (Limit von GET /api/files)
  useEffect(() => {
    if (!layout || visible.end < visible.start) return;
    const generation = generationRef.current;
    const missing = layout.days
      .slice(visible.start, visible.end + 1)
      .filter((day) => !loadedRef.current.has(day.date) && !loadingRef.current.has(day.date));
    if (missing.length === 0) return;
    for (const chunk of chunkDaysForLoading(missing, layout.days)) {
      const dates = chunk.days.map((day) => day.date);
      dates.forEach((date) => loadingRef.current.add(date));
      void (async () => {
        const collected: FileOverviewItem[] = [];
        try {
          for (let skip = 0; skip < chunk.total; skip += 200) {
            const page = await browserApiFetch<FileOverviewItem[]>(
              `/api/files?${filterQuery}&sort_by=group_date&sort_dir=${sortDir}&date_from=${chunk.from}&date_to=${chunk.to}&skip=${skip}&limit=200`,
            );
            collected.push(...(page ?? []));
            if (!page || page.length < 200) break;
          }
          if (generation !== generationRef.current) return;
          dates.forEach((date) => loadedRef.current.add(date));
          onItemsLoaded(dates, collected);
        } catch {
          // Beim nächsten Scrollen bzw. der nächsten Aktualisierung erneut versucht
        } finally {
          dates.forEach((date) => loadingRef.current.delete(date));
        }
      })();
    }
  }, [layout, visible, filterQuery, sortDir, onItemsLoaded, loadTick]);

  const groups = useMemo(() => new Map(groupPhotosByDate(items).map((group) => [group.date, group])), [items]);
  const selectionMode = selectedIds.size > 0;

  // Der Inhaltsbereich ist immer da: seine Breite bestimmt das Layout, auch schon vor der Zählung.
  const rendered = layout ? layout.days.slice(visible.start, visible.end + 1) : [];

  return (
    <div className="photo-timeline">
      <div ref={contentRef} className="photo-timeline-content" style={{ height: layout?.total ?? 0 }}>
        {!days ? <div className="photo-timeline-loading" role="status" aria-label={t("loading")} /> : null}
        {layout && rendered.map((day, offset) => {
          const index = visible.start + offset;
          const group = groups.get(day.date);
          const loadedItems = group?.items ?? [];
          const placeholders = Math.max(0, day.count - loadedItems.length);
          const ids = loadedItems.map((item) => item.id);
          const allSelected = ids.length > 0 && ids.every((id) => selectedIds.has(id));
          return (
            <section
              key={day.date}
              className="photo-timeline-day"
              style={{ top: layout.offsets[index], height: layout.heights[index] }}
              aria-label={formatWeekdayDate(day.date, locale)}
            >
              <div className="photo-date-heading photo-timeline-heading">
                <div className="photo-date-heading-labels">
                  <h2 className="photo-date-weekday">{formatWeekdayDate(day.date, locale)}</h2>
                  <span className="photo-date-context">
                    {group?.contextLabel}{group?.contextLabel ? " " : null}{tGroups("groupCount", { count: day.count })}
                  </span>
                  {group
                    ? dateMarkersFor(loadedItems.map((item) => item.date_source)).map((marker) => (
                        <PhotoDateMarker key={marker.kind} variant="pill" {...marker} />
                      ))
                    : null}
                </div>
                {ids.length > 0 && (
                  <button type="button" className="button-secondary button-ghost photo-date-select-all" aria-pressed={allSelected} onClick={() => onToggleGroup(ids)}>
                    {allSelected ? tGroups("deselectDay") : tGroups("selectDay")}
                  </button>
                )}
              </div>
              <div className="photo-timeline-grid" style={{ gridTemplateColumns: `repeat(${layout.columns}, ${layout.tile}px)`, gridAutoRows: `${layout.tile}px` }}>
                {loadedItems.map((item) => (
                  <PhotoTile
                    key={item.id}
                    square
                    item={item}
                    selected={selectedIds.has(item.id)}
                    selectionMode={selectionMode}
                    onOpen={() => onOpen(item)}
                    onToggleSelect={() => onToggleSelect(item.id)}
                  />
                ))}
                {Array.from({ length: placeholders }, (_, placeholder) => (
                  <span key={`placeholder-${placeholder}`} className="photo-timeline-placeholder" aria-hidden="true" />
                ))}
              </div>
            </section>
          );
        })}
      </div>
      {layout && layout.days.length > 0 ? (
      <TimelineScrubber
        days={layout.days}
        offsets={layout.offsets}
        total={layout.total}
        scrollTop={scrollTop}
        viewportHeight={viewportHeight}
        locale={locale}
        label={t("scrubberLabel")}
        onJump={(offset) => window.scrollTo({ top: documentTop(contentRef.current) + offset })}
      />
      ) : null}
    </div>
  );
}

function TimelineScrubber({
  days,
  offsets,
  total,
  scrollTop,
  viewportHeight,
  locale,
  label,
  onJump,
}: {
  days: TimelineDay[];
  offsets: number[];
  total: number;
  scrollTop: number;
  viewportHeight: number;
  locale: string;
  label: string;
  onJump: (offset: number) => void;
}) {
  const railRef = useRef<HTMLDivElement>(null);
  const [railHeight, setRailHeight] = useState(0);
  const [hover, setHover] = useState<number | null>(null);
  const draggingRef = useRef(false);
  const monthFormat = useMemo(() => new Intl.DateTimeFormat(locale, { month: "short", year: "numeric", timeZone: "UTC" }), [locale]);

  useLayoutEffect(() => {
    const element = railRef.current;
    if (!element) return;
    const measure = () => setRailHeight(element.clientHeight);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const scrollable = Math.max(1, total - viewportHeight);
  // Marken auf derselben Skala wie Cursor und Sprung (Scrollhöhe), damit ein Klick auf «2023»
  // genau dort landet, wo die Beschriftung steht.
  const marks = useMemo(() => scrubberMarks(days, offsets, scrollable, railHeight), [days, offsets, scrollable, railHeight]);
  const position = Math.min(1, Math.max(0, scrollTop / scrollable));
  const currentIndex = dayIndexAt(offsets, Math.max(0, scrollTop));
  const current = days[Math.max(0, currentIndex)];
  const monthOf = (date: string) => monthFormat.format(new Date(`${date}T00:00:00Z`));

  // Position auf der Leiste <-> Stelle im Inhalt: proportional zur Scrollhöhe, damit oben und
  // unten exakt Anfang und Ende des Bestands treffen.
  const offsetFor = (clientY: number) => {
    const rect = railRef.current?.getBoundingClientRect();
    if (!rect || rect.height <= 0) return 0;
    const ratio = Math.min(1, Math.max(0, (clientY - rect.top) / rect.height));
    return ratio * scrollable;
  };
  const hoverDate = hover === null ? null : days[Math.max(0, dayIndexAt(offsets, hover))]?.date;

  return (
    <div className="photo-timeline-scrubber">
      <div
        ref={railRef}
        className="photo-timeline-rail"
        role="slider"
        tabIndex={0}
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(position * 100)}
        aria-valuetext={current ? monthOf(current.date) : undefined}
        onPointerDown={(event) => {
          draggingRef.current = true;
          event.currentTarget.setPointerCapture(event.pointerId);
          onJump(offsetFor(event.clientY));
        }}
        onPointerMove={(event) => {
          const offset = offsetFor(event.clientY);
          setHover(offset);
          if (draggingRef.current) onJump(offset);
        }}
        onPointerUp={(event) => {
          draggingRef.current = false;
          event.currentTarget.releasePointerCapture(event.pointerId);
        }}
        onPointerLeave={() => {
          if (!draggingRef.current) setHover(null);
        }}
        onKeyDown={(event) => {
          // Pfeile: ein Monat weiter/zurück, Bild auf/ab: ein Bildschirm, Pos1/Ende: Anfang/Ende
          const step = event.key === "PageDown" ? viewportHeight : event.key === "PageUp" ? -viewportHeight : 0;
          if (step) return onJump(Math.max(0, scrollTop + step));
          if (event.key === "Home") return onJump(0);
          if (event.key === "End") return onJump(scrollable);
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            const monthStarts = marks.months.map((mark) => mark.offset);
            const target = event.key === "ArrowDown"
              ? monthStarts.find((offset) => offset > scrollTop + 1)
              : [...monthStarts].reverse().find((offset) => offset < scrollTop - 1);
            if (target !== undefined) onJump(target);
          }
        }}
      >
        {marks.months.map((mark) => (
          <span key={mark.key} className="photo-timeline-dot" style={{ top: mark.y }} aria-hidden="true" />
        ))}
        {marks.years.map((mark) => (
          <span key={mark.key} className="photo-timeline-year" style={{ top: mark.y }} aria-hidden="true">{mark.label}</span>
        ))}
        <span className="photo-timeline-cursor" style={{ top: position * railHeight }} aria-hidden="true">
          {current ? <span className="photo-timeline-cursor-label">{monthOf(current.date)}</span> : null}
        </span>
        {hover !== null && hoverDate ? (
          <span className="photo-timeline-hover" style={{ top: (hover / scrollable) * railHeight }} aria-hidden="true">
            {monthOf(hoverDate)}
          </span>
        ) : null}
      </div>
    </div>
  );
}
