"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import type { Route } from "next";
import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import type { AnalyticsChartSeries } from "@/components/admin/admin-analytics-chart";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { StatusBanner } from "@/components/ui/status-banner";
import { Tabs } from "@/components/ui/tabs";
import { browserApiFetch } from "@/lib/api/client";
import { CHART_COLORS } from "@/lib/constants/chart-colors";
import { formatDate, formatFileSize, formatRappen } from "@/lib/utils/format";
import type { AnalyticsFeatures, AnalyticsRange, AnalyticsSeries, AnalyticsSeriesKey } from "@/types/admin-analytics";

// recharts erst im Browser nachladen (Muster admin-cashflow-chart.tsx).
const AnalyticsChart = dynamic(() => import("@/components/admin/admin-analytics-chart").then((m) => m.AnalyticsChart), { ssr: false });

type TFunc = ReturnType<typeof useTranslations>;

export const ANALYTICS_TABS: AnalyticsSeriesKey[] = ["growth", "usage", "features", "revenue", "load", "storage", "errors"];
// Nutzung (Anmeldungen) und Fehler kommen aus Owner-Quellen (audit_log, system_error_log).
export const OWNER_ONLY_TABS: AnalyticsSeriesKey[] = ["usage", "errors"];
const RANGES: AnalyticsRange[] = ["30d", "90d", "12m"];

type MetricDef = { key: string; kind: "line" | "bar"; color: string; format: "count" | "bytes" | "rappen" | "ms" | "mb" | "percent" };

const SERIES_DEFS: Record<Exclude<AnalyticsSeriesKey, "features">, MetricDef[]> = {
  growth: [
    { key: "tenants.total", kind: "line", color: CHART_COLORS.analyticsTenants, format: "count" },
    { key: "users.total", kind: "line", color: CHART_COLORS.analyticsUsers, format: "count" },
    { key: "tenants.new", kind: "bar", color: CHART_COLORS.analyticsNew, format: "count" },
  ],
  usage: [
    { key: "users.active_30d", kind: "line", color: CHART_COLORS.analyticsUsers, format: "count" },
    { key: "logins.success", kind: "bar", color: CHART_COLORS.analyticsLoginSuccess, format: "count" },
    { key: "logins.failure", kind: "bar", color: CHART_COLORS.analyticsLoginFailure, format: "count" },
  ],
  revenue: [{ key: "mrr_rp", kind: "line", color: CHART_COLORS.analyticsRevenue, format: "rappen" }],
  load: [
    { key: "postgres.latency_ms.avg", kind: "line", color: CHART_COLORS.analyticsLoad, format: "ms" },
    { key: "postgres.latency_ms.max", kind: "line", color: CHART_COLORS.analyticsErrors, format: "ms" },
    { key: "postgres.connections.max", kind: "bar", color: CHART_COLORS.analyticsTenants, format: "count" },
    { key: "redis.used_mb.max", kind: "line", color: CHART_COLORS.analyticsUsers, format: "mb" },
    { key: "runtime.loop_lag_ms.max", kind: "line", color: CHART_COLORS.analyticsNew, format: "ms" },
  ],
  storage: [{ key: "storage.bytes_total", kind: "line", color: CHART_COLORS.analyticsStorage, format: "bytes" }],
  errors: [{ key: "errors.total", kind: "bar", color: CHART_COLORS.analyticsErrors, format: "count" }],
};

// Metrik-Schlüssel enthalten Punkte - für die Übersetzung und recharts (dataKey) ersetzen.
function metricId(key: string): string {
  return key.replace(/\./g, "_");
}

function formatBucket(bucket: string): string {
  // Tag (JJJJ-MM-TT) wie überall TT.MM.JJJJ; Monat (JJJJ-MM) als MM.JJJJ.
  if (bucket.length === 7) return `${bucket.slice(5, 7)}.${bucket.slice(0, 4)}`; // i18n-ok: festes Datumsformat, kein UI-Text
  return formatDate(bucket);
}

