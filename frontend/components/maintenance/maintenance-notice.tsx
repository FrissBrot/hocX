"use client";

import { useLocale, useTranslations } from "next-intl";

import { remainingMinutes } from "@/lib/maintenance";
import { formatDateTime, formatTime } from "@/lib/utils/format";
import { PublicMaintenanceStatus } from "@/types/api";

type Props = {
  status: PublicMaintenanceStatus;
  /** "page": eigene Wartungsseite (mit Überschrift), "inline": Hinweis auf der Anmeldeseite. */
  variant?: "page" | "inline";
};

const KNOWN_REASONS = new Set(["manual", "storage_initial_migration", "storage_cutover"]);

/** Wartungshinweis für Anmeldeseite und Wartungsseite. Die Freigabe hängt nie an der hier
 * angezeigten Schätzung - überschreitet sie ihr Ende, erscheint ein klarer Hinweis statt einer 0. */
export function MaintenanceNotice({ status, variant = "inline" }: Props) {
  const t = useTranslations("maintenance");
  const locale = useLocale();
  const custom = status.messages[locale] ?? status.messages.de ?? null;
  const reason = status.reason_code && KNOWN_REASONS.has(status.reason_code) ? status.reason_code : "manual";

  if (!status.active && !status.partial) {
    const next = status.upcoming[0];
    if (!next?.starts_at) return null;
    return (
      <div className="maintenance-notice maintenance-notice-upcoming" role="status">
        <strong>{t("upcoming.title")}</strong>
        <p>
          {next.ends_at
            ? t("upcoming.withEnd", { start: formatDateTime(next.starts_at, locale), end: formatDateTime(next.ends_at, locale) })
            : t("upcoming.withoutEnd", { start: formatDateTime(next.starts_at, locale) })}
        </p>
        {next.messages[locale] ? <p>{next.messages[locale]}</p> : null}
      </div>
    );
  }

  const minutes = remainingMinutes(status);
  const Heading = variant === "page" ? "h1" : "h2";
  return (
    <div className={`maintenance-notice${status.active ? "" : " maintenance-notice-partial"}`} role="status" aria-live="polite">
      <Heading className="maintenance-notice-title">{status.active ? t("title") : t("partial.title")}</Heading>
      <p>{custom ?? (status.active ? t(`reasons.${reason}`) : t("partial.message"))}</p>
      {status.estimate_state === "overdue" ? (
        <p className="maintenance-notice-estimate">{t("estimate.overdue")}</p>
      ) : status.estimate_state === "estimated" && status.estimated_end_at && minutes ? (
        <>
          <p className="maintenance-notice-estimate">{t("estimate.availableAt", { time: formatTime(status.estimated_end_at, locale) })}</p>
          <p className="maintenance-notice-estimate muted">
            {minutes.high >= 120
              ? t("estimate.remainingHours", { low: Math.max(1, Math.round(minutes.low / 60)), high: Math.ceil(minutes.high / 60) })
              : minutes.low === minutes.high
                ? t("estimate.remainingAbout", { count: minutes.high })
                : t("estimate.remainingRange", { low: minutes.low, high: minutes.high })}
          </p>
        </>
      ) : (
        <p className="maintenance-notice-estimate muted">{t("estimate.estimating")}</p>
      )}
      <p className="muted maintenance-notice-hint">{status.active ? t("autoRefresh") : t("partial.hint")}</p>
    </div>
  );
}
