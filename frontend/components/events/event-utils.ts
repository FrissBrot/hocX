import { TAG_COLORS } from "@/components/ui/tag-input";
import { EventSummary } from "@/types/api";

export function effectiveEndDate(event: EventSummary): string {
  return event.event_end_date || event.event_date;
}

export function isoToUtcDate(iso: string): Date {
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(year, (month || 1) - 1, day || 1));
}

export function utcDateToIso(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function addUtcDays(iso: string, days: number): string {
  const date = isoToUtcDate(iso);
  date.setUTCDate(date.getUTCDate() + days);
  return utcDateToIso(date);
}

/** Anzahl Kalendertage von `start` bis `end` (beide inklusive). */
export function daySpan(start: string, end: string): number {
  return Math.round((isoToUtcDate(end).getTime() - isoToUtcDate(start).getTime()) / 86_400_000) + 1;
}

// Tags ohne konfigurierte Farbe bekommen stabil eine Farbe aus der Tag-Palette.
export function fallbackTagColor(tag: string): string {
  let hash = 0;
  for (let index = 0; index < tag.length; index += 1) {
    hash = (hash * 31 + tag.charCodeAt(index)) | 0;
  }
  return TAG_COLORS[Math.abs(hash) % TAG_COLORS.length];
}

/** Ordnet jeden Kalendertag den Terminen zu, die an ihm stattfinden (mehrtägige auf jedem Tag). */
export function eventsByDay(events: EventSummary[]): Map<string, EventSummary[]> {
  const map = new Map<string, EventSummary[]>();
  events.forEach((event) => {
    const end = effectiveEndDate(event);
    let day = event.event_date.slice(0, 10);
    // Obergrenze schützt vor fehlerhaften Enddaten (z. B. Jahrzehnte in der Zukunft).
    for (let guard = 0; guard < 366 && day <= end; guard += 1) {
      const list = map.get(day);
      if (list) list.push(event);
      else map.set(day, [event]);
      day = addUtcDays(day, 1);
    }
  });
  map.forEach((list) => list.sort((left, right) => left.event_date.localeCompare(right.event_date) || left.title.localeCompare(right.title)));
  return map;
}
