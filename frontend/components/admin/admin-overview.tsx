"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import type { Route } from "next";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { FilterTabs } from "@/components/ui/filter-tabs";
import { HealthBadge } from "@/components/ui/health-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { StatTile, type StatTileDelta } from "@/components/ui/stat-tile";
import { StatusBanner } from "@/components/ui/status-banner";
import { TimeRangeTabs } from "@/components/ui/time-range-tabs";
import { announce } from "@/lib/a11y/announce";
import { derivePlatformStatus, percentDelta, problemHref } from "@/lib/admin/platform-status";
import { browserApiFetch } from "@/lib/api/client";
import { describeAuditAction } from "@/lib/audit-labels";
import { useVisibleInterval } from "@/lib/hooks/use-visible-interval";
import { formatDateTime, formatRappen } from "@/lib/utils/format";
import type { AdminOverview as Overview, OverviewFeedItem, OverviewRange, OverviewSeries } from "@/types/admin-overview";

import type { OverviewChartRow } from "@/components/admin/admin-overview-chart";

// recharts erst im Browser nachladen (Admin-Bundle klein halten, Plan §9 Performance)
const OverviewBarChart = dynamic(() => import("@/components/admin/admin-overview-chart").then((m) => m.OverviewBarChart), {
  ssr: false,
  loading: () => <Skeleton variant="block" />,
});

const RANGES = ["24h", "7d", "30d", "90d"] as const;
const REFRESH_MS = 60_000;

type FeedFilter = "all" | "admin" | "system";

function deltaOf(current: number, previous: number | null | undefined, higherIsGood: boolean, text: (percent: number) => string): StatTileDelta | null {
  const percent = percentDelta(current, previous);
  if (percent === null) return null;
  const direction = percent > 0 ? "up" : percent < 0 ? "down" : "flat"; // i18n-ok: Vergleich, kein UI-Text
  const tone = direction === "flat" ? "neutral" : (direction === "up") === higherIsGood ? "good" : "bad";
  return { text: text(percent), direction, tone };
}

function bucketLabel(bucket: string, bucketHours: number, locale: string): string {
  const date = new Date(bucket);
  if (bucketHours >= 24) return date.toLocaleDateString(locale, { day: "2-digit", month: "2-digit" });
  return date.toLocaleString(locale, bucketHours >= 6 ? { day: "2-digit", month: "2-digit", hour: "2-digit" } : { hour: "2-digit", minute: "2-digit" });
}

