"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { MaintenanceView, versionLabel } from "@/lib/maintenance";
import { formatTime } from "@/lib/utils/format";
import { PublicMaintenanceStatus } from "@/types/api";

type Props = {
  status: PublicMaintenanceStatus;
  view: MaintenanceView;
  /** Jetzt (ms) - von der Seite im Sekundentakt nachgeführt (Countdown, «dauert länger»). */
  now: number;
  /** Nächste automatische Prüfung (ms), für den Countdown der Wartung. */
  nextCheckAt: number | null;
  /** Laufende Version dieses Frontends (Fusszeile der Wartung). */
  runningVersion: string | null;
  /** Öffentliche Statusseite (HOCX_STATUS_PAGE_URL), null = kein Hinweis. */
  statusPageUrl: string | null;
  /** «Jetzt neu laden»: prüft sofort, die Seite leitet weiter, sobald hocX bereit ist. */
  onCheck: () => Promise<void>;
  copyright: React.ReactNode;
};

const KNOWN_REASONS = new Set(["manual", "storage_initial_migration", "storage_cutover", "backup_restore", "deploy"]);

function ReloadIcon({ spinning }: { spinning?: boolean }) {
  return (
    <svg className={spinning ? "maint-icon maint-icon-spin" : "maint-icon"} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M20 11a8 8 0 1 0-2.3 5.7" />
      <path d="M20 4v7h-7" />
    </svg>
  );
}

function Brand() {
  return (
    <div className="maint-brand">
      <span className="maint-logo" aria-hidden="true">hX{/* i18n-ok: Logo-Kürzel, kein Text */}</span>
      <span className="maint-brand-name">HOCX{/* i18n-ok: Produktname */}</span>
    </div>
  );
}

/** Wartungs- (1a) bzw. Update-Seite (1b). Die statische Traefik-Seite
 * (infra/maintenance/maintenance.html) zeigt dieselbe Update-Meldung mit denselben Texten. */
