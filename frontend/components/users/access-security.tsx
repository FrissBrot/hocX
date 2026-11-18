"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DocsLink } from "@/components/ui/help-popover";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/error-message";
import type { TenantMfaPolicy } from "@/types/api";

/** Zugriff › Sicherheit: MFA-Regeln der Organisation. Die Pflicht bei Administrationsrechten ist
 * fest (Katalog), «MFA für alle Logins» schaltet der Admin (tenant.require_mfa, access.manage). */
export function AccessSecurity({ initialPolicy }: { initialPolicy: TenantMfaPolicy | null }) {
  const t = useTranslations("users");
  const tSecurity = useTranslations("security");
  const showToast = useToast();
  const confirm = useConfirm();
  const [policy, setPolicy] = useState(initialPolicy);
  const [busy, setBusy] = useState(false);

  async function toggle(next: boolean) {
    if (!policy || busy) return;
    if (next) {
      const ok = await confirm({
        title: t("security.enableConfirmTitle"),
        message: t("security.enableConfirmMessage", { count: policy.logins_without_mfa }),
        confirmLabel: t("security.enableConfirm"),
      });
      if (!ok) return;
    }
    setBusy(true);
    try {
      const saved = await browserApiFetch<TenantMfaPolicy>("/api/users/mfa-policy", {
        method: "PUT",
        body: JSON.stringify({ require_mfa: next }),
      });
      setPolicy(saved);
      showToast(next ? t("security.enabledToast") : t("security.disabledToast"), "success");
    } catch (error) {
      showToast(apiErrorMessage(error, tSecurity, "apiErrors", t("security.saveFailed")), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("security.title")}</h1>
          <p className="muted">{t("security.description")}</p>
        </div>
      </div>

      <div className="profile-toggle">
        <span className="profile-toggle-text">
          <span>{t("security.adminTitle")}</span>
          <span className="field-help">{t("security.adminHelp")}</span>
        </span>
        <Badge variant="info">{t("security.alwaysRequired")}</Badge>
      </div>

      {policy ? (
        <>
          <label className="profile-toggle">
            <span className="profile-toggle-text">
              <span>{t("security.allTitle")}</span>
              <span className="field-help">{t("security.allHelp")}</span>
            </span>
            <input
              type="checkbox"
              role="switch"
              checked={policy.require_mfa}
              disabled={busy}
              onChange={(event) => void toggle(event.target.checked)}
            />
            <span className="album-picker-switch-track" aria-hidden="true" />
          </label>
          {policy.logins_without_mfa > 0 ? (
            <StatusBanner
              tone={policy.require_mfa ? "warning" : "neutral"}
              message={t(policy.require_mfa ? "security.missingRequired" : "security.missingOptional", {
                count: policy.logins_without_mfa,
                total: policy.logins_total,
              })}
            />
          ) : (
            <span className="field-help">{t("security.allHaveMfa", { total: policy.logins_total })}</span>
          )}
        </>
      ) : (
        <StatusBanner tone="error" message={t("security.loadFailed")} />
      )}
      <DocsLink page="konto" anchor="mfa">{t("security.docs")}</DocsLink>
    </div>
  );
}
