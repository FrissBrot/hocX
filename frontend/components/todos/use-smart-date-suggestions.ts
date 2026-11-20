"use client";

import { useMemo } from "react";
import { useLocale, useTranslations } from "next-intl";
import { formatDate, formatWeekdayDate } from "@/lib/utils/format";
import { smartDateCandidates, smartDateSuggestions, type SmartDateCandidate } from "@/lib/utils/smart-dates";

export type SmartDateSuggestion = SmartDateCandidate & { label: string; subtle: string };

/** Wochentagsname in der UI-Sprache (1 = Montag … 7 = Sonntag); 05.01.2026 ist ein Montag. */
function weekdayName(weekday: number, locale: string): string {
  return new Intl.DateTimeFormat(locale, { weekday: "long" }).format(new Date(2026, 0, 4 + weekday));
}

/** Smarte Datumsvorschläge zum Getippten (siehe lib/utils/smart-dates.ts); leer ohne Eingabe. */
export function useSmartDateSuggestions(query: string): SmartDateSuggestion[] {
  const t = useTranslations("todos.smartDate");
  const tKeywords = useTranslations("todos.smartDateKeywords");
  const locale = useLocale();
  return useMemo(
    () =>
      smartDateSuggestions(query, (candidate) => {
        const weekday = candidate.weekday ? weekdayName(candidate.weekday, locale) : "";
        return {
          label: t(candidate.kind, { weekday, count: candidate.count ?? 0, date: formatDate(candidate.date) }),
          keywords: tKeywords.has(candidate.kind) ? tKeywords(candidate.kind) : "",
        };
      }).map((suggestion) => ({ ...suggestion, subtle: formatWeekdayDate(suggestion.date, locale) })),
    [query, locale, t, tKeywords]
  );
}

/** Vorschläge ohne Eingabe (Fällig-Liste der schnellen Pendenz): die häufigsten Fristen. */
const DEFAULT_SMART_DATES: Array<{ kind: SmartDateCandidate["kind"]; weekday?: number }> = [
  { kind: "tomorrow" },
  { kind: "dayAfterTomorrow" },
  { kind: "endOfWeek" },
  { kind: "weekdayNext", weekday: 5 },
  { kind: "inTwoWeeks" },
  { kind: "endOfMonth" },
];

/**
 * Smarte Daten ohne Eingabe: morgen, übermorgen, Ende Woche, nächster Freitag, in 2 Wochen,
 * Ende Monat (je Datum nur einmal) - gleiche Beschriftung wie {@link useSmartDateSuggestions}.
 */
export function useDefaultSmartDates(now?: Date): SmartDateSuggestion[] {
  const t = useTranslations("todos.smartDate");
  const locale = useLocale();
  const day = (now ?? new Date()).toDateString();
  return useMemo(() => {
    const candidates = smartDateCandidates("", new Date(day));
    const seen = new Set<string>();
    const result: SmartDateSuggestion[] = [];
    for (const wanted of DEFAULT_SMART_DATES) {
      const candidate = candidates.find((item) => item.kind === wanted.kind && (wanted.weekday === undefined || item.weekday === wanted.weekday));
      if (!candidate || seen.has(candidate.date)) continue;
      seen.add(candidate.date);
      const weekday = candidate.weekday ? weekdayName(candidate.weekday, locale) : "";
      result.push({
        ...candidate,
        label: t(candidate.kind, { weekday, count: 0, date: formatDate(candidate.date) }),
        subtle: formatWeekdayDate(candidate.date, locale),
      });
    }
    return result;
  }, [day, locale, t]);
}
