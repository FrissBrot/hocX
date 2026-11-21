"use client";

import Link from "next/link";
import type { Route } from "next";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { MetricHistory, useMetricFormatter, type MetricDef, type MetricPoint } from "@/components/admin/metric-history";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { CHART_COLORS } from "@/lib/constants/chart-colors";
import { formatDate } from "@/lib/utils/format";

// Betrieb (1.5.1, Plan §2 E): Verläufe Datenbank/Redis aus den Ressourcen-Stichproben und
// Speicher-Belegung aus dem täglichen Snapshot (metrics_rollup) - keine Live-Summen.

const HISTORY_RANGES = ["24h", "7d", "14d"] as const;
type HistoryRange = (typeof HISTORY_RANGES)[number];

type SystemHistory = { range: HistoryRange; bucket_minutes: number; collecting_since: string | null; points: MetricPoint[] };

function useJson<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setFailed(false);
    browserApiFetch<T>(path, { signal: controller.signal })
      .then(setData)
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [path]);
  return { data, failed };
}

export function AdminSystemHistory() {
  const t = useTranslations("admin.systemHistory");
  const [range, setRange] = useState<HistoryRange>("24h");
  const { data, failed } = useJson<SystemHistory>(`/api/admin/system-status/history?range=${range}`);
  const postgres: MetricDef[] = [
    { key: "postgres.latency_ms.avg", label: t("metrics.postgresLatencyAvg"), kind: "line", color: CHART_COLORS.analyticsLoad, format: "ms" },
    { key: "postgres.latency_ms.max", label: t("metrics.postgresLatencyMax"), kind: "line", color: CHART_COLORS.analyticsErrors, format: "ms" },
    { key: "postgres.connections.max", label: t("metrics.postgresConnections"), kind: "bar", color: CHART_COLORS.analyticsTenants, format: "count" },
  ];
  const sizes: MetricDef[] = [
    { key: "postgres.size_mb.max", label: t("metrics.postgresSize"), kind: "line", color: CHART_COLORS.analyticsStorage, format: "mb" },
    { key: "redis.used_mb.max", label: t("metrics.redisUsed"), kind: "line", color: CHART_COLORS.analyticsUsers, format: "mb" },
  ];
  const redis: MetricDef[] = [
    { key: "redis.latency_ms.avg", label: t("metrics.redisLatencyAvg"), kind: "line", color: CHART_COLORS.analyticsNew, format: "ms" },
    { key: "redis.latency_ms.max", label: t("metrics.redisLatencyMax"), kind: "line", color: CHART_COLORS.analyticsErrors, format: "ms" },
  ];
  return (
    <section className="card section-stack" aria-labelledby="admin-system-history-title">
      <div className="page-header">
        <div>
          <h2 id="admin-system-history-title" className="section-title">{t("title")}</h2>
          <p className="muted">
            {data?.collecting_since ? t("description", { date: formatDate(data.collecting_since) }) : t("descriptionEmpty")}
          </p>
        </div>
        <FilterTabs<HistoryRange> options={HISTORY_RANGES.map((value) => ({ value, label: t(`range.${value}`) }))} value={range} onChange={setRange} />
      </div>
      {failed ? <StatusBanner tone="error" message={t("loadFailed")} /> : null}
      {data ? (
        <div className="grid">
          <h3 className="admin-analytics-heading">{t("postgresTitle")}</h3>
          <MetricHistory points={data.points} defs={postgres} bucketLabel={t("bucket")} />
          <h3 className="admin-analytics-heading">{t("redisTitle")}</h3>
          <MetricHistory points={data.points} defs={redis} bucketLabel={t("bucket")} />
          <h3 className="admin-analytics-heading">{t("sizeTitle")}</h3>
          <MetricHistory points={data.points} defs={sizes} bucketLabel={t("bucket")} />
        </div>
      ) : failed ? null : (
        <p className="muted">{t("loading")}</p>
      )}
    </section>
  );
}

type StorageSeries = {
  collecting_since: string | null;
  points: MetricPoint[];
  top_tenants?: { tenant_id: string; name: string; bytes: number }[];
};

export function AdminStorageOccupancy() {
  const t = useTranslations("admin.storageOccupancy");
  const formatValue = useMetricFormatter();
  const { data, failed } = useJson<StorageSeries>("/api/admin/analytics/storage?range=90d");
  const defs: MetricDef[] = [{ key: "storage.bytes_total", label: t("total"), kind: "line", color: CHART_COLORS.analyticsStorage, format: "bytes" }];
  return (
    <section className="card section-stack" aria-labelledby="admin-storage-occupancy-title">
      <div>
        <h2 id="admin-storage-occupancy-title" className="section-title">{t("title")}</h2>
        <p className="muted">{data?.collecting_since ? t("description", { date: formatDate(data.collecting_since) }) : t("descriptionEmpty")}</p>
      </div>
      {failed ? <StatusBanner tone="error" message={t("loadFailed")} /> : null}
      {data ? (
        <>
          <MetricHistory points={data.points} defs={defs} bucketLabel={t("day")} />
          <h3 className="admin-analytics-heading">{t("topTitle")}</h3>
          <DataTable columns={[t("tenant"), t("storage")]} emptyMessage={t("empty")}>
            {(data.top_tenants ?? []).map((item) => (
              <tr key={item.tenant_id}>
                <td>
                  <Link href={`/admin/tenants/${item.tenant_id}/storage` as Route}>{item.name}</Link>
                </td>
                <td>{formatValue("bytes", item.bytes)}</td>
              </tr>
            ))}
          </DataTable>
        </>
      ) : null}
    </section>
  );
}