function isTab(value: string | null): value is AnalyticsSeriesKey {
  return value !== null && (ANALYTICS_TABS as string[]).includes(value);
}

export function AdminAnalytics({ isOwner }: { isOwner: boolean }) {
  const t = useTranslations("adminAnalytics");
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const tabs = useMemo(() => ANALYTICS_TABS.filter((tab) => isOwner || !OWNER_ONLY_TABS.includes(tab)), [isOwner]);
  const requested = searchParams.get("tab");
  const activeTab: AnalyticsSeriesKey = isTab(requested) && tabs.includes(requested) ? requested : "growth";
  const [range, setRange] = useState<AnalyticsRange>("90d");

  const selectTab = useCallback(
    (id: string) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("tab", id);
      router.replace(`${pathname}?${params.toString()}` as Route, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  return (
    <div className="grid admin-analytics-page">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("title")}</h1>
          <p className="muted">{t("subtitle")}</p>
        </div>
        <FilterTabs<AnalyticsRange>
          options={RANGES.map((value) => ({ value, label: t(`range.${value}`) }))}
          value={range}
          onChange={setRange}
        />
      </div>
      <Tabs
        activeId={activeTab}
        onChange={selectTab}
        tabs={tabs.map((tab) => ({
          id: tab,
          label: t(`tabs.${tab}`),
          content: tab === activeTab ? <AnalyticsPanel key={`${tab}-${range}`} t={t} series={tab} range={range} /> : null,
        }))}
      />
    </div>
  );
}

function AnalyticsPanel({ t, series, range }: { t: TFunc; series: AnalyticsSeriesKey; range: AnalyticsRange }) {
  const [data, setData] = useState<AnalyticsSeries | AnalyticsFeatures | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    browserApiFetch<AnalyticsSeries | AnalyticsFeatures>(`/api/admin/analytics/${series}?range=${range}`, { signal: controller.signal })
      .then(setData)
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [series, range]);

  if (failed) return <StatusBanner tone="error" message={t("loadFailed")} />;
  if (!data) return <p className="muted">{t("loading")}</p>;
  if (data.series === "features") return <FeaturesPanel t={t} data={data as AnalyticsFeatures} />;
  return <SeriesPanel t={t} data={data as AnalyticsSeries} />;
}

function CollectingNote({ t, since }: { t: TFunc; since: string | null }) {
  return (
    <p className="muted admin-analytics-note">
      {since ? t("collectingSince", { date: formatDate(since) }) : t("noData")}
    </p>
  );
}

function useValueFormatter() {
  const locale = useLocale();
  return useCallback(
    (format: MetricDef["format"], value: number | null | undefined): string => {
      if (value === null || value === undefined || Number.isNaN(value)) return "–";
      const number = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
      switch (format) {
        case "bytes":
          return formatFileSize(value, locale);
        case "rappen":
          return formatRappen(Math.round(value), locale);
        case "ms":
          return `${number.format(value)} ms`; // i18n-ok: Einheit
        case "mb":
          return `${number.format(value)} MB`; // i18n-ok: Einheit
        case "percent":
          return `${number.format(value)} %`; // i18n-ok: Einheit
        default:
          return number.format(value);
      }
    },
    [locale],
  );
}

