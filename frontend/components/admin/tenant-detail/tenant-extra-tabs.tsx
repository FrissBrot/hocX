"use client";

import Link from "next/link";
import type { Route } from "next";
import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { MetricHistory, type MetricDef, type MetricPoint } from "@/components/admin/metric-history";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { StatTile } from "@/components/ui/stat-tile";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { CHART_COLORS } from "@/lib/constants/chart-colors";
import { formatDate, formatDateTime } from "@/lib/utils/format";

// Mandanten-Detail-Tabs Features, Nutzung, Sicherheit (1.5.1, Plan §5.2).

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

type TenantFeatureRow = { code: string; name: string; access: "full" | "read_only" | "none"; source: "plan" | "addon" | null; enabled_at: string | null };

const ACCESS_VARIANT = { full: "success", read_only: "warning", none: "neutral" } as const;

export function TenantFeaturesTab({ tenantId, readOnly }: { tenantId: string; readOnly: boolean }) {
  const t = useTranslations("adminTenantDetail.features");
  const tFeatures = useTranslations("common.features");
  const { data, failed } = useJson<TenantFeatureRow[]>(`/api/admin/tenants/${tenantId}/features`);
  const booked = (data ?? []).filter((row) => row.access !== "none").length;
  return (
    <section className="card section-stack">
      <div className="page-header">
        <div>
          <h2 className="section-title">{t("title")}</h2>
          <p className="muted">{data ? t("summary", { booked, total: data.length }) : t("description")}</p>
        </div>
        {!readOnly ? (
          <Link href={`/admin/tenants/${tenantId}/subscription` as Route} className="button-secondary">
            {t("edit")}
          </Link>
        ) : null}
      </div>
      {failed ? <StatusBanner tone="error" message={t("loadFailed")} /> : null}
      <DataTable columns={[t("columns.feature"), t("columns.access"), t("columns.source"), t("columns.since")]} emptyMessage={data ? t("empty") : undefined}>
        {(data ?? []).map((row) => (
          <tr key={row.code}>
            <td>
              <strong>{tFeatures.has(row.code) ? tFeatures(row.code) : row.name}</strong>
              <div className="muted admin-cell-sub"><code>{row.code}</code></div>
            </td>
            <td><Badge variant={ACCESS_VARIANT[row.access] ?? "neutral"} dot>{t(`access.${row.access}`)}</Badge></td>
            <td>{row.source ? t(`source.${row.source === "plan" ? "plan" : "addon"}`) : <span className="muted">—</span>}</td>
            <td>{row.enabled_at ? formatDate(row.enabled_at) : <span className="muted">—</span>}</td>
          </tr>
        ))}
      </DataTable>
    </section>
  );
}

const USAGE_RANGES = ["30d", "90d", "12m"] as const;
type UsageRange = (typeof USAGE_RANGES)[number];
type TenantUsage = { range: UsageRange; bucket: "day" | "month"; collecting_since: string | null; totals: Record<string, number>; points: MetricPoint[] };

export function TenantUsageTab({ tenantId }: { tenantId: string }) {
  const t = useTranslations("adminTenantDetail.usage");
  const [range, setRange] = useState<UsageRange>("30d");
  const { data, failed } = useJson<TenantUsage>(`/api/admin/tenants/${tenantId}/usage?range=${range}`);
  const activity: MetricDef[] = [
    { key: "logins", label: t("metrics.logins"), kind: "bar", color: CHART_COLORS.analyticsLoginSuccess, format: "count" },
    { key: "users.active", label: t("metrics.activeUsers"), kind: "line", color: CHART_COLORS.analyticsUsers, format: "count" },
  ];
  const modules: MetricDef[] = [
    { key: "usage.protocols", label: t("metrics.protocols"), kind: "bar", color: CHART_COLORS.analyticsTenants, format: "count" },
    { key: "usage.events", label: t("metrics.events"), kind: "bar", color: CHART_COLORS.analyticsNew, format: "count" },
    { key: "usage.files", label: t("metrics.files"), kind: "bar", color: CHART_COLORS.analyticsStorage, format: "count" },
  ];
  const storage: MetricDef[] = [{ key: "storage.bytes", label: t("metrics.storage"), kind: "line", color: CHART_COLORS.analyticsStorage, format: "bytes" }];
  const totals = data?.totals ?? {};
  return (
    <section className="card section-stack">
      <div className="page-header">
        <div>
          <h2 className="section-title">{t("title")}</h2>
          <p className="muted">{data?.collecting_since ? t("description", { date: formatDate(data.collecting_since) }) : t("descriptionEmpty")}</p>
        </div>
        <FilterTabs<UsageRange> options={USAGE_RANGES.map((value) => ({ value, label: t(`range.${value}`) }))} value={range} onChange={setRange} />
      </div>
      {failed ? <StatusBanner tone="error" message={t("loadFailed")} /> : null}
      {data ? (
        <>
          <div className="admin-security-tiles">
            <StatTile label={t("metrics.logins")} value={totals.logins ?? 0} />
            <StatTile label={t("metrics.protocols")} value={totals["usage.protocols"] ?? 0} />
            <StatTile label={t("metrics.events")} value={totals["usage.events"] ?? 0} />
            <StatTile label={t("metrics.files")} value={totals["usage.files"] ?? 0} />
          </div>
          <h3 className="admin-analytics-heading">{t("activityTitle")}</h3>
          <MetricHistory points={data.points} defs={activity} bucketLabel={t(data.bucket === "month" ? "month" : "day")} />
          <h3 className="admin-analytics-heading">{t("modulesTitle")}</h3>
          <MetricHistory points={data.points} defs={modules} bucketLabel={t(data.bucket === "month" ? "month" : "day")} />
          <h3 className="admin-analytics-heading">{t("storageTitle")}</h3>
          <MetricHistory points={data.points} defs={storage} bucketLabel={t(data.bucket === "month" ? "month" : "day")} />
        </>
      ) : null}
    </section>
  );
}

