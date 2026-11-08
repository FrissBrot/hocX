"use client";

import { useMemo } from "react";
import { useLocale, useTranslations } from "next-intl";
import { formatDate, formatWeekdayDate } from "@/lib/utils/format";
import { smartDateSuggestions, type SmartDateCandidate } from "@/lib/utils/smart-dates";

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