function SeriesPanel({ t, data }: { t: TFunc; data: AnalyticsSeries }) {
  const formatValue = useValueFormatter();
  const summaryId = useId();
  const defs = SERIES_DEFS[data.series as Exclude<AnalyticsSeriesKey, "features">];
  const rows = data.points.map((point) => {
    const row: Record<string, string | number | null> = { label: formatBucket(point.bucket) };
    for (const def of defs) row[metricId(def.key)] = point.values[def.key] ?? null;
    return row;
  });
  const chartSeries: AnalyticsChartSeries[] = defs.map((def) => ({
    key: metricId(def.key),
    label: t(`metrics.${metricId(def.key)}`),
    color: def.color,
    kind: def.kind,
  }));
  const formatByKey = (key: string, value: number) => formatValue(defs.find((def) => metricId(def.key) === key)?.format ?? "count", value);
  const axisFormat = defs[0]?.format ?? "count";
  const last = data.points.at(-1);

  return (
    <div className="grid">
      <CollectingNote t={t} since={data.collecting_since} />
      {data.points.length === 0 ? (
        <EmptyState title={t("emptyTitle")} description={t("emptyDescription")} />
      ) : (
        <section className="panel admin-analytics-panel">
          <p id={summaryId} className="admin-analytics-summary">
            {last
              ? t("summary", {
                  date: formatBucket(last.bucket),
                  values: defs.map((def) => `${t(`metrics.${metricId(def.key)}`)} ${formatValue(def.format, last.values[def.key])}`).join(" · "),
                })
              : null}
          </p>
          <AnalyticsChart rows={rows} series={chartSeries} formatValue={formatByKey} formatAxis={(value) => formatValue(axisFormat, value)} describedBy={summaryId} />
          <details className="admin-analytics-table">
            <summary>{t("showTable")}</summary>
            <DataTable columns={[{ key: "bucket", label: t(data.bucket === "month" ? "columns.month" : "columns.day") }, ...defs.map((def) => ({ key: def.key, label: t(`metrics.${metricId(def.key)}`) }))]}>
              {data.points.map((point) => (
                <tr key={point.bucket}>
                  <td>{formatBucket(point.bucket)}</td>
                  {defs.map((def) => (
                    <td key={def.key}>{formatValue(def.format, point.values[def.key])}</td>
                  ))}
                </tr>
              ))}
            </DataTable>
          </details>
        </section>
      )}
      {data.series === "load" ? <p className="muted">{t("loadRetention")}</p> : null}
      {data.series === "storage" && data.top_tenants ? <TopTenants t={t} items={data.top_tenants} /> : null}
    </div>
  );
}

function TopTenants({ t, items }: { t: TFunc; items: NonNullable<AnalyticsSeries["top_tenants"]> }) {
  const formatValue = useValueFormatter();
  return (
    <section className="panel admin-analytics-panel">
      <h2 className="admin-analytics-heading">{t("topTenants.title")}</h2>
      <DataTable columns={[{ key: "name", label: t("topTenants.tenant") }, { key: "bytes", label: t("topTenants.storage") }]} emptyMessage={t("noData")}>
        {items.map((item) => (
          <tr key={item.tenant_id}>
            <td>
              <Link href={`/admin/tenants/${item.tenant_id}` as Route}>{item.name}</Link>
            </td>
            <td>{formatValue("bytes", item.bytes)}</td>
          </tr>
        ))}
      </DataTable>
    </section>
  );
}

function FeaturesPanel({ t, data }: { t: TFunc; data: AnalyticsFeatures }) {
  const tCommon = useTranslations("common");
  const formatValue = useValueFormatter();
  return (
    <div className="grid">
      <CollectingNote t={t} since={data.collecting_since} />
      <section className="panel admin-analytics-panel">
        <h2 className="admin-analytics-heading">
          {data.as_of ? t("features.title", { date: formatDate(data.as_of), total: data.tenants_total }) : t("features.titleNoDate")}
        </h2>
        <DataTable
          columns={[
            { key: "feature", label: t("features.feature") },
            { key: "tenants", label: t("features.tenants") },
            { key: "share", label: t("features.share") },
          ]}
          emptyMessage={t("noData")}
        >
          {data.items.map((item) => (
            <tr key={item.code}>
              <td>{tCommon.has(`features.${item.code}`) ? tCommon(`features.${item.code}`) : item.code}</td>
              <td>{formatValue("count", item.tenants)}</td>
              <td>
                <div className="admin-analytics-share">
                  <meter className="admin-analytics-meter" min={0} max={1} value={item.share ?? 0} aria-label={t("features.share")} />
                  <span>{item.share === null ? "–" : formatValue("percent", item.share * 100)}</span>
                </div>
              </td>
            </tr>
          ))}
        </DataTable>
      </section>
    </div>
  );
}