type TenantSecurity = {
  summary: { failures_24h: number; accounts_with_failures_24h: number; new_device_logins_7d: number; blocked_24h: number };
  warnings: { kind: string; user_id: string; display_name: string; count: number; last_at: string }[];
  events: { ts: string; event_type: string; outcome: string; user_id: string | null; display_name: string | null; user_agent_family: string | null; risk_level: string | null }[];
};

const WARNING_KINDS = new Set(["account_attack", "privileged_new_device", "mfa_removed", "account_locked"]);
const OUTCOME_VARIANT: Record<string, "success" | "danger" | "warning" | "info" | "neutral"> = {
  success: "success", failure: "danger", blocked: "warning", challenged: "info", info: "neutral",
};

export function TenantSecurityTab({ tenantId }: { tenantId: string }) {
  const t = useTranslations("adminTenantDetail.security");
  const tSec = useTranslations("adminSecurity");
  const locale = useLocale();
  const { data, failed } = useJson<TenantSecurity>(`/api/admin/tenants/${tenantId}/security`);
  return (
    <section className="card section-stack">
      <div>
        <h2 className="section-title">{t("title")}</h2>
        <p className="muted">{t("description")}</p>
      </div>
      {failed ? <StatusBanner tone="error" message={t("loadFailed")} /> : null}
      {data ? (
        <>
          <div className="admin-security-tiles">
            <StatTile label={t("tiles.failures")} value={data.summary.failures_24h} />
            <StatTile label={t("tiles.accounts")} value={data.summary.accounts_with_failures_24h} />
            <StatTile label={t("tiles.blocked")} value={data.summary.blocked_24h} />
            <StatTile label={t("tiles.newDevices")} value={data.summary.new_device_logins_7d} />
          </div>
          <h3 className="admin-analytics-heading">{t("warningsTitle")}</h3>
          <DataTable columns={[t("columns.warning"), t("columns.account"), t("columns.count"), t("columns.last")]} emptyMessage={t("noWarnings")}>
            {data.warnings.map((warning) => (
              <tr key={`${warning.kind}-${warning.user_id}`}>
                <td><Badge variant="warning" dot>{WARNING_KINDS.has(warning.kind) ? t(`warnings.${warning.kind}`) : warning.kind}</Badge></td>
                <td>{warning.display_name}</td>
                <td className="admin-cell-number">{warning.count}</td>
                <td>{formatDateTime(warning.last_at, locale)}</td>
              </tr>
            ))}
          </DataTable>
          <h3 className="admin-analytics-heading">{t("eventsTitle")}</h3>
          <DataTable columns={[t("columns.time"), t("columns.type"), t("columns.outcome"), t("columns.account"), t("columns.client")]} emptyMessage={t("noEvents")}>
            {data.events.map((event, index) => (
              <tr key={`${event.ts}-${index}`}>
                <td>{formatDateTime(event.ts, locale)}</td>
                <td><code>{event.event_type}</code></td>
                <td><Badge variant={OUTCOME_VARIANT[event.outcome] ?? "neutral"} dot>{tSec.has(`outcomes.${event.outcome}`) ? tSec(`outcomes.${event.outcome}`) : event.outcome}</Badge></td>
                <td>{event.display_name ?? <span className="muted">—</span>}</td>
                <td>{event.user_agent_family ?? <span className="muted">—</span>}</td>
              </tr>
            ))}
          </DataTable>
        </>
      ) : null}
    </section>
  );
}
