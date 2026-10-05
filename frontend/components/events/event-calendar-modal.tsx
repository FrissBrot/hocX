"use client";

import { useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { EventIcon } from "@/components/events/event-icons";
import { addUtcDays, effectiveEndDate, eventsByDay, isoToUtcDate, utcDateToIso } from "@/components/events/event-utils";
import { Badge } from "@/components/ui/badge";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal } from "@/components/ui/modal";
import { toIntlLocale } from "@/lib/utils/format";
import { EventSummary } from "@/types/api";

type CalendarView = "month" | "year";

type Props = {
  open: boolean;
  onClose: () => void;
  events: EventSummary[];
  todayIso: string;
  tagColor: (tag: string) => string;
  onOpenEvent: (event: EventSummary) => void;
  onCreateForDate: (iso: string) => void;
};

function monthStartIso(year: number, month: number): string {
  return utcDateToIso(new Date(Date.UTC(year, month, 1)));
}

function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
}

/** Montag = 0 … Sonntag = 6 */
function weekdayIndex(iso: string): number {
  return (isoToUtcDate(iso).getUTCDay() + 6) % 7;
}

/** Tage eines Monatsrasters, beginnend am Montag vor dem Monatsersten, volle Wochen. */
function monthGridDays(year: number, month: number): string[] {
  const first = monthStartIso(year, month);
  const start = addUtcDays(first, -weekdayIndex(first));
  const total = Math.ceil((weekdayIndex(first) + daysInMonth(year, month)) / 7) * 7;
  return Array.from({ length: total }, (_, index) => addUtcDays(start, index));
}

/** Höchstens so viele Terminbalken übereinander pro Woche, der Rest erscheint als „+N". */
const MAX_LANES = 3;

type WeekSegment = {
  event: EventSummary;
  /** Spalte 0–6 innerhalb der Woche */
  start: number;
  span: number;
  lane: number;
  continuesBefore: boolean;
  continuesAfter: boolean;
};

/**
 * Zerlegt die Termine einer Woche in durchgehende Balken (mehrtägige Termine als ein Segment pro
 * Woche) und verteilt sie auf Zeilen, sodass sich keine Balken überschneiden.
 */
function weekSegments(week: string[], dayMap: Map<string, EventSummary[]>): WeekSegment[] {
  const seen = new Set<string>();
  const segments: Omit<WeekSegment, "lane">[] = [];
  week.forEach((day, column) => {
    (dayMap.get(day) ?? []).forEach((event) => {
      if (seen.has(event.id)) return;
      seen.add(event.id);
      let end = column;
      while (end + 1 < week.length && (dayMap.get(week[end + 1]) ?? []).includes(event)) end += 1;
      segments.push({
        event,
        start: column,
        span: end - column + 1,
        continuesBefore: event.event_date.slice(0, 10) < day,
        continuesAfter: effectiveEndDate(event) > week[end],
      });
    });
  });
  // Längere Balken zuerst, damit sie oben durchgehend liegen.
  segments.sort((left, right) => left.start - right.start || right.span - left.span || left.event.title.localeCompare(right.event.title));
  const laneEnds: number[] = [];
  return segments.map((segment) => {
    let lane = laneEnds.findIndex((lastColumn) => lastColumn < segment.start);
    if (lane === -1) lane = laneEnds.length;
    laneEnds[lane] = segment.start + segment.span - 1;
    return { ...segment, lane };
  });
}

/** Anzahl Termine an einem Wochentag, die wegen MAX_LANES keinen eigenen Balken bekommen. */
function hiddenSegmentCount(segments: WeekSegment[], column: number): number {
  return segments.filter((segment) => {
    const covers = segment.start <= column && column < segment.start + segment.span;
    return covers && segment.lane >= MAX_LANES;
  }).length;
}

function chunkWeeks(days: string[]): string[][] {
  return Array.from({ length: days.length / 7 }, (_, index) => days.slice(index * 7, index * 7 + 7));
}

function tagStyle(color: string) {
  return { "--tag-color": color } as React.CSSProperties;
}