export function MaintenanceScreen({ status, view, now, nextCheckAt, runningVersion, statusPageUrl, onCheck, copyright }: Props) {
  const t = useTranslations("maintenance");
  const locale = useLocale();
  const [checking, setChecking] = useState(false);

  if (view.mode === "update") {
    const { fromVersion, toVersion, slow } = view;
    const versions = fromVersion && toVersion && fromVersion !== toVersion
      ? { label: `${versionLabel(fromVersion)} → ${versionLabel(toVersion)}`, aria: t("update.versions", { from: versionLabel(fromVersion), to: versionLabel(toVersion) }) }
      : fromVersion || toVersion
        ? { label: versionLabel((toVersion || fromVersion) as string), aria: t("update.version", { version: versionLabel((toVersion || fromVersion) as string) }) }
        : null;

    async function check() {
      setChecking(true);
      try {
        await onCheck();
      } finally {
        setChecking(false);
      }
    }

    return (
      <div className="maint-page">
        <main className="maint-card" aria-labelledby="maintenance-title">
          <div className="maint-head">
            <Brand />
            {versions ? (
              <span className="maint-pill maint-pill-version">
                <span aria-hidden="true">{versions.label}</span>
                <span className="visually-hidden">{versions.aria}</span>
              </span>
            ) : null}
          </div>
          <div className="maint-body" role="status" aria-live="polite">
            <h1 className="maint-title" id="maintenance-title">{slow ? t("update.slowTitle") : t("update.title")}</h1>
            <p className="maint-text">{slow ? t("update.slowMessage") : t("update.message")}</p>
          </div>
          <div className="maint-progress maint-progress-indeterminate" aria-hidden="true" />
          <div className="maint-actions">
            <button type="button" className="button-primary maint-reload" onClick={() => void check()} disabled={checking} aria-busy={checking}>
              <ReloadIcon spinning={checking} />
              <span>{checking ? t("update.checking") : t("update.reload")}</span>
            </button>
            <p className="maint-hint">{t("update.autoReload")}</p>
          </div>
          {slow && statusPageUrl ? (
            <p className="maint-status-line">
              {t.rich("update.statusPage", {
                link: (chunks) => <a href={statusPageUrl} target="_blank" rel="noopener noreferrer">{chunks}</a>,
              })}
            </p>
          ) : null}
        </main>
        <div className="maint-footer">
          <span className="maint-dot maint-dot-update" aria-hidden="true" />
          {toVersion ? <span className="maint-version">{versionLabel(toVersion)}</span> : null}
          {copyright}
        </div>
      </div>
    );
  }

  const custom = status.messages[locale] ?? status.messages.de ?? null;
  const reason = status.reason_code && KNOWN_REASONS.has(status.reason_code) ? status.reason_code : "manual";
  const { eta } = view;
  const seconds = nextCheckAt === null ? null : Math.max(0, Math.ceil((nextCheckAt - now) / 1000));
  const chip = eta.state === "known" && eta.minutes
    ? eta.minutes.high >= 120
      ? t("screen.remainingHours", { low: Math.max(1, Math.round(eta.minutes.low / 60)), high: Math.ceil(eta.minutes.high / 60) })
      : eta.minutes.low === eta.minutes.high
        ? t("screen.remainingAbout", { count: eta.minutes.high })
        : t("screen.remainingRange", { low: eta.minutes.low, high: eta.minutes.high })
    : null;

  return (
    <div className="maint-page">
      <main className="maint-card" aria-labelledby="maintenance-title">
        <div className="maint-head">
          <Brand />
          <span className="maint-pill maint-pill-warning"><span className="maint-dot maint-dot-warning" aria-hidden="true" />{t("screen.pill")}</span>
        </div>
        <div className="maint-body" role="status" aria-live="polite">
          <h1 className="maint-title" id="maintenance-title">{t("title")}</h1>
          <p className="maint-text">{custom ?? t(`reasons.${reason}`)}</p>
        </div>
        <div className="maint-eta">
          <div className="maint-eta-row">
            <div className="maint-eta-main">
              <span className="maint-eta-label">{t("screen.etaLabel")}</span>
              {eta.state === "known" ? (
                <span className="maint-eta-time">
                  {t.rich("screen.etaTime", {
                    time: formatTime(eta.endAt, locale),
                    clock: (chunks) => <span className="maint-eta-clock">{chunks}</span>,
                    unit: (chunks) => <span className="maint-eta-unit">{chunks}</span>,
                  })}
                </span>
              ) : (
                <span className="maint-eta-unknown">{eta.state === "overdue" ? t("screen.etaOverdue") : t("screen.etaUnknown")}</span>
              )}
            </div>
            {chip ? <span className="maint-pill maint-pill-accent">{chip}</span> : null}
          </div>
          {eta.state === "known" && eta.progress ? (
            <div
              className="maint-eta-bar"
              role="progressbar"
              aria-label={t("screen.progressLabel")}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(eta.progress.done * 100)}
            >
              <span className="maint-eta-bar-done" style={{ width: `${eta.progress.done * 100}%` }} />
              <span className="maint-eta-bar-range" style={{ left: `${eta.progress.uncertainFrom * 100}%` }} />
            </div>
          ) : null}
        </div>
        <div className="maint-card-footer">
          <ReloadIcon />
          <span className="maint-card-footer-text">{t("screen.autoCheck")}</span>
          {seconds !== null ? (
            <span className="maint-countdown">{seconds > 0 ? t("screen.countdown", { seconds }) : t("screen.countdownNow")}</span>
          ) : null}
        </div>
      </main>
      <div className="maint-footer">
        <span className="maint-dot maint-dot-ok" aria-hidden="true" />
        {runningVersion ? <span className="maint-version">{versionLabel(runningVersion)}</span> : null}
        {copyright}
      </div>
    </div>
  );
}
