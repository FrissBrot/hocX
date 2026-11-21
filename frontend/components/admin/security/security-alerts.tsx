"use client";

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { StatusBanner } from "@/components/ui/status-banner";
import { useAdminResource } from "@/components/admin/security/use-admin-resource";
import type { AuthAlert } from "@/types/admin-security";

const KNOWN_RULES = new Set(["stuffing", "spraying", "account_attack", "admin_mfa", "admin_new_device", "blocks", "network", "cross_tenant", "tenant", "limiter"]);

/** Tabelle der ausgelösten Alarmregeln. Titel kommen aus den Übersetzungen (je Regel), der
 * Schlüssel `auth:<regel>[:<pseudonym>]` entspricht dem Problemschlüssel im Systemmonitor. */
export function SecurityAlertList({ alerts, loading }: { alerts: AuthAlert[]; loading?: boolean }) {
  const t = useTranslations("adminSecurity");
  return (
    <DataTable
      columns={[t("alerts.columns.severity"), t("alerts.columns.rule"), t("alerts.columns.subject"), t("alerts.columns.key")]}
      emptyMessage={loading ? undefined : t("alerts.empty")}
    >
      {alerts.map((alert) => (
        <tr key={alert.key}>
          <td>
            <Badge variant={alert.severity === "critical" ? "danger" : "warning"} dot>
              {t(`severity.${alert.severity}`)}
            </Badge>
          </td>
          <td>{t(`alerts.rules.${KNOWN_RULES.has(alert.rule) ? alert.rule : "unknown"}`)}</td>
          <td>{alert.subject ? <code>{alert.subject}</code> : null}</td>
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
    <section className="card section-stack">
      {alerts.failed ? <StatusBanner tone="error" message={t("loadFailed")} /> : null}
      <div className="admin-security-toolbar">
        <button type="button" className="button-secondary" onClick={alerts.reload}>{t("refresh")}</button>
      </div>
      <SecurityAlertList alerts={alerts.data ?? []} loading={alerts.loading} />
    </section>
  );
}