export function EventCalendarModal({ open, onClose, events, todayIso, tagColor, onOpenEvent, onCreateForDate }: Props) {
  const t = useTranslations("events");
  const locale = useLocale();
  const intlLocale = toIntlLocale(locale);
  const [view, setView] = useState<CalendarView>("month");
  const [cursor, setCursor] = useState(() => ({ year: 2000, month: 0 }));
  const [selectedIso, setSelectedIso] = useState(todayIso);

  // Beim Öffnen immer auf heute springen.
  useEffect(() => {
    if (!open) return;
    const today = isoToUtcDate(todayIso);
    setCursor({ year: today.getUTCFullYear(), month: today.getUTCMonth() });
    setSelectedIso(todayIso);
  }, [open, todayIso]);

  const dayMap = useMemo(() => eventsByDay(events), [events]);

  const formatters = useMemo(
    () => ({
      monthYear: new Intl.DateTimeFormat(intlLocale, { month: "long", year: "numeric", timeZone: "UTC" }),
      month: new Intl.DateTimeFormat(intlLocale, { month: "long", timeZone: "UTC" }),
      dayMonthShort: new Intl.DateTimeFormat(intlLocale, { day: "numeric", month: "short", timeZone: "UTC" }),
      weekdayShort: new Intl.DateTimeFormat(intlLocale, { weekday: "short", timeZone: "UTC" }),
      weekdayNarrow: new Intl.DateTimeFormat(intlLocale, { weekday: "narrow", timeZone: "UTC" }),
      dayLong: new Intl.DateTimeFormat(intlLocale, { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" }),
    }),
    [intlLocale]
  );

  // 2024-01-01 war ein Montag: daraus die lokalisierten Wochentagsnamen ableiten.
  const weekdayLabels = useMemo(
    () =>
      Array.from({ length: 7 }, (_, index) => {
        const date = isoToUtcDate(addUtcDays("2024-01-01", index));
        return { short: formatters.weekdayShort.format(date).replace(/\.$/, ""), narrow: formatters.weekdayNarrow.format(date) };
      }),
    [formatters]
  );

  const monthStats = useMemo(() => {
    const total = daysInMonth(cursor.year, cursor.month);
    const first = monthStartIso(cursor.year, cursor.month);
    let busy = 0;
    for (let index = 0; index < total; index += 1) {
      if (dayMap.has(addUtcDays(first, index))) busy += 1;
    }
    return { total, busy };
  }, [cursor, dayMap]);

  const yearStats = useMemo(() => {
    const prefix = `${cursor.year}-`;
    let busy = 0;
    dayMap.forEach((_, day) => {
      if (day.startsWith(prefix)) busy += 1;
    });
    const yearEvents = events.filter((event) => event.event_date.startsWith(prefix) || (event.event_end_date ?? "").startsWith(prefix));
    const tags = Array.from(new Set(yearEvents.map((event) => (event.tag ?? "").trim()).filter(Boolean))).sort((left, right) => left.localeCompare(right));
    return { busy, count: yearEvents.length, tags };
  }, [cursor.year, dayMap, events]);

  function step(direction: -1 | 1) {
    setCursor((current) => {
      if (view === "year") return { ...current, year: current.year + direction };
      const next = new Date(Date.UTC(current.year, current.month + direction, 1));
      return { year: next.getUTCFullYear(), month: next.getUTCMonth() };
    });
  }

  function goToday() {
    const today = isoToUtcDate(todayIso);
    setCursor({ year: today.getUTCFullYear(), month: today.getUTCMonth() });
    setSelectedIso(todayIso);
  }

  function openMonth(month: number) {
    setCursor((current) => ({ ...current, month }));
    setView("month");
  }

  const selectedEvents = dayMap.get(selectedIso) ?? [];
  const title = view === "month" ? formatters.monthYear.format(new Date(Date.UTC(cursor.year, cursor.month, 1))) : String(cursor.year);
  const subtitle =
    view === "month"
      ? t("calendar.monthSummary", { busy: monthStats.busy, total: monthStats.total })
      : t("calendar.yearSummary", { count: yearStats.count, busy: yearStats.busy });

  function renderMonth() {
    return (
      <div className="event-cal-month" role="grid" aria-label={title}>
        <div className="event-cal-weekdays" role="row">
          {weekdayLabels.map((label) => (
            <div key={label.short} className="event-cal-weekday" role="columnheader">
              {label.short}
            </div>
          ))}
        </div>
        <div className="event-cal-days">
          {chunkWeeks(monthGridDays(cursor.year, cursor.month)).map((week) => {
            const segments = weekSegments(week, dayMap);
            const hiddenPerDay = week.map((_, column) => hiddenSegmentCount(segments, column));
            const isOutside = (day: string) => isoToUtcDate(day).getUTCMonth() !== cursor.month;
            return (
              <div key={week[0]} className="event-cal-week" role="row">
                {week.map((day, column) => {
                  const date = isoToUtcDate(day);
                  const outside = isOutside(day);
                  const hasEvents = dayMap.has(day);
                  const isWeekend = weekdayIndex(day) >= 5;
                  const label = date.getUTCDate() === 1 ? formatters.dayMonthShort.format(date).replace(/\.$/, "") : String(date.getUTCDate());
                  const className = [
                    "event-cal-day",
                    outside ? "event-cal-day-outside" : "",
                    isWeekend ? "event-cal-day-weekend" : "",
                    day === selectedIso ? "event-cal-day-selected" : "",
                    day === todayIso ? "event-cal-day-today" : "",
                  ]
                    .filter(Boolean)
                    .join(" ");
                  return (
                    <button
                      key={day}
                      type="button"
                      role="gridcell"
                      aria-selected={day === selectedIso}
                      aria-label={formatters.dayLong.format(date)}
                      className={className}
                      style={{ gridColumn: column + 1 }}
                      onClick={() => setSelectedIso(day)}
                    >
                      <span className={`event-cal-day-number${hasEvents ? " event-cal-day-number-busy" : ""}`}>{label}</span>
                    </button>
                  );
                })}
                {/* Balken liegen über den Tageszellen; Klicks gehen an die Zelle darunter (Tag auswählen). */}
                <div className="event-cal-week-events" aria-hidden="true">
                  {segments
                    .filter((segment) => segment.lane < MAX_LANES)
                    .map(({ event, start, span, lane, continuesBefore, continuesAfter }) => {
                      const tag = (event.tag ?? "").trim();
                      const fullyOutside = isOutside(week[start]) && isOutside(week[start + span - 1]);
                      const className = [
                        "event-cal-chip",
                        "event-cal-bar",
                        event.is_cancelled ? "event-cal-chip-cancelled" : "",
                        tag ? "" : "event-cal-chip-untagged",
                        fullyOutside ? "event-cal-chip-outside" : "",
                        continuesBefore ? "event-cal-bar-continues-before" : "",
                        continuesAfter ? "event-cal-bar-continues-after" : "",
                      ]
                        .filter(Boolean)
                        .join(" ");
                      return (
                        <span
                          key={event.id}
                          className={className}
                          style={{ ...(tag ? tagStyle(tagColor(tag)) : {}), gridColumn: `${start + 1} / span ${span}`, gridRow: lane + 1 }}
                        >
                          <span className="event-cal-chip-dot" />
                          <span className="event-cal-chip-label">{event.title}</span>
                        </span>
                      );
                    })}
                  {hiddenPerDay.map((count, column) =>
                    count > 0 ? (
                      <span key={`more-${column}`} className="event-cal-more" style={{ gridColumn: column + 1, gridRow: MAX_LANES + 1 }}>
                        {t("calendar.more", { count })}
                      </span>
                    ) : null
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  function renderYear() {
    return (
      <div className="event-cal-year">
        {yearStats.tags.length > 0 ? (
          <div className="event-cal-legend">
            {yearStats.tags.map((tag) => (
              <span key={tag} className="event-cal-legend-item" style={tagStyle(tagColor(tag))}>
                <span className="event-cal-legend-swatch" />
                {tag}
              </span>
            ))}
          </div>
        ) : null}
        <div className="event-cal-year-grid">
          {Array.from({ length: 12 }, (_, month) => {
            const first = monthStartIso(cursor.year, month);
            const total = daysInMonth(cursor.year, month);
            const monthEvents = new Set<string>();
            for (let index = 0; index < total; index += 1) {
              (dayMap.get(addUtcDays(first, index)) ?? []).forEach((event) => monthEvents.add(event.id));
            }
            return (
              <section key={month} className="event-cal-mini">
                <button type="button" className="event-cal-mini-head" onClick={() => openMonth(month)}>
                  <span className="event-cal-mini-title">{formatters.month.format(isoToUtcDate(first))}</span>
                  <span className="event-cal-mini-count">
                    {monthEvents.size > 0 ? t("calendar.eventCount", { count: monthEvents.size }) : t("calendar.free")}
                  </span>
                </button>
                <div className="event-cal-mini-grid">
                  {weekdayLabels.map((label, index) => (
                    <span key={index} className="event-cal-mini-weekday" aria-hidden="true">
                      {label.narrow}
                    </span>
                  ))}
                  {Array.from({ length: weekdayIndex(first) }, (_, index) => (
                    <span key={`pad-${index}`} />
                  ))}
                  {Array.from({ length: total }, (_, index) => {
                    const day = addUtcDays(first, index);
                    const dayEvents = dayMap.get(day) ?? [];
                    const tag = (dayEvents[0]?.tag ?? "").trim();
                    const className = [
                      "event-cal-mini-day",
                      dayEvents.length > 0 ? "event-cal-mini-day-busy" : "",
                      dayEvents.length > 0 && !tag ? "event-cal-mini-day-untagged" : "",
                      day === selectedIso ? "event-cal-mini-day-selected" : "",
                      day === todayIso ? "event-cal-mini-day-today" : "",
                    ]
                      .filter(Boolean)
                      .join(" ");
                    return (
                      <button
                        key={day}
                        type="button"
                        className={className}
                        style={tag ? tagStyle(tagColor(tag)) : undefined}
                        aria-label={formatters.dayLong.format(isoToUtcDate(day))}
                        aria-pressed={day === selectedIso}
                        title={dayEvents.map((event) => event.title).join(", ") || undefined}
                        onClick={() => setSelectedIso(day)}
                      >
                        {index + 1}
                      </button>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("calendar.title")}
      size="fullscreen"
      className="event-calendar-modal"
      header={
        <div className="event-cal-header">
          <div className="event-cal-nav">
            <button type="button" className="button-ghost button-icon event-cal-nav-button" onClick={() => step(-1)} aria-label={t("calendar.previous")}>
              <EventIcon name="chevronLeft" />
            </button>
            <button type="button" className="button-ghost button-icon event-cal-nav-button" onClick={() => step(1)} aria-label={t("calendar.next")}>
              <EventIcon name="chevronRight" />
            </button>
          </div>
          <div className="event-cal-heading">
            <h2 className="event-cal-title">{title}</h2>
            <p className="event-cal-subtitle">{subtitle}</p>
          </div>
          <button type="button" className="button-secondary button-ghost event-cal-today" onClick={goToday}>
            {t("calendar.today")}
          </button>
        </div>
      }
      headerActions={
        <FilterTabs<CalendarView>
          options={[
            { value: "month", label: t("calendar.viewMonth") },
            { value: "year", label: t("calendar.viewYear") },
          ]}
          value={view}
          onChange={setView}
        />
      }
    >
      <div className="event-cal-body">
        <div className="event-cal-main">{view === "month" ? renderMonth() : renderYear()}</div>
        <aside className="event-cal-side">
          <div className="event-cal-side-head">
            <span className="event-cal-side-eyebrow">
              {selectedEvents.length > 0 ? t("calendar.eventCount", { count: selectedEvents.length }) : t("calendar.freeDay")}
            </span>
            <h3 className="event-cal-side-title">{formatters.dayLong.format(isoToUtcDate(selectedIso))}</h3>
          </div>
          <div className="event-cal-side-body">
            {selectedEvents.length === 0 ? (
              <div className="event-cal-side-empty">
                <strong>{t("calendar.noEventTitle")}</strong>
                <span className="muted">{t("calendar.noEventDescription")}</span>
              </div>
            ) : (
              <div className="event-cal-side-list">
                {selectedEvents.map((event) => {
                  const tag = (event.tag ?? "").trim();
                  return (
                    <button key={event.id} type="button" className="event-cal-side-event" onClick={() => onOpenEvent(event)}>
                      <span className={`event-cal-side-event-title${event.is_cancelled ? " event-cal-side-event-cancelled" : ""}`}>{event.title}</span>
                      <span className="event-list-row-meta">
                        {tag ? (
                          <span className="badge event-tag-badge" style={tagStyle(tagColor(tag))}>
                            <span className="badge-dot" />
                            {tag}
                          </span>
                        ) : null}
                        {event.is_cancelled ? <Badge variant="danger">{t("columns.cancelled")}</Badge> : null}
                        {event.location ? (
                          <span className="event-list-meta-item">
                            <EventIcon name="pin" width={14} height={14} />
                            {event.location}
                          </span>
                        ) : null}
                        {(event.participant_count ?? 0) > 0 ? (
                          <span className="event-list-meta-item">
                            <EventIcon name="users" width={14} height={14} />
                            {event.participant_count}
                          </span>
                        ) : null}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
            <button type="button" className="button-primary event-cal-create" onClick={() => onCreateForDate(selectedIso)}>
              <EventIcon name="plus" />
              {t("calendar.createOnDay")}
            </button>
          </div>
        </aside>
      </div>
    </Modal>
  );
}
