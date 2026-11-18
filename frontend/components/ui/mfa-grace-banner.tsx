"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { formatDateTime } from "@/lib/utils/format";

const DISMISS_KEY = "hocx-mfa-grace-dismissed";

/**
 * Hinweis während der 3-Tage-Frist (Migration 0192): MFA ist für dieses bestehende Konto neu
 * Pflicht, eingerichtet ist noch nichts. «Später» blendet ihn nur für diese Browser-Sitzung aus -
 * er kommt wieder, bis die Frist um ist; danach führt die Anmeldung direkt in die Einrichtung.
 */
export function MfaGraceBanner({ until, onSetup }: { until: string | null | undefined; onSetup: () => void }) {
  const t = useTranslations("security");
  const locale = useLocale();
  const [dismissed, setDismissed] = useState(true);

  useEffect(() => {
    try {
      setDismissed(window.sessionStorage.getItem(DISMISS_KEY) === until);
    } catch {
      setDismissed(false);
    }
  }, [until]);

  if (!until || dismissed) return null;

  function dismiss() {
    setDismissed(true);
    try {
      window.sessionStorage.setItem(DISMISS_KEY, until ?? "");
    } catch {
      // ohne Speicher erscheint der Hinweis beim nächsten Laden wieder
    }
  }

  return (
    <div className="mfa-grace-banner" role="status">
      <div className="mfa-grace-text">
        <strong>{t("grace.title")}</strong>
        <span className="muted">{t("grace.message", { until: formatDateTime(until, locale) })}</span>
      </div>
      <button type="button" className="button-ghost" onClick={dismiss}>{t("grace.later")}</button>
      <button type="button" className="button-primary" onClick={onSetup}>{t("grace.setup")}</button>
    </div>
  );
}
