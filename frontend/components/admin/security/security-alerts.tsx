"use client";

import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { useAdminResource } from "@/components/admin/security/use-admin-resource";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateTime } from "@/lib/utils/format";
import type { AuthAlert } from "@/types/admin-security";

const KNOWN_RULES = new Set(["stuffing", "spraying", "account_attack", "admin_mfa", "admin_new_device", "blocks", "network", "cross_tenant", "tenant", "limiter"]);

/** Tabelle der ausgelösten Alarmregeln. Titel kommen aus den Übersetzungen (je Regel), der
 * Schlüssel `auth:<regel>[:<pseudonym>]` entspricht dem Problemschlüssel im Systemmonitor.
 * Mit `onToggleAck` (nur Warnungsseite, owner) lassen sich Warnungen quittieren (1.5.1). */
export function SecurityAlertList({
  alerts,
  loading,
  onToggleAck,
}: {
  alerts: AuthAlert[];
  loading?: boolean;
  onToggleAck?: (alert: AuthAlert) => void;
}) {
  const t = useTranslations("adminSecurity");
  const locale = useLocale();
  const columns = [t("alerts.columns.severity"), t("alerts.columns.rule"), t("alerts.columns.subject"), t("alerts.columns.status"), t("alerts.columns.key")];
  if (onToggleAck) columns.push(t("alerts.columns.actions"));
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
          <td>{alert.subject ? <code>{alert.subject}</code> : null}</td>
          <td>
            {alert.acknowledged_at ? (
              <>
                <Badge variant="neutral">{t("alerts.acknowledged")}</Badge>
                <div className="muted admin-cell-sub">
                  {t("alerts.acknowledgedBy", { name: alert.acknowledged_by ?? "—", time: formatDateTime(alert.acknowledged_at, locale) })}
                </div>
              </>
            ) : (
              <Badge variant="warning">{t("alerts.open")}</Badge>
            )}
          </td>
          <td><code>{alert.key}</code></td>
          {onToggleAck ? (
            <td>
              <button type="button" className="button-secondary" onClick={() => onToggleAck(alert)}>
                {alert.acknowledged_at ? t("alerts.reopen") : t("alerts.acknowledge")}
              </button>
            </td>
          ) : null}
        </tr>
      ))}
    </DataTable>
  );
}

export function SecurityAlertsView({ canWrite = true }: { canWrite?: boolean }) {
  const t = useTranslations("adminSecurity");
  const confirm = useConfirm();
  const showToast = useToast();
  const alerts = useAdminResource<AuthAlert[]>("/api/admin/auth-security/alerts");
  if (alerts.forbidden) return <StatusBanner tone="neutral" message={t("ownerOnly")} />;

  async function toggleAck(alert: AuthAlert) {
    const acknowledging = !alert.acknowledged_at;
    if (acknowledging) {
      const ok = await confirm({ message: t("alerts.acknowledgeConfirm"), confirmLabel: t("alerts.acknowledge") });
      if (!ok) return;
    }
    try {
      await browserApiFetch(`/api/admin/auth-security/alerts/${acknowledging ? "ack" : "unack"}`, {
        method: "POST",
        body: JSON.stringify({ key: alert.key }),
      });
      showToast(acknowledging ? t("alerts.acknowledgedToast") : t("alerts.reopenedToast"), "success");
      alerts.reload();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("loadFailed"), "error");
    }
  }

  return (
    <section className="card section-stack">
      {alerts.failed ? <StatusBanner tone="error" message={t("loadFailed")} /> : null}
      <p className="muted">{t("alerts.ackHelp")}</p>
      <div className="admin-security-toolbar">
        <button type="button" className="button-secondary" onClick={alerts.reload}>{t("refresh")}</button>
      </div>
      <SecurityAlertList alerts={alerts.data ?? []} loading={alerts.loading} onToggleAck={canWrite ? toggleAck : undefined} />
    </section>
  );
}
