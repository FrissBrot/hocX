"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { StatusBanner } from "@/components/ui/status-banner";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import type { NotificationCategory, NotificationPreferences } from "@/types/api";

/** Eigene E-Mail-Benachrichtigungen im Profil. Jeder Schalter speichert sofort. */
export function NotificationPreferencesPanel({ open }: { open: boolean }) {
  const t = useTranslations("settings.profileModal.notifications");
  const showToast = useToast();
  const [data, setData] = useState<NotificationPreferences | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    browserApiFetch<NotificationPreferences>("/api/users/me/notification-preferences")
      .then((loaded) => { if (!cancelled) setData(loaded); })
      .catch((error) => { if (!cancelled) showToast(error instanceof Error ? error.message : t("loadFailed"), "error"); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  async function toggle(category: NotificationCategory, enabled: boolean) {
    setBusy(true);
    try {
      setData(await browserApiFetch<NotificationPreferences>("/api/users/me/notification-preferences", {
        method: "PUT",
        body: JSON.stringify({ preferences: [{ category, enabled }] }),
      }));
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("saveFailed"), "error");
    } finally {
      setBusy(false);
    }
  }

  if (!data) return <p className="muted">{t("loading")}</p>;
  return (
    <div className="grid">
      <p className="muted">{t("description")}</p>
      {!data.email_enabled ? <StatusBanner tone="neutral" message={t("platformOff")} /> : null}
      {!data.has_email ? <StatusBanner tone="neutral" message={t("noEmail")} /> : null}
      {data.preferences.map((preference) => (
        <label key={preference.category} className="profile-toggle">
          <span className="profile-toggle-text">
            <span>{t(`category.${preference.category}.label`)}</span>
            <span className="field-help">{t(`category.${preference.category}.hint`)}</span>
          </span>
          <input
            type="checkbox"
            role="switch"
            checked={preference.enabled}
            disabled={busy}
            onChange={(event) => void toggle(preference.category, event.target.checked)}
          />
          <span className="album-picker-switch-track" aria-hidden="true" />
        </label>
      ))}
    </div>
  );
}
