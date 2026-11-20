// Reine Hilfsfunktionen der Bausteinliste (/elements) - ohne Hooks, übersetzte Texte kommen
// als `t` herein (Muster wie section-tabs.ts / mobile-utils.ts).
import { appCalendarDate, formatDayMonth, formatShortMonthDate } from "@/lib/utils/format";
import type { ElementDefinitionBlock } from "@/types/api";

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

export type TitleSegment = { text: string; placeholder: boolean };

// Platzhalter wie {cycle_year_start}, die beim Einfügen in eine Vorlage ersetzt werden.
const PLACEHOLDER_PATTERN = /\{[a-z][a-z0-9_]*\}/g;

/** Titel in Text und Platzhalter zerlegen ("Programm {cycle_year_start}" → Text + Pille). */
export function titleSegments(title: string): TitleSegment[] {
  const segments: TitleSegment[] = [];
  let last = 0;
  for (const match of title.matchAll(PLACEHOLDER_PATTERN)) {
    const index = match.index ?? 0;
    if (index > last) segments.push({ text: title.slice(last, index), placeholder: false });
    segments.push({ text: match[0], placeholder: true });
    last = index + match[0].length;
  }
  if (last < title.length) segments.push({ text: title.slice(last), placeholder: false });
  return segments;
}

/** Blocktypen eines Bausteins: eindeutig, in der Reihenfolge der Blöcke. */
export function contentTypeIds(blocks: ElementDefinitionBlock[]): number[] {
  const ids: number[] = [];
  for (const block of [...blocks].sort((left, right) => left.sort_index - right.sort_index)) {
    if (!ids.includes(block.element_type_id)) ids.push(block.element_type_id);
  }
  return ids;
}

// Bis zu dieser Anzahl Tage relativ («vor 3 Tagen»), danach als Datum.
const RELATIVE_DAYS = 14;

/** «Geändert heute / gestern / vor N Tagen / am 12. Sept.» - Keys unter `changed.*`. */
export function changedLabel(updatedAt: string, t: TFunc, locale: string, now: Date = new Date()): string {
  const day = appCalendarDate(updatedAt);
  const today = appCalendarDate(now);
  if (!day || !today) return "";
  const diff = Math.round((Date.parse(today) - Date.parse(day)) / 86_400_000);
  if (diff <= 0) return t("changed.today");
  if (diff === 1) return t("changed.yesterday");
  if (diff < RELATIVE_DAYS) return t("changed.daysAgo", { count: diff });
  const date = day.slice(0, 4) === today.slice(0, 4) ? formatDayMonth(updatedAt, locale) : formatShortMonthDate(updatedAt, locale);
  return t("changed.on", { date });
}
