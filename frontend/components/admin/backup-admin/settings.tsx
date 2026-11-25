"use client";

import { FormEvent, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { StatusBanner } from "@/components/ui/status-banner";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/contexts/toast-context";
import { stepUpFetch } from "@/lib/admin-step-up";
import { formatDateTime, formatFileSize } from "@/lib/utils/format";
import type { BackupSettings } from "@/types/api";

import { num, retentionEstimate, runHoursOfDay, zurichDay } from "./backup-utils";
import { errorText, type TFunc } from "./shared";

type SettingsForm = Omit<BackupSettings, "worker_config" | "repository" | "ntfy_configured" | "updated_at" | "updated_by_email">;
type NumberKey = { [K in keyof SettingsForm]: SettingsForm[K] extends number ? K : never }[keyof SettingsForm];

function formOf(settings: BackupSettings): SettingsForm {
  return {
    schedule_enabled: settings.schedule_enabled, interval_hours: settings.interval_hours, schedule_offset_minutes: settings.schedule_offset_minutes,
    keep_within_days: settings.keep_within_days, keep_daily: settings.keep_daily, keep_weekly: settings.keep_weekly, keep_monthly: settings.keep_monthly,
    verify_interval_hours: settings.verify_interval_hours, verify_sample_objects: settings.verify_sample_objects,
    restore_test_interval_days: settings.restore_test_interval_days, success_notification: settings.success_notification,
  };
}

const LIMITS: Record<NumberKey, [number, number]> = {
  interval_hours: [1, 168], schedule_offset_minutes: [0, 1439], keep_within_days: [0, 3650], keep_daily: [0, 3650], keep_weekly: [0, 520],
  keep_monthly: [0, 240], verify_interval_hours: [1, 8760], verify_sample_objects: [0, 100000], restore_test_interval_days: [1, 365],
};

export function Settings({ t, locale, settings, isOwner, onSaved }: { t: TFunc; locale: string; settings: BackupSettings; isOwner: boolean; onSaved: (value: BackupSettings) => void }) {
  const showToast = useToast();
  const [form, setForm] = useState<SettingsForm>(() => formOf(settings));
  const [saving, setSaving] = useState(false);
  const [savedNow, setSavedNow] = useState(false);
  const update = <K extends keyof SettingsForm>(key: K, value: SettingsForm[K]) => { setSavedNow(false); setForm((current) => ({ ...current, [key]: value })); };
  const config = settings.worker_config;
  const repo = settings.repository;
  const dirty = JSON.stringify(form) !== JSON.stringify(formOf(settings));
  const invalid = (Object.keys(LIMITS) as NumberKey[]).some((key) => !Number.isInteger(form[key]) || form[key] < LIMITS[key][0] || form[key] > LIMITS[key][1])
    || form.keep_within_days + form.keep_daily + form.keep_weekly + form.keep_monthly === 0;

  const today = zurichDay(Date.now());
  const runs = useMemo(() => runHoursOfDay(today, Math.max(1, num(form.interval_hours)), Math.max(0, num(form.schedule_offset_minutes))), [today, form.interval_hours, form.schedule_offset_minutes]);
  const estimate = retentionEstimate({ interval_hours: Math.max(1, num(form.interval_hours)), keep_within_days: num(form.keep_within_days),
    keep_daily: num(form.keep_daily), keep_weekly: num(form.keep_weekly), keep_monthly: num(form.keep_monthly) });
  const lookbackTotal = Math.max(1, estimate.segments.reduce((sum, segment) => sum + segment.days, 0));

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isOwner || invalid) return;
    setSaving(true);
    try {
      const saved = await stepUpFetch<BackupSettings>("backup-settings", "/api/admin/backups/settings", { method: "PUT", body: JSON.stringify(form) });
      onSaved(saved);
      setForm(formOf(saved));
      setSavedNow(true);
      showToast(t("toast.settingsSaved"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    } finally {
      setSaving(false);
    }
  }

  const numberField = (key: NumberKey, label: string, unit: string) => (
    <label className="field-stack">
      <span className="field-label">{label}</span>
      <span className="backup-unit-input">
        <input className="input" type="number" inputMode="numeric" min={LIMITS[key][0]} max={LIMITS[key][1]} value={Number.isNaN(form[key]) ? "" : form[key]} disabled={!isOwner}
          onChange={(event) => update(key, event.target.value === "" ? Number.NaN : Number(event.target.value))} />
        <span className="backup-unit" aria-hidden="true">{unit}</span>
      </span>
    </label>
  );

  return (
    <div className="backup-settings-view">
      <form className="backup-settings-main" onSubmit={submit}>
        {!isOwner ? <StatusBanner tone="neutral" message={t("settings.readOnly")} /> : null}
        <section className="card backup-card" aria-labelledby="backup-schedule-title">
          <div className="backup-card-head">
            <div>
              <h2 id="backup-schedule-title" className="backup-section-title">{t("settings.scheduleTitle")}</h2>
              <p className="muted backup-small">{t("settings.description")}</p>
            </div>
          </div>
          <Switch checked={form.schedule_enabled} disabled={!isOwner} onChange={(value) => update("schedule_enabled", value)} label={t("settings.scheduleEnabled")}
            help={form.schedule_enabled ? undefined : t("settings.scheduleOffHint")} />
          <div className={form.schedule_enabled ? "backup-stack" : "backup-stack backup-dimmed"}>
            <div className="backup-dayline" role="img" aria-label={t("settings.runsToday", { times: runs.map(hourLabel).join(", ") || "—" })}>
              {runs.slice(0, 24).map((hour) => (
                <span key={hour} className="backup-dayline-run" style={{ left: `${(hour / 24) * 100}%` }}>
                  {runs.length <= 6 ? <span className="backup-dayline-label">{hourLabel(hour)}</span> : null}
                </span>
              ))}
            </div>
            <div className="backup-dayline-axis" aria-hidden="true"><span>00</span><span>06</span><span>12</span><span>18</span><span>24</span></div>
            <span className="muted backup-small">{t("settings.scheduleText", { offset: form.schedule_offset_minutes })}</span>
          </div>
          <div className="backup-field-grid">
            {numberField("interval_hours", t("settings.intervalShort"), t("settings.unitHours"))}
            {numberField("schedule_offset_minutes", t("settings.offsetShort"), t("settings.unitOffset"))}
          </div>
        </section>

        <section className="card backup-card" aria-labelledby="backup-retention-title">
          <div>
            <h2 id="backup-retention-title" className="backup-section-title">{t("settings.retentionTitle")}</h2>
            <p className="muted backup-small">{t("settings.retentionHelp")}</p>
          </div>
          <div className="backup-stack">
            <div className="backup-retention-bar" role="img" aria-label={t("settings.retentionSummary", { months: Math.round(estimate.lookbackDays / 30), points: estimate.points })}>
              {estimate.segments.map((segment) => (
                <span key={segment.key} className={`backup-retention-${segment.key}`} style={{ flexGrow: segment.days / lookbackTotal }}>{t(`settings.segment.${segment.key}`)}</span>
              ))}
            </div>
            <span className="backup-small">{t("settings.retentionSummary", { months: Math.round(estimate.lookbackDays / 30), points: estimate.points })}</span>
          </div>
          <div className="backup-field-grid">
            {numberField("keep_within_days", t("settings.keepWithin"), t("settings.unitDays"))}
            {numberField("keep_daily", t("settings.keepDaily"), t("settings.unitPoints"))}
            {numberField("keep_weekly", t("settings.keepWeekly"), t("settings.unitPoints"))}
            {numberField("keep_monthly", t("settings.keepMonthly"), t("settings.unitPoints"))}
          </div>
        </section>

        <section className="card backup-card" aria-labelledby="backup-checks-title">
          <h2 id="backup-checks-title" className="backup-section-title">{t("settings.checksTitle")}</h2>
          <div className="backup-field-grid backup-field-grid-3">
            {numberField("verify_interval_hours", t("settings.verifyIntervalShort"), t("settings.unitHoursShort"))}
            {numberField("verify_sample_objects", t("settings.verifySample"), t("settings.unitFiles"))}
            {numberField("restore_test_interval_days", t("settings.restoreTestIntervalShort"), t("settings.unitDays"))}
          </div>
          <p className="muted backup-small">{t("settings.heavyWindow")}</p>
          <fieldset className="backup-fieldset">
            <legend className="field-label">{t("settings.successNotification")}</legend>
            <div className="backup-choice-grid backup-choice-grid-3">
              {(["off", "daily", "each"] as const).map((value) => (
                <label key={value} className={form.success_notification === value ? "backup-choice backup-choice-on backup-choice-compact" : "backup-choice backup-choice-compact"}>
                  <input type="radio" name="backup-success-notification" value={value} checked={form.success_notification === value} disabled={!isOwner}
                    className="backup-choice-input" onChange={() => update("success_notification", value)} />
                  <span className="backup-choice-text"><strong>{t(`settings.notify.${value}`)}</strong><span className="muted backup-small">{t(`settings.notifyHelp.${value}`)}</span></span>
                </label>
              ))}
            </div>
            <span className="muted backup-small">{t("settings.problemsAlways")}</span>
          </fieldset>
        </section>

        {isOwner ? (
          <div className="card backup-savebar">
            <span className="muted backup-small">{savedNow ? t("settings.savedNow") : settings.updated_by_email
              ? t("settings.updated", { email: settings.updated_by_email, time: formatDateTime(settings.updated_at, locale) }) : t("settings.neverChanged")}</span>
            <button type="submit" className="button-primary" disabled={saving || !dirty || invalid}>{t("actions.saveWithPasskey")}</button>
          </div>
        ) : null}
        {invalid && isOwner ? <StatusBanner tone="error" message={t("settings.invalid")} /> : null}
      </form>

      <section className="card backup-card backup-connection" aria-labelledby="backup-connection-title">
        <div>
          <h2 id="backup-connection-title" className="backup-section-title">{t("settings.connectionTitle")}</h2>
          <p className="muted backup-small">{t("settings.connectionDescription")}</p>
        </div>
        <div className={repo.ok ? "backup-conn backup-conn-ok" : repo.ok === false ? "backup-conn backup-conn-bad" : "backup-conn"}>
          <span className="backup-conn-dot" aria-hidden="true" />
          <div className="backup-stack-tight">
            <strong>{repo.ok ? t("settings.connOk") : repo.ok === false ? t("settings.connBad") : t("settings.connUnknown")}</strong>
            <span className="backup-small">
              {repo.ok === false && repo.error_code ? errorText(t, `borg_${repo.error_code}`, repo.error) : null}
              {repo.ok && repo.checked_at ? t("settings.connOkSub", { time: formatDateTime(repo.checked_at, locale) }) : null}
            </span>
          </div>
        </div>
        {/* Adresse/Benutzer der Storage Box nur für Owner - Support bekommt das Feld nicht von der API. */}
        {typeof config.repository === "string" && config.repository ? <div className="backup-repo-url backup-mono">{config.repository}</div> : null}
        <dl className="storage-facts">
          <dt>{t("settings.encryption")}</dt><dd>{repo.encryption ?? "—"}</dd>
          <dt>{t("settings.repositoryId")}</dt><dd className="backup-id">{repo.repository_id ? `${repo.repository_id.slice(0, 4)}…${repo.repository_id.slice(-4)}` : "—"} {config.repository_id_pinned ? <Badge variant="success">{t("settings.pinned")}</Badge> : <Badge variant="warning">{t("settings.notPinned")}</Badge>}</dd>
          <dt>{t("settings.hostKey")}</dt><dd>{config.host_key_pinned ? <Badge variant="success">{t("settings.pinned")}</Badge> : <Badge variant="danger">{t("settings.notPinned")}</Badge>}</dd>
          <dt>{t("settings.secrets")}</dt><dd>{t("settings.secretsValue", { key: config.ssh_key_configured ? t("settings.present") : t("settings.missing"), passphrase: config.passphrase_configured ? t("settings.present") : t("settings.missing") })}</dd>
          <dt>{t("settings.maintenanceKey")}</dt><dd>{config.maintenance_key_present ? <Badge variant="warning">{t("settings.maintenanceKeyPresent")}</Badge> : <>{t("settings.maintenanceKeyAbsentShort")} <Badge variant="success">{t("settings.recommended")}</Badge></>}</dd>
          <dt>{t("settings.borgVersion")}</dt><dd>{repo.borg_version ?? "—"}</dd>
          <dt>{t("settings.staging")}</dt><dd>{t("settings.stagingValue", { budget: formatFileSize(Number(config.staging_max_bytes ?? 0), locale), free: repo.staging_free_bytes !== null ? formatFileSize(repo.staging_free_bytes, locale) : "—" })}</dd>
          <dt>{t("settings.ntfy")}</dt><dd>{settings.ntfy_configured ? <Badge variant="success">{t("settings.ntfyConfigured")}</Badge> : <><Badge variant="warning">{t("settings.ntfyMissing")}</Badge> <a href="/admin/notifications">{t("settings.ntfyLink")}</a></>}</dd>
          <dt>{t("settings.lastCheck")}</dt><dd>{repo.checked_at ? formatDateTime(repo.checked_at, locale) : "—"}</dd>
        </dl>
      </section>
    </div>
  );
}

function hourLabel(hour: number): string {
  const h = Math.floor(hour);
  const m = Math.round((hour - h) * 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`; // i18n-ok: Uhrzeit HH:MM, keine Sprache
}
