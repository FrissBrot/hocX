"use client";

import dynamic from "next/dynamic";
import { useCallback, useId } from "react";
import { useLocale, useTranslations } from "next-intl";

import type { AnalyticsChartSeries } from "@/components/admin/admin-analytics-chart";
import { DataTable } from "@/components/ui/data-table";
import { formatDate, formatDateTime, formatFileSize } from "@/lib/utils/format";

// Gemeinsamer Verlauf für Betrieb (Datenbank/Redis), Speicher-Belegung und Mandanten-Nutzung (1.5.1):
// Diagramm (recharts lazy) + Zusammenfassung über aria-describedby + «Daten als Tabelle» (DESIGN §11).

const AnalyticsChart = dynamic(() => import("@/components/admin/admin-analytics-chart").then((m) => m.AnalyticsChart), { ssr: false });

export type MetricFormat = "count" | "bytes" | "ms" | "mb";
export type MetricDef = { key: string; label: string; kind: "line" | "bar"; color: string; format: MetricFormat };
export type MetricPoint = { bucket: string; values: Record<string, number | undefined> };

export function useMetricFormatter() {
  const locale = useLocale();
  return useCallback(
    (format: MetricFormat, value: number | null | undefined): string => {
      if (value === null || value === undefined || Number.isNaN(value)) return "–";
      const number = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
      switch (format) {
        case "bytes":
          return formatFileSize(value, locale);
        case "ms":
          return `${number.format(value)} ms`; // i18n-ok: Einheit
        case "mb":
          return `${number.format(value)} MB`; // i18n-ok: Einheit
        default:
          return number.format(value);
      }
    },
    [locale],
  );
}

/** Tag (JJJJ-MM-TT) → TT.MM.JJJJ, Monat (JJJJ-MM) → MM.JJJJ, Zeitpunkt → Datum und Uhrzeit. */
export function useBucketFormatter() {
  const locale = useLocale();
  return useCallback(
    (bucket: string) => {
      if (bucket.length === 7) return `${bucket.slice(5, 7)}.${bucket.slice(0, 4)}`; // i18n-ok: festes Datumsformat
      if (bucket.length === 10) return formatDate(bucket);
      return formatDateTime(bucket, locale);
    },
    [locale],
  );
}

export function MetricHistory({ points, defs, bucketLabel }: { points: MetricPoint[]; defs: MetricDef[]; bucketLabel: string }) {
  const t = useTranslations("admin.metricHistory");
  const formatValue = useMetricFormatter();
  const formatBucket = useBucketFormatter();
  const summaryId = useId();
  const id = (key: string) => key.replace(/\./g, "_");
  const rows = points.map((point) => {
    const row: Record<string, string | number | null> = { label: formatBucket(point.bucket) };
    for (const def of defs) row[id(def.key)] = point.values[def.key] ?? null;
    return row;
  });
  const series: AnalyticsChartSeries[] = defs.map((def) => ({ key: id(def.key), label: def.label, color: def.color, kind: def.kind }));
  const formatByKey = (key: string, value: number) => formatValue(defs.find((def) => id(def.key) === key)?.format ?? "count", value);
  const last = points.at(-1);
  if (points.length === 0) return <p className="muted">{t("empty")}</p>;
  return (
    <div className="admin-analytics-panel">
      <p id={summaryId} className="admin-analytics-summary">
        {last
          ? t("summary", {
              time: formatBucket(last.bucket),
              values: defs.map((def) => `${def.label} ${formatValue(def.format, last.values[def.key])}`).join(" · "),
            })
          : null}
      </p>
      <AnalyticsChart rows={rows} series={series} formatValue={formatByKey} formatAxis={(value) => formatValue(defs[0]?.format ?? "count", value)} describedBy={summaryId} />
      <details className="admin-analytics-table">
        <summary>{t("showTable")}</summary>
        <DataTable columns={[{ key: "bucket", label: bucketLabel }, ...defs.map((def) => ({ key: def.key, label: def.label }))]}>
          {points.map((point) => (
            <tr key={point.bucket}>
              <td>{formatBucket(point.bucket)}</td>
              {defs.map((def) => (
                <td key={def.key}>{formatValue(def.format, point.values[def.key])}</td>
              ))}
            </tr>
          ))}
        </DataTable>
      </details>
    </div>
  );
}
