"use client";

import Link from "next/link";
import type { Route } from "next";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { StatusBanner } from "@/components/ui/status-banner";
import { useAdminResource } from "@/components/admin/security/use-admin-resource";
import { incidentLabel, statusVariant } from "@/lib/admin/security-incidents";
import { formatDateTime } from "@/lib/utils/format";
import type { AuthAlert } from "@/types/admin-security";

const KNOWN_RULES = new Set(["stuffing", "spraying", "account_attack", "admin_mfa", "admin_new_device", "blocks", "network", "cross_tenant", "tenant", "limiter"]);

/** Tabelle der ausgelösten Alarmregeln. Titel kommen aus den Übersetzungen (je Regel), der
 * Schlüssel `auth:<regel>[:<pseudonym>]` entspricht dem Problemschlüssel im Systemmonitor. Ab 1.7
 * zeigt jede Warnung ihren Vorfall (Status und Zuständig dort, statt der Quittung aus 1.5.1). */
export function SecurityAlertList({ alerts, loading }: { alerts: AuthAlert[]; loading?: boolean }) {
  const t = useTranslations("adminSecurity");
  const locale = useLocale();
  const columns = [t("alerts.columns.severity"), t("alerts.columns.rule"), t("alerts.columns.subject"), t("alerts.columns.incident"), t("alerts.columns.key")];
  return (
    <DataTable columns={columns} emptyMessage={loading ? undefined : t("alerts.empty")}>
      {alerts.map((alert) => (
        <tr key={alert.key}>
          <td>
            <Badge variant={alert.severity === "critical" ? "danger" : "warning"} dot>
              {t(`severity.${alert.severity}`)}
            </Badge>
          </td>
          <td>{t(`alerts.rules.${KNOWN_RULES.has(alert.rule) ? alert.rule : "unknown"}`)}</td>
          <td>
            {alert.subject_label ? (
              <>
                <span>{alert.subject_label}</span>
                <div className="muted admin-cell-sub"><code>{alert.subject}</code></div>
              </>
            ) : alert.subject ? (
              <code>{alert.subject}</code>
            ) : null}
          </td>
          <td>
            {alert.incident ? (
              <>
                <Link href={`/admin/security/incidents?incident=${alert.incident.id}` as Route} className="admin-security-inline-link">
                  {incidentLabel(alert.incident.id)}
                </Link>{" "}
                <Badge variant={statusVariant(alert.incident.status)} dot>{t(`statuses.${alert.incident.status}`)}</Badge>
                {alert.incident.assignee ? <div className="muted admin-cell-sub">{t("alerts.assignee", { name: alert.incident.assignee })}</div> : null}
              </>
            ) : (
              <span className="muted">{t("alerts.noIncident")}</span>
            )}
            {alert.clears_at && alert.window_minutes ? (
              <div className="muted admin-cell-sub">
                {t("alerts.clearsAt", { time: formatDateTime(alert.clears_at, locale), minutes: alert.window_minutes })}
              </div>
            ) : null}
          </td>
          <td><code>{alert.key}</code></td>
        </tr>
      ))}
    </DataTable>
  );
}

export function SecurityAlertsView() {
  const t = useTranslations("adminSecurity");
  const alerts = useAdminResource<AuthAlert[]>("/api/admin/auth-security/alerts");
  if (alerts.forbidden) return <StatusBanner tone="neutral" message={t("ownerOnly")} />;
  return (
    <section className="card section-stack" aria-labelledby="security-open-alerts">
      <h2 id="security-open-alerts" className="section-title">{t("alerts.openTitle")}</h2>
      {alerts.failed ? <StatusBanner tone="error" message={t("loadFailed")} /> : null}
      <p className="muted">{t("alerts.incidentHelp")}</p>
      <div className="admin-security-toolbar">
        <button type="button" className="button-secondary" onClick={alerts.reload}>{t("refresh")}</button>
      </div>
      <SecurityAlertList alerts={alerts.data ?? []} loading={alerts.loading} />
    </section>
  );
}
