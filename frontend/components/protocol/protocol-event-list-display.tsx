"use client";

import type { CSSProperties } from "react";
import { useLocale, useTranslations } from "next-intl";

import { FilterTabs } from "@/components/ui/filter-tabs";
import { splitTags } from "@/lib/element-types/event-filter";
import { formatDate, formatDateRange, formatDateTileParts } from "@/lib/utils/format";

// Darstellung der Terminliste im Protokoll-Editor (Design «Termine, Listen & Pendenzen»):
// Kalender-Kachel statt Datumstext, Tag-Punkt unter dem Titel, Trennzeile an der Sitzung und
// Umschalter «Alle/Kommend». Nur Anzeige - Spaltenwahl, Filter und PDF bleiben unverändert.

type TagColorConfig = Record<string, { color?: string } | undefined>;

type EventDates = { event_date: string; event_end_date?: string | null };

/** Vergangen = Enddatum (sonst Datum) vor dem Sitzungsdatum - dieselbe Regel wie bisher. */
export function isEventBeforeSession(event: EventDates, protocolDate: string | null | undefined): boolean {
  const endDate = event.event_end_date || event.event_date;
  return !!protocolDate && endDate < protocolDate;
}

export type EventTimeline = {
  /** je Zeile: liegt vor der Sitzung */
  past: boolean[];
  pastCount: number;
  upcomingCount: number;
  /** Index der ersten Zeile nach dem Wechsel vergangen/kommend (Trennzeile davor), sonst -1 */
  boundaryIndex: number;
  /** true: Wechsel von vergangen zu kommend (aufsteigend), false: kommend zu vergangen (absteigend) */
  boundaryStartsUpcoming: boolean;
  /** erste kommende Zeile (Autoscroll), sonst -1 */
  firstUpcomingIndex: number;
};

export function eventTimeline(rows: EventDates[], protocolDate: string | null | undefined): EventTimeline {
  const past = rows.map((row) => isEventBeforeSession(row, protocolDate));
  const pastCount = past.filter(Boolean).length;
  const boundaryIndex = past.findIndex((value, index) => index > 0 && value !== past[index - 1]);
  return {
    past,
    pastCount,
    upcomingCount: rows.length - pastCount,
    boundaryIndex,
    boundaryStartsUpcoming: boundaryIndex > 0 ? !past[boundaryIndex] : true,
    firstUpcomingIndex: past.findIndex((value) => !value),
  };
}

/** Erste konfigurierte Farbe der Tags eines Termins (wie eventRowTintStyle). */
export function eventTagColor(tag: string | null | undefined, tagConfig: TagColorConfig): string | null {
  return splitTags(tag).map((item) => tagConfig[item]?.color).find(Boolean) ?? null;
}

export function EventDateTile({
  date,
  endDate,
  color,
}: {
  date: string;
  endDate?: string | null;
  color?: string | null;
}) {
  const locale = useLocale();
  const t = useTranslations("protocols.tables");
  const parts = formatDateTileParts(date, locale);
  const hasEnd = !!endDate && endDate !== date;
  // Tag-Farbe ist ein Laufzeitwert (Tag-Konfiguration) - nur als Variable, die Optik kommt aus der Klasse
  const style = color ? ({ "--protocol-event-tile-color": color } as CSSProperties) : undefined;
  return (
    <div className="protocol-event-date">
      <span className="protocol-event-tile" style={style} aria-hidden="true">
        <span className="protocol-event-tile-month">{parts.month}</span>
        <span className="protocol-event-tile-day">{parts.day ? String(Number(parts.day)) : ""}</span>
        <span className="protocol-event-tile-weekday">{parts.weekday}</span>
      </span>
      {hasEnd ? (
        <span className="protocol-event-until" aria-hidden="true">
          {t("eventUntil", { date: formatDate(endDate) })}
        </span>
      ) : null}
      <span className="visually-hidden">{formatDateRange(date, endDate)}</span>
    </div>
  );
}

/** Tags als farbiger Punkt plus Name unter dem Titel. */
export function EventTagLine({ tag, tagConfig }: { tag: string | null | undefined; tagConfig: TagColorConfig }) {
  const tags = splitTags(tag);
  if (!tags.length) return null;
  return (
    <span className="protocol-event-tags">
      {tags.map((item) => {
        const color = tagConfig[item]?.color;
        return (
          <span key={item} className="protocol-event-tag">
            <span
              className="protocol-event-tag-dot"
              style={color ? ({ "--protocol-event-tile-color": color } as CSSProperties) : undefined}
              aria-hidden="true"
            />
            {item}
          </span>
        );
      })}
    </span>
  );
}

/** Zusammenfassung «X kommend · Y vergangen» und Umschalter Alle/Kommend (nur mit vergangenen Terminen). */
export function EventListToolbar({
  timeline,
  upcomingOnly,
  onChangeUpcomingOnly,
}: {
  timeline: EventTimeline;
  upcomingOnly: boolean;
  onChangeUpcomingOnly: (value: boolean) => void;
}) {
  const t = useTranslations("protocols.tables");
  return (
    <div className="protocol-event-toolbar">
      <span className="protocol-event-summary">
        {t("eventSummary", { upcoming: timeline.upcomingCount, past: timeline.pastCount })}
      </span>
      {timeline.pastCount > 0 ? (
        <FilterTabs
          value={upcomingOnly ? "upcoming" : "all"}
          onChange={(value) => onChangeUpcomingOnly(value === "upcoming")}
          options={[
            { value: "all", label: t("eventFilterAll"), count: timeline.upcomingCount + timeline.pastCount },
            { value: "upcoming", label: t("eventFilterUpcoming"), count: timeline.upcomingCount },
          ]}
        />
      ) : null}
    </div>
  );
}

/** Trennzeile an der Sitzungsgrenze. */
export function EventSessionSeparator({
  colSpan,
  protocolDate,
  startsUpcoming,
}: {
  colSpan: number;
  protocolDate: string | null | undefined;
  startsUpcoming: boolean;
}) {
  const t = useTranslations("protocols.tables");
  const date = formatDate(protocolDate);
  const label = startsUpcoming
    ? date ? t("eventSeparatorFromDate", { date }) : t("eventSeparatorFrom")
    : date ? t("eventSeparatorBeforeDate", { date }) : t("eventSeparatorBefore");
  return (
    <tr className="protocol-event-separator">
      <td colSpan={colSpan}>
        <span className="protocol-event-separator-label">{label}</span>
      </td>
    </tr>
  );
}
