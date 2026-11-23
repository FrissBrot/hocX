"use client";

import { useTranslations } from "next-intl";

/**
 * Pflichthinweis (Release 1.5.2): das Passwort wurde bei der Anmeldung als aus einem Datenleck
 * bekannt erkannt (Migration 0219). Nicht ausblendbar - er verschwindet erst, wenn ein neues
 * Passwort gesetzt ist. Bis dahin verlangt jede Anmeldung den zweiten Faktor bzw. einen E-Mail-Code.
 * Ohne `onChange` (Plattform-Admin) nur Text: das Passwort setzt dort eine andere Owner-Person.
 */
export function PasswordBreachedBanner({ breached, onChange }: { breached: boolean | undefined; onChange?: () => void }) {
  const t = useTranslations("security");
  if (!breached) return null;
  return (
    <div className="mfa-grace-banner password-breached-banner" role="alert">
      <div className="mfa-grace-text">
        <strong>{t("breached.title")}</strong>
        <span>{onChange ? t("breached.message") : t("breached.adminMessage")}</span>
      </div>
      {onChange ? (
        <button type="button" className="button-primary" onClick={onChange}>{t("breached.change")}</button>
      ) : null}
    </div>
  );
}
