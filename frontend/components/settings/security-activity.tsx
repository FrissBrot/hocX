"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateTime } from "@/lib/utils/format";
import type { TenantSecurityAccount, TenantSecurityActivity, TenantSecurityWarningKind } from "@/types/admin-security";

const WARNING_TONE: Record<TenantSecurityWarningKind, BadgeVariant> = {
  account_attack: "danger",
  account_locked: "danger",
  privileged_new_device: "warning",
  mfa_removed: "warning",
};
const OUTCOME_TONE: Record<string, BadgeVariant> = { success: "success", failure: "danger", blocked: "warning", challenged: "info", info: "neutral" };
const RISK_TONE: Record<string, BadgeVariant> = { normal: "neutral", moderate: "info", high: "warning", critical: "danger" };
const KNOWN_EVENTS = new Set([
  "login.password", "login.locked", "login.challenge", "login.mfa.totp", "login.mfa.passkey", "login.success", "mfa.enroll",
  "mfa.remove", "session.revoke", "session.logout", "reset.request", "reset.complete", "password.change", "stepup.success", "stepup.failure",
]);
// Übersetzungsschlüssel ohne Punkte (next-intl liest Punkte als Verschachtelung): login.mfa.totp -> login_mfa_totp
const KNOWN_OUTCOMES = new Set(Object.keys(OUTCOME_TONE));

/** /tenant-settings/security: Warnungen, Aktivität je Konto, letzte Ereignisse der eigenen
 * Organisation (security.read). Sitzungen beenden nur mit access.manage (canRevoke); das Backend
 * verlangt dafür eine frische Anmeldung, der Bestätigungsdialog erscheint automatisch. */
export function SecurityActivity({ initial, canRevoke }: { initial: TenantSecurityActivity; canRevoke: boolean }) {
  const t = useTranslations("tenantSettings.security");
  const locale = useLocale();
  const confirm = useConfirm();
  const showToast = useToast();
  const [data, setData] = useState(initial);

  async function revoke(account: TenantSecurityAccount) {
    const confirmed = await confirm({ message: t("revokeConfirm", { name: account.display_name }), tone: "danger", confirmLabel: t("revoke") });
    if (!confirmed) return;
    try {
      const result = await browserApiFetch<{ revoked: number }>(`/api/auth-security/accounts/${encodeURIComponent(account.user_id)}/revoke-sessions`, { method: "POST" });
      showToast(t("revoked", { count: result.revoked }), "success");
      setData(await browserApiFetch<TenantSecurityActivity>("/api/auth-security/activity"));
    } catch {
      showToast(t("revokeFailed"), "error");
    }
  }

  const summary = data.summary;
  return (
    <div className="section-stack">
      <div className="tenant-security-summary">
        {([
          ["failures24h", summary.failures_24h],
          ["accountsWithFailures", summary.accounts_with_failures_24h],
          ["newDeviceLogins", summary.new_device_logins_7d],
          ["blocked24h", summary.blocked_24h],
        ] as const).map(([key, value]) => (
          <div className="card tenant-security-stat" key={key}>
            <span className="tenant-security-stat-label">{t(`summary.${key}`)}</span>
            <strong className="tenant-security-stat-value">{Number(value)}</strong>
          </div>
        ))}
      </div>

      <section className="section-stack">
        <DataToolbar title={t("warningsTitle")} />
        <DataTable columns={[t("columns.warning"), t("columns.when")]} emptyMessage={t("warningsEmpty")}>
          {data.warnings.map((warning) => (
            <tr key={`${warning.kind}-${warning.user_id}`}>
              <td>
                <Badge variant={WARNING_TONE[warning.kind] ?? "warning"} dot>
                  {t(`warnings.${warning.kind}`, { name: warning.display_name, count: Number(warning.count) })}
                </Badge>
              </td>
              <td>{formatDateTime(warning.last_at, locale)}</td>
            </tr>
          ))}
        </DataTable>
      </section>

      <section className="section-stack">
        <DataToolbar title={t("accountsTitle")} />
        <DataTable
          columns={[t("columns.account"), t("columns.lastLogin"), t("columns.failures"), t("columns.sessions"), ...(canRevoke ? [t("columns.actions")] : [])]}
          emptyMessage={t("accountsEmpty")}
        >
          {data.accounts.map((account) => (
            <tr key={account.user_id}>
              <td>{account.display_name}</td>
              <td>{account.last_login ? formatDateTime(account.last_login, locale) : t("never")}</td>
              <td>{account.failures_7d > 0 ? <Badge variant="warning">{account.failures_7d}</Badge> : 0}</td>
              <td>{account.active_sessions}</td>
              {canRevoke ? (
                <td>
                  <button type="button" className="button-secondary" disabled={account.active_sessions === 0} onClick={() => void revoke(account)}>
                    {t("revoke")}
                  </button>
                </td>
              ) : null}
            </tr>
          ))}
        </DataTable>
      </section>

      <section className="section-stack">
        <DataToolbar title={t("eventsTitle")} />
        <DataTable
          columns={[t("columns.time"), t("columns.event"), t("columns.outcome"), t("columns.account"), t("columns.device"), t("columns.risk")]}
          emptyMessage={t("eventsEmpty")}
        >
          {data.events.map((event, index) => (
            <tr key={`${event.ts}-${index}`}>
              <td>{formatDateTime(event.ts, locale)}</td>
              <td>{KNOWN_EVENTS.has(event.event_type) ? t(`events.${event.event_type.replaceAll(".", "_")}`) : event.event_type}</td>
              <td>
                {KNOWN_OUTCOMES.has(event.outcome) ? <Badge variant={OUTCOME_TONE[event.outcome]} dot>{t(`outcomes.${event.outcome}`)}</Badge> : null}
              </td>
              <td>{event.display_name ?? null}</td>
              <td>{event.user_agent_family ?? null}</td>
              <td>{event.risk_level ? <Badge variant={RISK_TONE[event.risk_level] ?? "neutral"}>{t(`risk.${event.risk_level}`)}</Badge> : null}</td>
            </tr>
          ))}
        </DataTable>
      </section>
    </div>
  );
}