function SeriesPanel({ kind, range }: { kind: "logins" | "errors"; range: OverviewRange }) {
  const t = useTranslations("adminOverview");
  const locale = useLocale();
  const summaryId = useId();
  const [series, setSeries] = useState<OverviewSeries | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setFailed(false);
    browserApiFetch<OverviewSeries>(`/api/admin/overview/series?kind=${kind}&range=${range}`)
      .then((result) => {
        if (!cancelled) setSeries(result);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [kind, range]);

  const rows: OverviewChartRow[] = (series?.points ?? []).map((point) => ({
    label: bucketLabel(point.bucket, series?.bucket_hours ?? 1, locale),
    success: point.success,
    failure: point.failure,
    errors: point.errors,
  }));
  const totals = rows.reduce(
    (acc, row) => ({ success: acc.success + (row.success ?? 0), failure: acc.failure + (row.failure ?? 0), errors: acc.errors + (row.errors ?? 0) }),
    { success: 0, failure: 0, errors: 0 },
  );
  const chartSeries =
    kind === "logins"
      ? [
          { key: "success" as const, name: t("charts.success") },
          { key: "failure" as const, name: t("charts.failure") },
        ]
      : [{ key: "errors" as const, name: t("charts.errors") }];

  return (
    <section className="panel admin-overview-chart" aria-busy={series === null && !failed}>
      <h2 className="admin-overview-section-title">{t(`charts.${kind}Title`)}</h2>
      <p id={summaryId} className="muted admin-overview-chart-summary">
        {kind === "logins"
          ? t("charts.loginsSummary", { success: totals.success, failure: totals.failure, range: t(`ranges.${range}`) })
          : t("charts.errorsSummary", { count: totals.errors, range: t(`ranges.${range}`) })}
      </p>
      {failed ? (
        <StatusBanner tone="error" message={t("charts.loadFailed")} />
      ) : series === null ? (
        <Skeleton variant="block" />
      ) : (
        <>
          <OverviewBarChart rows={rows} series={chartSeries} describedBy={summaryId} />
          {kind === "errors" && series.top_types.length > 0 ? (
            <ul className="admin-overview-top-types">
              {series.top_types.map((entry) => (
                <li key={entry.error_type}>
                  <code>{entry.error_type}</code> <span className="muted">{entry.count}</span>
                </li>
              ))}
            </ul>
          ) : null}
          <details className="admin-overview-table-alt">
            <summary>{t("charts.asTable")}</summary>
            <div className="table-shell">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">{t("charts.time")}</th>
                    {chartSeries.map((entry) => (
                      <th scope="col" key={entry.key}>
                        {entry.name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, index) => (
                    <tr key={`${row.label}-${index}`}>
                      <td>{row.label}</td>
                      {chartSeries.map((entry) => (
                        <td key={entry.key}>{row[entry.key] ?? 0}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </section>
  );
}

function FeedRow({ item }: { item: OverviewFeedItem }) {
  const t = useTranslations("adminOverview");
  const tActions = useTranslations("common.auditActions");
  const locale = useLocale();
  const label =
    item.kind === "admin"
      ? describeAuditAction(item.action, tActions)
      : t(`feed.systemKinds.${item.action === "resolved" ? "resolved" : item.action === "container_restart" ? "container_restart" : "problem"}`, { subject: item.subject ?? "" });
  const meta = [item.tenant, item.actor].filter(Boolean).join(" · ");
  return (
    <li className="admin-overview-feed-item">
      <time className="admin-overview-feed-time" dateTime={item.at}>
        {formatDateTime(item.at, locale)}
      </time>
      <Link href={item.href as Route} className="admin-overview-feed-link">
        <span className="admin-overview-feed-label">{label}</span>
        {meta ? <span className="muted admin-overview-feed-meta">{meta}</span> : null}
      </Link>
      {item.severity === "critical" || item.severity === "warning" || item.outcome === "failure" ? (
        <HealthBadge state={item.severity === "critical" ? "critical" : "warning"} />
      ) : null}
    </li>
  );
}

export function AdminOverview({ initial }: { initial: Overview | null }) {
  const t = useTranslations("adminOverview");
  const locale = useLocale();
  const [data, setData] = useState<Overview | null>(initial);
  const [loadFailed, setLoadFailed] = useState(initial === null);
  const [paused, setPaused] = useState(false);
  const [range, setRange] = useState<OverviewRange>("24h");
  const [feedFilter, setFeedFilter] = useState<FeedFilter>("all");
  const lastStatus = useRef<string | null>(null);

  const refresh = useCallback(() => {
    browserApiFetch<Overview>("/api/admin/overview")
      .then((next) => {
        setData(next);
        setLoadFailed(false);
      })
      .catch(() => setLoadFailed(true));
  }, []);
  useVisibleInterval(refresh, paused ? null : REFRESH_MS);

  const isOwner = data?.role === "owner";
  const platform = derivePlatformStatus(data?.status ?? null);

  // Statuswechsel einmal ansagen (nicht bei jedem Polling-Tick, WCAG 4.1.3)
  useEffect(() => {
    if (!isOwner) return;
    if (lastStatus.current !== null && lastStatus.current !== platform.status) {
      announce(t("status.changed", { status: t(`status.states.${platform.status}`) }));
    }
    lastStatus.current = platform.status;
  }, [isOwner, platform.status, t]);

  if (!data) {
    return (
      <div className="grid">
        <div className="page-header">
          <h1 className="page-title">{t("title")}</h1>
        </div>
        <StatusBanner tone="error" message={t("loadFailed")} />
      </div>
    );
  }

  const kpis = data.kpis;
  const noPermission = t("noPermission");
  const percentText = (key: string) => (percent: number) => t(key, { percent: `${percent > 0 ? "+" : ""}${percent}` }); // i18n-ok: Vorzeichen der Zahl
  const feedItems = (data.feed ?? []).filter((item) => feedFilter === "all" || item.kind === feedFilter);

  return (
    <div className="grid admin-overview">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("title")}</h1>
          <p className="muted">{t("subtitle")}</p>
        </div>
        <div className="admin-overview-header-actions">
          <button type="button" className="button-secondary" aria-pressed={paused} onClick={() => setPaused((current) => !current)}>
            {paused ? t("refresh.resume") : t("refresh.pause")}
          </button>
        </div>
      </div>

      {loadFailed ? <StatusBanner tone="error" message={t("refreshFailed")} /> : null}

      {isOwner && data.status ? (
        <section className={`admin-overview-status admin-overview-status-${platform.status}`} aria-labelledby="admin-overview-status-title">
          <div className="admin-overview-status-head">
            <h2 id="admin-overview-status-title" className="admin-overview-status-title">
              {t("status.platform")}
            </h2>
            <HealthBadge state={platform.status} label={t(`status.states.${platform.status}`)} />
            <span className="muted">{t(`status.rules.${platform.rule}`)}</span>
            {data.status.snapshot_at ? (
              <span className="muted admin-overview-status-time">{t("status.asOf", { time: formatDateTime(data.status.snapshot_at, locale) })}</span>
            ) : null}
          </div>
          {platform.problems.length > 0 ? (
            <ul className="admin-overview-problems">
              {platform.problems.map((problem) => (
                <li key={problem.key}>
                  <Link href={problemHref(problem) as Route}>
                    <code>{problem.key}</code>
                  </Link>{" "}
                  <span className="muted">{problem.reason}</span>
                </li>
              ))}
            </ul>
          ) : null}
          {data.status.maintenance_active ? (
            <p className="admin-overview-maintenance">
              <Link href="/admin/maintenance">{t("status.maintenanceActive")}</Link>
            </p>
          ) : null}
        </section>
      ) : null}

      <section className="admin-overview-kpis" aria-label={t("kpis.title")}>
        <StatTile
          label={t("kpis.platform")}
          href={isOwner ? "/admin/system" : undefined}
          unavailable={isOwner ? undefined : noPermission}
          value={t(`status.states.${platform.status}`)}
          hint={isOwner && data.status ? t("kpis.platformHint", { critical: data.status.critical, warning: data.status.warning }) : undefined}
        />
        <StatTile
          label={t("kpis.tenants")}
          href="/admin/tenants"
          value={kpis.tenants.value.toLocaleString(locale)}
          hint={t("kpis.tenantsNew", { count: kpis.tenants.new_30d })}
        />
        <StatTile
          label={t("kpis.activeUsers")}
          value={kpis.active_users_30d.value.toLocaleString(locale)}
          delta={deltaOf(kpis.active_users_30d.value, kpis.active_users_30d.previous, true, percentText("kpis.vsPrevious30d"))}
          hint={t("kpis.activeUsersHint")}
        />
        <StatTile
          label={t("kpis.mrr")}
          href="/admin/cashflow"
          value={formatRappen(kpis.mrr.value_rp, locale)}
          delta={deltaOf(kpis.mrr.value_rp, kpis.mrr.previous_month_income_rp, true, percentText("kpis.vsPreviousMonth"))}
          hint={t("kpis.payingTenants", { count: kpis.mrr.paying_tenants })}
          status={kpis.mrr.overdue_count > 0 ? "warning" : undefined}
          statusLabel={kpis.mrr.overdue_count > 0 ? t("kpis.overdue", { count: kpis.mrr.overdue_count }) : undefined}
        />
        <StatTile
          label={t("kpis.errors")}
          href={kpis.errors_24h ? "/admin/error-logs" : undefined}
          unavailable={kpis.errors_24h ? undefined : noPermission}
          value={kpis.errors_24h?.value.toLocaleString(locale)}
          delta={kpis.errors_24h ? deltaOf(kpis.errors_24h.value, kpis.errors_24h.previous, false, percentText("kpis.vsPrevious24h")) : null}
        />
        <StatTile
          label={t("kpis.loginFailures")}
          href={kpis.login_failures_24h ? "/admin/security" : undefined}
          unavailable={kpis.login_failures_24h ? undefined : noPermission}
          value={kpis.login_failures_24h?.value.toLocaleString(locale)}
          delta={kpis.login_failures_24h ? deltaOf(kpis.login_failures_24h.value, kpis.login_failures_24h.previous, false, percentText("kpis.vsPrevious24h")) : null}
        />
      </section>

      <section className="panel admin-overview-todos" aria-labelledby="admin-overview-todos-title">
        <h2 id="admin-overview-todos-title" className="admin-overview-section-title">
          {t("todos.title")}
        </h2>
        {data.todos.length === 0 ? (
          <p className="muted">{t("todos.empty")}</p>
        ) : (
          <ul className="admin-overview-todo-list">
            {data.todos.map((todo) => (
              <li key={todo.key}>
                <Link href={todo.href as Route} className="admin-overview-todo-link">
                  <HealthBadge state={todo.severity === "info" ? "degraded" : todo.severity} label={String(todo.count)} />
                  <span>{t(`todos.items.${todo.key}`, { count: todo.count })}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      {isOwner ? (
        <>
          <div className="admin-overview-range">
            <span className="muted">{t("charts.range")}</span>
            <TimeRangeTabs value={range} onChange={setRange} ranges={RANGES} />
          </div>
          <div className="admin-overview-charts">
            <SeriesPanel kind="logins" range={range} />
            <SeriesPanel kind="errors" range={range} />
          </div>
        </>
      ) : null}

      {data.feed !== null ? (
        <section className="panel admin-overview-feed" aria-labelledby="admin-overview-feed-title">
          <div className="admin-overview-feed-head">
            <h2 id="admin-overview-feed-title" className="admin-overview-section-title">
              {t("feed.title")}
            </h2>
            <FilterTabs<FeedFilter>
              value={feedFilter}
              onChange={setFeedFilter}
              options={[
                { value: "all", label: t("feed.filters.all") },
                { value: "admin", label: t("feed.filters.admin") },
                { value: "system", label: t("feed.filters.system") },
              ]}
            />
          </div>
          {feedItems.length === 0 ? (
            <p className="muted">{t("feed.empty")}</p>
          ) : (
            <ul className="admin-overview-feed-list">
              {feedItems.map((item) => (
                <FeedRow key={item.id} item={item} />
              ))}
            </ul>
          )}
        </section>
      ) : null}
    </div>
  );
}
