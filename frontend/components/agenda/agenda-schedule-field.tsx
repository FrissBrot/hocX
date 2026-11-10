"use client";

import { useMemo } from "react";
import { useLocale, useTranslations } from "next-intl";

import { FilterTabs } from "@/components/ui/filter-tabs";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { formatMonthYear } from "@/lib/utils/format";
import { AgendaSchedule } from "@/types/api";

const MONTHS_AHEAD = 24;

/** Monatserste ab dem laufenden Monat als ISO-Datum (JJJJ-MM-01). */
export function upcomingMonths(today: Date = new Date(), count: number = MONTHS_AHEAD): string[] {
  const result: string[] = [];
  for (let offset = 0; offset < count; offset += 1) {
    const date = new Date(today.getFullYear(), today.getMonth() + offset, 1);
    result.push(`${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-01`);
  }
  return result;
}

export function AgendaScheduleField({
  value,
  onChange,
}: {
  value: AgendaSchedule;
  onChange: (value: AgendaSchedule) => void;
}) {
  const t = useTranslations("agenda");
  const locale = useLocale();
  const months = useMemo(() => {
    const list = upcomingMonths();
    // Ein gespeicherter Monat in der Vergangenheit bleibt wählbar statt still zu verschwinden.
    if (value.month && !list.includes(value.month)) list.unshift(value.month);
    return list.map((month) => ({ id: month, label: formatMonthYear(month, locale) }));
  }, [locale, value.month]);

  return (
    <div className="field-stack">
      <span className="field-label">{t("fieldSchedule")}</span>
      <FilterTabs
        options={[
          { value: "next_meeting", label: t("scheduleNextMeeting") },
          { value: "month", label: t("fieldMonth") },
        ]}
        value={value.kind}
        onChange={(kind) => onChange(kind === "month" ? { kind, month: value.month ?? months[1]?.id ?? months[0].id } : { kind })}
      />
      {value.kind === "month" && (
        <SearchableSelect
          options={months}
          getId={(option) => option.id}
          getLabel={(option) => option.label}
          value={value.month ?? null}
          onChange={(option) => option && onChange({ kind: "month", month: option.id })}
        />
      )}
      <span className="field-help">{value.kind === "month" ? t("scheduleHelpMonth") : t("scheduleHelpNext")}</span>
    </div>
  );
}
