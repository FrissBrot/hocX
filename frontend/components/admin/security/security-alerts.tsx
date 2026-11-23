"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
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
      {/* Quittierte Warnungen abgesetzt am Ende, bis die Regel neu auslöst */}
      {[...alerts].sort((a, b) => Number(Boolean(a.acknowledged_at)) - Number(Boolean(b.acknowledged_at))).map((alert) => (
        <tr key={alert.key} className={alert.acknowledged_at ? "admin-alert-acknowledged" : undefined}>
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
            {alert.acknowledged_at ? (
              <>
                <Badge variant="neutral">{t("alerts.acknowledged")}</Badge>
                <div className="muted admin-cell-sub">
                  {t("alerts.acknowledgedBy", { name: alert.acknowledged_by ?? "—", time: formatDateTime(alert.acknowledged_at, locale) })}
                </div>
                {alert.acknowledged_note ? <div className="muted admin-cell-sub">{t("alerts.noteShown", { note: alert.acknowledged_note })}</div> : null}
              </>
            ) : (
              <Badge variant="warning">{t("alerts.open")}</Badge>
            )}
            {alert.clears_at && alert.window_minutes ? (
              <div className="muted admin-cell-sub">
                {t("alerts.clearsAt", { time: formatDateTime(alert.clears_at, locale), minutes: alert.window_minutes })}
              </div>
            ) : null}
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
  const showToast = useToast();
  const alerts = useAdminResource<AuthAlert[]>("/api/admin/auth-security/alerts");
  const [acknowledging, setAcknowledging] = useState<AuthAlert | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  if (alerts.forbidden) return <StatusBanner tone="neutral" message={t("ownerOnly")} />;

  async function send(alert: AuthAlert, acknowledge: boolean, text?: string) {
    setBusy(true);
    try {
      await browserApiFetch(`/api/admin/auth-security/alerts/${acknowledge ? "ack" : "unack"}`, {
        method: "POST",
        body: JSON.stringify(acknowledge && text ? { key: alert.key, note: text } : { key: alert.key }),
      });
      showToast(acknowledge ? t("alerts.acknowledgedToast") : t("alerts.reopenedToast"), "success");
      setAcknowledging(null);
      setNote("");
      alerts.reload();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("loadFailed"), "error");
    } finally {
      setBusy(false);
    }
  }

  function toggleAck(alert: AuthAlert) {
    // Quittieren mit optionaler Notiz (1.5.1, bleibt in 1.6; in 1.7 wird daraus der Vorfall-Status)
    if (alert.acknowledged_at) void send(alert, false);
    else setAcknowledging(alert);
  }

  return (
    <section className="card section-stack" aria-labelledby="security-open-alerts">
      <h2 id="security-open-alerts" className="section-title">{t("alerts.openTitle")}</h2>
      {alerts.failed ? <StatusBanner tone="error" message={t("loadFailed")} /> : null}
      <p className="muted">{t("alerts.ackHelp")}</p>
      <div className="admin-security-toolbar">
        <button type="button" className="button-secondary" onClick={alerts.reload}>{t("refresh")}</button>
      </div>
      <SecurityAlertList alerts={alerts.data ?? []} loading={alerts.loading} onToggleAck={canWrite ? toggleAck : undefined} />
      <Modal open={acknowledging !== null} title={t("alerts.acknowledgeTitle")} description={t("alerts.acknowledgeConfirm")} onClose={() => setAcknowledging(null)}>
        <ModalSaveForm
          className="section-stack"
          onSubmit={(event) => {
            event.preventDefault();
            if (acknowledging) return send(acknowledging, true, note.trim() || undefined);
          }}
        >
          <label className="field-stack">
            <span className="field-label">{t("alerts.noteLabel")}</span>
            <textarea value={note} onChange={(event) => setNote(event.target.value)} maxLength={500} rows={3} />
            <span className="field-help">{t("alerts.noteHelp")}</span>
          </label>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setAcknowledging(null)}>{t("blocks.cancel")}</button>
            <button type="submit" className="button-primary" disabled={busy}>{t("alerts.acknowledge")}</button>
          </div>
        </ModalSaveForm>
      </Modal>
    </section>
  );
}
