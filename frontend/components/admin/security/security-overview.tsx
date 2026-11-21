"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import type { Route } from "next";
import { useId, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { StatusBanner } from "@/components/ui/status-banner";
import { SecurityAlertList } from "@/components/admin/security/security-alerts";
import { useAdminResource } from "@/components/admin/security/use-admin-resource";
import { formatDateTime, formatTime } from "@/lib/utils/format";
import type { AuthAlert, AuthSecurityOverview, AuthSecuritySummary } from "@/types/admin-security";

// recharts erst im Browser nachladen (Admin-Bundle bleibt klein)
const SecurityTimeseriesChart = dynamic(
  () => import("@/components/admin/security/security-timeseries-chart").then((m) => m.SecurityTimeseriesChart),
  { ssr: false }
);

function SecurityTile({ label, value, hint, tone, href }: { label: string; value: number; hint?: string; tone?: "danger" | "warning"; href?: string }) {
  const body = (
    <>
      <span className="admin-security-tile-label">{label}</span>
      <strong className="admin-security-tile-value">{value.toLocaleString()}</strong>
      {hint ? <span className="admin-security-tile-hint">{hint}</span> : null}
    </>
  );
  const className = `card admin-security-tile${tone ? ` admin-security-tile-${tone}` : ""}`;
  return href ? (
    <Link href={href as Route} className={`${className} admin-security-tile-link`}>{body}</Link>
  ) : (
    <div className={className}>{body}</div>
  );
}

/** /admin/security: Kacheln, Zeitreihe (Diagramm oder Tabelle), auffällige Netze/Konten, Warnungen. */
export function SecurityOverview() {
  const t = useTranslations("adminSecurity");
  const locale = useLocale();
  const summaryId = useId();
  const overview = useAdminResource<AuthSecurityOverview>("/api/admin/auth-security/overview");
  const summary = useAdminResource<AuthSecuritySummary>("/api/admin/auth-security/summary");
  const alerts = useAdminResource<AuthAlert[]>("/api/admin/auth-security/alerts");
  const [asTable, setAsTable] = useState(false);

  const points = useMemo(
    () => (summary.data?.timeseries ?? []).map((point) => ({
      label: formatTime(point.bucket, locale),
      failures: Number(point.failures),
      successes: Number(point.successes),
      blocked: Number(point.blocked),
    })),
    [summary.data, locale]
  );
  const totals = points.reduce((acc, point) => ({ failures: acc.failures + point.failures, successes: acc.successes + point.successes }), { failures: 0, successes: 0 });

  if (overview.forbidden) {
    return <StatusBanner tone="neutral" message={t("ownerOnly")} />;
  }

  return (
    <div className="section-stack">
      {overview.failed || summary.failed ? <StatusBanner tone="error" message={t("loadFailed")} /> : null}
      {overview.data ? (
        <div className="admin-security-tiles">
          <SecurityTile
            label={t("overview.tiles.openAlerts")}
            value={overview.data.open_alerts}
            hint={t("overview.tiles.criticalAlerts", { count: overview.data.critical_alerts })}
            tone={overview.data.critical_alerts > 0 ? "danger" : overview.data.open_alerts > 0 ? "warning" : undefined}
            href="/admin/security/alerts"
          />
          <SecurityTile
            label={t("overview.tiles.failures")}
            value={overview.data.failures_24h}
            hint={t("overview.tiles.previous", { count: overview.data.failures_prev_24h })}
            href="/admin/security/events?outcome=failure"
          />
          <SecurityTile
            label={t("overview.tiles.activeBlocks")}
            value={overview.data.active_blocks}
            hint={t("overview.tiles.blocked", { count: overview.data.blocked_24h })}
            href="/admin/security/blocks"
          />
          <SecurityTile label={t("overview.tiles.adminLogins")} value={overview.data.admin_logins_24h} />
        </div>
      ) : null}

      <section className="card section-stack">
        <DataToolbar
          title={t("overview.chartTitle")}
          actions={
            <button type="button" className="button-secondary button-ghost" aria-pressed={asTable} onClick={() => setAsTable((value) => !value)}>
              {asTable ? t("overview.showChart") : t("overview.showTable")}
            </button>
          }
        />
        <p className="muted" id={summaryId}>{t("overview.chartSummary", totals)}</p>
        {points.length === 0 ? (
          <p className="muted">{summary.loading ? null : t("overview.chartEmpty")}</p>
        ) : asTable ? (
          <DataTable columns={[t("overview.columns.bucket"), t("overview.columns.failures"), t("overview.columns.blocked"), t("overview.columns.successes")]}>
            {(summary.data?.timeseries ?? []).map((point) => (
              <tr key={point.bucket}>
                <td>{formatDateTime(point.bucket, locale)}</td>
                <td>{point.failures}</td>
                <td>{point.blocked}</td>
                <td>{point.successes}</td>
              </tr>
            ))}
          </DataTable>
        ) : (
          <div className="admin-security-chart" role="img" aria-describedby={summaryId}>
            <SecurityTimeseriesChart data={points} />
          </div>
        )}
      </section>

      <section className="card section-stack">
        <DataToolbar
          title={t("overview.alertsTitle")}
          actions={<Link href={"/admin/security/alerts" as Route} className="button-secondary button-ghost">{t("overview.allAlerts")}</Link>}
        />
        <SecurityAlertList alerts={alerts.data ?? []} loading={alerts.loading} />
      </section>

      <div className="admin-security-columns">
        <section className="card section-stack">
          <DataToolbar title={t("overview.topNetworks")} />
          <DataTable
            columns={[t("overview.columns.network"), t("overview.columns.failures"), t("overview.columns.accounts"), t("overview.columns.tenants"), t("overview.columns.lastSeen")]}
            emptyMessage={t("overview.noTopNetworks")}
          >
            {(summary.data?.top_networks ?? []).map((row) => (
              <tr key={row.src_net_hash ?? "none"}>
                <td><code>{row.src_net_hash}</code></td>
                <td>{row.failures}</td>
                <td>{row.accounts}</td>
                <td>{row.tenants}</td>
                <td>{formatDateTime(row.last_seen, locale)}</td>
              </tr>
            ))}
          </DataTable>
        </section>
        <section className="card section-stack">
          <DataToolbar title={t("overview.topAccounts")} />
          <DataTable
            columns={[t("overview.columns.account"), t("overview.columns.failures"), t("overview.columns.networks"), t("overview.columns.lastSeen")]}
            emptyMessage={t("overview.noTopAccounts")}
          >
            {(summary.data?.top_accounts ?? []).map((row) => (
              <tr key={row.subject_hash ?? "none"}>
                <td>
                  <code>{row.subject_hash}</code>
                  {row.tenant_id ? (
                    <> <Link href={`/admin/tenants/${row.tenant_id}` as Route} className="admin-security-inline-link"><Badge variant="neutral">#{row.tenant_id}</Badge></Link></>
                  ) : null}
                </td>
                <td>{row.failures}</td>
                <td>{row.networks}</td>
                <td>{formatDateTime(row.last_seen, locale)}</td>
              </tr>
            ))}
          </DataTable>
        </section>
      </div>
      <p>
        <Link href={"/admin/security/audit" as Route}>{t("overview.auditLink")}</Link>
      </p>
    </div>
  );
}
