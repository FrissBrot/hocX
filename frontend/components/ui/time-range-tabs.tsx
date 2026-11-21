"use client";

import { useTranslations } from "next-intl";

import { FilterTabs } from "@/components/ui/filter-tabs";

export type TimeRange = "24h" | "7d" | "30d" | "90d" | "12m";

/** Zeitraum-Umschalter (24h/7d/30d/90d[/12m]) als FilterTabs-Variante; Tastatur wie FilterTabs (Pfeile). */
export function TimeRangeTabs<T extends TimeRange>({
  value,
  onChange,
  ranges,
}: {
  value: T;
  onChange: (value: T) => void;
  ranges: readonly T[];
}) {
  const t = useTranslations("common.timeRange");
  return <FilterTabs options={ranges.map((range) => ({ value: range, label: t(range as TimeRange) }))} value={value} onChange={onChange} />;
}
