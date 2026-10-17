"use client";

import { useLocale, useTranslations } from "next-intl";

import { remainingMinutes } from "@/lib/maintenance";
import { formatDateTime, formatTime, formatWeekdayDate } from "@/lib/utils/format";
import { PublicMaintenanceStatus } from "@/types/api";

type Props = {
  status: PublicMaintenanceStatus;
  /** "page": eigene Wartungsseite (mit Überschrift), "inline": Hinweis auf der Anmeldeseite. */
  variant?: "page" | "inline";
};

/** Kalendertag in Ortszeit ("YYYY-MM-DD") - für "gleicher Tag" und die Wochentagsanzeige. */
function localIsoDate(iso: string): string {
  const date = new Date(iso);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

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
    const date = formatWeekdayDate(localIsoDate(next.starts_at), locale);
    const when = !next.ends_at
      ? t("upcoming.whenOpen", { date, start: formatTime(next.starts_at, locale) })
      : localIsoDate(next.starts_at) === localIsoDate(next.ends_at)
        ? t("upcoming.when", { date, start: formatTime(next.starts_at, locale), end: formatTime(next.ends_at, locale) })
        : t("upcoming.whenRange", { start: formatDateTime(next.starts_at, locale), end: formatDateTime(next.ends_at, locale) });
    const message = next.messages[locale] || next.messages.de;
    // Banner oben in der Anmeldekarte: Ankündigung, Zeitraum, Meldung des Admins.
    return (
      <div className="maintenance-banner" role="status">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
          <path d="M4.5 6.5h15v13h-15zM4.5 10.5h15M8.5 4v4M15.5 4v4" />
        </svg>
        <div className="maintenance-banner-text">
          <span className="maintenance-banner-kicker">{t("upcoming.title")}</span>
          <strong>{when}</strong>
          <span>
            {message ||
              (next.ends_at
                ? t("upcoming.withEnd", { start: formatDateTime(next.starts_at, locale), end: formatDateTime(next.ends_at, locale) })
                : t("upcoming.withoutEnd", { start: formatDateTime(next.starts_at, locale) }))}
          </span>
        </div>
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
