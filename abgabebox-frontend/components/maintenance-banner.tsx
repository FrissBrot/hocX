"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { BoxMaintenanceStatus, boxMaintenanceView } from "@/lib/maintenance-view";

const POLL_MS = 30_000;

/** Hinweis während einer Wartung bzw. eines Updates. Gesperrt wird serverseitig (503 aus
 * abgabebox-backend) - hier nur sichtbar gemacht, damit niemand ein Formular ausfüllt, das gerade
 * nicht angenommen wird. Während eines Updates dieselbe Meldung wie die statische Traefik-Seite. */
export function MaintenanceBanner() {
  const t = useTranslations("abgabebox.maintenance");
  const locale = useLocale();
  const [status, setStatus] = useState<BoxMaintenanceStatus | null>(null);
  const [loadedAt] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await fetch("/api/public/maintenance-status", { cache: "no-store" });
        if (response.ok && !cancelled) setStatus((await response.json()) as BoxMaintenanceStatus);
      } catch {
        // Letzten Stand behalten.
      }
      if (!cancelled) setNow(Date.now());
    }
    void load();
    const interval = setInterval(() => void load(), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const view = status ? boxMaintenanceView(status, now, loadedAt) : null;
  if (!status || !view) return null;
  if (view.mode === "update") {
    return (
      <div className="box-maintenance" role="status" aria-live="polite">
        <div className="box-maintenance-head">
          <strong>{view.slow ? t("updateSlowTitle") : t("updateTitle")}</strong>
          {view.versions ? <span className="box-maintenance-version">{view.versions}</span> : null}
        </div>
        <p>{view.slow ? t("updateSlowMessage") : t("updateMessage")}</p>
        <p>{t("updateHint")}</p>
      </div>
    );
  }
  const time = status.estimated_end_at
    ? new Date(status.estimated_end_at).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" })
    : null;
  return (
    <div className="box-maintenance" role="status" aria-live="polite">
      <strong>{view.mode === "maintenance" ? t("title") : t("uploadsTitle")}</strong>
      <p>{view.mode === "maintenance" ? t("message") : t("uploadsMessage")}</p>
      {time ? <p>{t("availableAt", { time })}</p> : <p>{t("estimating")}</p>}
    </div>
  );
}
