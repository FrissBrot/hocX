"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

type Status = { active: boolean; uploads_blocked: boolean; estimated_end_at: string | null };

const POLL_MS = 30_000;

/** Hinweis während einer Wartung. Gesperrt wird serverseitig (503 aus abgabebox-backend) - hier
 * nur sichtbar gemacht, damit niemand ein Formular ausfüllt, das gerade nicht angenommen wird. */
export function MaintenanceBanner() {
  const t = useTranslations("abgabebox.maintenance");
  const locale = useLocale();
  const [status, setStatus] = useState<Status | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await fetch("/api/public/maintenance-status", { cache: "no-store" });
        if (response.ok && !cancelled) setStatus((await response.json()) as Status);
      } catch {
        // Letzten Stand behalten.
      }
    }
    void load();
    const interval = setInterval(() => void load(), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (!status || (!status.active && !status.uploads_blocked)) return null;
  const time = status.estimated_end_at
    ? new Date(status.estimated_end_at).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" })
    : null;
  return (
    <div className="box-maintenance" role="status" aria-live="polite">
      <strong>{status.active ? t("title") : t("uploadsTitle")}</strong>
      <p>{status.active ? t("message") : t("uploadsMessage")}</p>
      {time ? <p>{t("availableAt", { time })}</p> : <p>{t("estimating")}</p>}
    </div>
  );
}
