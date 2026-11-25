"use client";

import { useEffect, useId, useMemo, useState } from "react";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { HealthBadge } from "@/components/ui/health-badge";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateTime, formatFileSize, formatTime, formatWeekdayDate, toIntlLocale } from "@/lib/utils/format";
import type { BackupJobPage, BackupProblem, BackupSettings, BackupStatus } from "@/types/api";

import { buildTimeline, levelDue, savingsPercent, type SlotState, type TimelineDay } from "./backup-utils";
import { ageText, durationText, JobPanel, RestorePanel, untilText, type TFunc } from "./shared";

export type BackupNavigate = (patch: Record<string, string | null>) => void;
export type BackupActions = {
  startBackup: () => Promise<void>;
  startRestoreTest: () => Promise<void>;
  verifyJob: (jobId: string) => Promise<void>;
  busy: string | null;
};

type HeroState = "ok" | "running" | "warning" | "critical" | "disabled";
const HERO_HEALTH = { ok: "ok", running: "degraded", warning: "warning", critical: "critical", disabled: "unknown" } as const;
const SEVERITY_VARIANT: Record<BackupProblem["severity"], BadgeVariant> = { warning: "warning", critical: "danger" };

const CONNECTION_PROBLEMS = new Set(["configuration", "repository_unreachable", "repository_id_mismatch", "repository_not_encrypted",
  "passphrase_wrong", "host_key_mismatch", "capacity_low", "staging_low", "schedule_disabled", "disabled"]);

type ProblemAction = { label: string; run: () => void };

function problemAction(t: TFunc, problem: BackupProblem, navigate: BackupNavigate, status: BackupStatus, isOwner: boolean, actions: BackupActions): ProblemAction | null {
  const code = problem.code;
  if (CONNECTION_PROBLEMS.has(code)) return { label: t("problemAction.settings"), run: () => navigate({ tab: "settings" }) };
  if (code === "partial") return { label: t("problemAction.history"), run: () => navigate({ tab: "history", state: "partial", kind: "backup", offset: null, job: status.last_success?.job_id ?? null }) };
  if (code === "overdue" || code === "last_failed" || code === "never_succeeded") return { label: t("problemAction.failed"), run: () => navigate({ tab: "history", state: "failed", kind: "backup", offset: null }) };
  if (code === "verify_failed" || code === "verify_overdue") {
    const jobId = status.last_success?.job_id;
    if (isOwner && jobId && !actions.busy) return { label: t("actions.verifyNow"), run: () => void actions.verifyJob(jobId) };
    return { label: t("problemAction.history"), run: () => navigate({ tab: "history", state: null, kind: "verify", offset: null }) };
  }
  if (code === "restore_test_failed" || code === "restore_test_overdue") {
    if (isOwner && !actions.busy) return { label: t("actions.restoreTest"), run: () => void actions.startRestoreTest() };
    return { label: t("problemAction.history"), run: () => navigate({ tab: "history", state: null, kind: "restore_test", offset: null }) };
  }
  return null;
}

export function Overview({ t, locale, status, settings, isOwner, onChanged, navigate, actions }: {
  t: TFunc; locale: string; status: BackupStatus; settings: BackupSettings; isOwner: boolean; onChanged: () => Promise<void>;
  navigate: BackupNavigate; actions: BackupActions;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(id);
  }, []);
  const running = status.current_job !== null;
  const hero: HeroState = status.overall === "ok" && running ? "running" : status.overall;
  const last = status.last_success;
  return (
    <div className="backup-overview">
      <Hero t={t} locale={locale} status={status} hero={hero} now={now} />
      {status.problems.length ? (
        <section className="card backup-problems" aria-label={t("overview.problemsLabel")}>
          <ul className="backup-problem-list">
            {status.problems.map((problem) => {
              const action = problemAction(t, problem, navigate, status, isOwner, actions);
              return (
                <li key={problem.code} className={`backup-problem backup-problem-${problem.severity}`}>
                  <div className="backup-problem-text">
                    <strong>{t.has(`problemTitle.${problem.code}`) ? t(`problemTitle.${problem.code}`) : problem.code}</strong>
                    <span className="muted">{t.has(`problems.${problem.code}`) ? t(`problems.${problem.code}`, problem.params as Record<string, string | number>) : ""}</span>
                  </div>
                  <Badge variant={SEVERITY_VARIANT[problem.severity]}>{t(`severity.${problem.severity}`)}</Badge>
                  {action ? <button type="button" className="button-secondary" onClick={action.run}>{action.label}</button> : null}
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {status.current_job ? <JobPanel t={t} locale={locale} job={status.current_job} isOwner={isOwner} onChanged={onChanged} /> : null}
      {status.current_restore ? <RestorePanel t={t} locale={locale} restoreId={status.current_restore.id} isOwner={isOwner} onChanged={onChanged} /> : null}

      {/* Ohne eingerichtetes Backup-System gibt es nichts nachzuweisen - nur Hero, Banner und Infrastruktur. */}
      {status.enabled ? (<>
      <section className="backup-levels-section" aria-labelledby="backup-levels-title">
        <div className="backup-section-head">
          <h2 id="backup-levels-title" className="backup-section-title">{t("levels.title")}</h2>
          <p className="muted">{t("levels.description")}</p>
        </div>
        <div className="backup-levels">
          <LevelCard t={t} locale={locale} n={1} title={t("levels.created")} at={last?.snapshot_at ?? null} archive={last?.archive_name ?? null}
            intervalMs={settings.interval_hours * 3_600_000} now={now} intervalLabel={t("levels.intervalHours", { hours: settings.interval_hours })}
            when={last ? t("levels.whenDuration", { time: formatDateTime(last.snapshot_at, locale), duration: durationText(t, last.duration_seconds) }) : null}
            nextLabel={status.next_backup_at ? t("levels.next", { time: formatTime(status.next_backup_at, locale) }) : null}
            badge={!last ? { label: t("levels.badge.never"), variant: "danger" } : status.problems.some((p) => p.code === "overdue" && p.severity === "critical")
              ? { label: t("levels.badge.overdue"), variant: "danger" } : status.problems.some((p) => p.code === "partial")
                ? { label: t("levels.badge.incomplete"), variant: "warning" } : { label: t("levels.badge.current"), variant: "success" }}
            heavy={false}
          />
          <LevelCard t={t} locale={locale} n={2} title={t("levels.verified")} at={status.last_verified_at} archive={status.last_verified_archive}
            intervalMs={settings.verify_interval_hours * 3_600_000} now={now} intervalLabel={t("levels.intervalDays", { days: Math.round(settings.verify_interval_hours / 24 * 10) / 10 })}
            when={status.last_verified_at ? formatDateTime(status.last_verified_at, locale) : null}
            heavy
            action={isOwner && last?.job_id ? { label: t("actions.verifyNow"), run: () => void actions.verifyJob(last.job_id as string), disabled: actions.busy !== null || !status.enabled } : null}
          />
          <LevelCard t={t} locale={locale} n={3} title={t("levels.restoreTested")} at={status.last_restore_test_at} archive={status.last_restore_test_archive}
            intervalMs={settings.restore_test_interval_days * 86_400_000} now={now} intervalLabel={t("levels.intervalDays", { days: settings.restore_test_interval_days })}
            when={status.last_restore_test_at ? formatDateTime(status.last_restore_test_at, locale) : null}
            heavy
            action={isOwner ? { label: t("actions.startTest"), run: () => void actions.startRestoreTest(), disabled: actions.busy !== null || !status.enabled || running } : null}
          />
        </div>
      </section>

      <Timeline t={t} locale={locale} settings={settings} now={now} version={status.current_job?.state ?? "idle"} />

      <div className="backup-two-cards">
        <StorageCard t={t} status={status} />
        <InfraCard t={t} locale={locale} status={status} settings={settings} navigate={navigate} />
      </div>
      </>) : <InfraCard t={t} locale={locale} status={status} settings={settings} navigate={navigate} />}

      {status.last_failure && status.overall !== "ok" ? (
        <p className="muted">{t("overview.lastFailureLine", {
          time: formatDateTime(status.last_failure.finished_at ?? status.last_failure.created_at, locale),
          error: status.last_failure.error_code && t.has(`errors.${status.last_failure.error_code}`) ? t(`errors.${status.last_failure.error_code}`) : (status.last_failure.error_message ?? t("errors.unknown")),
        })}</p>
      ) : null}
    </div>
  );
}

function Hero({ t, locale, status, hero, now }: { t: TFunc; locale: string; status: BackupStatus; hero: HeroState; now: number }) {
  const last = status.last_success;
  const job = status.current_job;
  return (
    <section className={`card backup-hero backup-hero-${hero}`} aria-labelledby="backup-hero-title">
      <div className="backup-hero-main">
        <span className="backup-hero-icon" aria-hidden="true">
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d={hero === "ok" ? "M5 12.5l4.5 4.5L19 7.5" : hero === "running" ? "M20 12a8 8 0 01-14.3 4.9M4 12a8 8 0 0114.3-4.9M18.5 3v4.5H14M5.5 21v-4.5H10"
              : hero === "disabled" ? "M5 12h14" : "M12 8v5M12 16.5h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"} />
          </svg>
        </span>
        <div className="backup-hero-text">
          <span className="backup-kicker">{t("hero.kicker")} · <HealthBadge state={HERO_HEALTH[hero]} label={t(`hero.state.${hero}`)} /></span>
          <h2 id="backup-hero-title" className="backup-hero-title">{t(`hero.title.${hero}`)}</h2>
          <p className="muted">{hero === "ok" && last ? t("hero.text.ok", { age: ageText(t, last.snapshot_at, now) })
            : hero === "critical" && last ? t("hero.text.critical", { age: ageText(t, last.snapshot_at, now) })
              : t(`hero.text.${hero === "ok" || hero === "critical" ? `${hero}Never` : hero}`)}</p>
        </div>
      </div>
      <dl className="backup-hero-facts">
        <div>
          <dt>{hero === "critical" ? t("hero.lastSuccess") : t("hero.lastBackup")}</dt>
          <dd className="backup-hero-value">{last ? formatTime(last.snapshot_at, locale) : t("overview.never")}</dd>
          <dd className="muted">{last ? t("hero.lastSub", { age: ageText(t, last.snapshot_at, now), duration: durationText(t, last.duration_seconds) }) : "—"}</dd>
        </div>
        <div>
          <dt>{t("overview.nextBackup")}</dt>
          <dd className="backup-hero-value">{job ? t("hero.running") : status.next_backup_at ? formatTime(status.next_backup_at, locale) : "—"}</dd>
          <dd className="muted">{job ? t("hero.runningSub", { trigger: t(`trigger.${job.trigger}`), time: formatTime(job.started_at ?? job.created_at, locale) })
            : status.next_backup_at ? t("hero.nextSub", { in: untilText(t, status.next_backup_at, now) }) : t("hero.noSchedule")}</dd>
        </div>
        <div>
          <dt>{t("hero.points")}</dt>
          <dd className="backup-hero-value">{status.restore_point_count.toLocaleString(locale)}</dd>
          <dd className="muted">{t("hero.protected", { count: status.protected_count })}</dd>
        </div>
      </dl>
    </section>
  );
}

function formatDay(at: number, locale: string): string {
  return new Intl.DateTimeFormat(toIntlLocale(locale), { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "Europe/Zurich" }).format(at);
}

function dayLabels(day: string, locale: string): { weekday: string; date: string } {
  const at = new Date(`${day}T12:00:00Z`);
  return {
    weekday: new Intl.DateTimeFormat(toIntlLocale(locale), { weekday: "short", timeZone: "UTC" }).format(at),
    date: new Intl.DateTimeFormat(toIntlLocale(locale), { day: "2-digit", month: "2-digit", timeZone: "UTC" }).format(at),
  };
}

function LevelCard({ t, locale, n, title, at, archive, intervalMs, now, intervalLabel, when, badge, action, heavy, nextLabel }: {
  t: TFunc; locale: string; n: number; title: string; at: string | null; archive: string | null; intervalMs: number; now: number; intervalLabel: string;
  when: string | null; badge?: { label: string; variant: BadgeVariant }; action?: { label: string; run: () => void; disabled: boolean } | null; heavy: boolean;
  nextLabel?: string | null;
}) {
  const due = levelDue(at, intervalMs, now);
  const soon = !due.overdue && due.pct >= 80;
  const shown = badge ?? (!at ? { label: t("levels.badge.never"), variant: "danger" as const } : due.overdue ? { label: t("levels.badge.due"), variant: "danger" as const }
    : soon ? { label: t("levels.badge.soon"), variant: "warning" as const } : { label: t("levels.badge.current"), variant: "success" as const });
  // Prüfung und Restore-Test laufen nur im nächtlichen Wartungsfenster (BACKUP_HEAVY_WINDOW_HOURS).
  const dueText = nextLabel ?? (due.overdue || !due.dueAt ? (heavy ? t("levels.dueWindow") : t("levels.dueNow"))
    : heavy && soon ? t("levels.dueWindowFrom", { date: formatDay(due.dueAt, locale) }) : t("levels.dueAt", { date: formatDay(due.dueAt, locale) }));
  return (
    <article className="card backup-level">
      <div className="backup-level-head">
        <span className="backup-level-title"><span className="backup-level-n" aria-hidden="true">{n}</span>{title}</span>
        <Badge variant={shown.variant}>{shown.label}</Badge>
      </div>
      <div>
        <div className="backup-level-age">{at ? ageText(t, at, now) : t("levels.never")}</div>
        <div className="muted backup-small">{when ?? "—"}</div>
      </div>
      <div className="backup-level-meter-block">
        <div className="backup-meter" role="meter" aria-label={t("levels.meterLabel", { title })} aria-valuemin={0} aria-valuemax={100} aria-valuenow={due.pct}
          aria-valuetext={t("levels.meterText", { percent: due.pct })}>
          <span className={`backup-meter-fill backup-meter-${shown.variant}`} style={{ width: `${Math.max(2, due.pct)}%` }} />
        </div>
        <div className="backup-level-due"><span>{intervalLabel}</span><span className={due.overdue ? "backup-text-danger" : soon ? "backup-text-warning" : ""}>{dueText}</span></div>
      </div>
      <div className="backup-level-foot">
        <span className="backup-mono-ellipsis" title={archive ?? undefined}>{archive ?? "—"}</span>
        {action ? <button type="button" className="button-secondary" disabled={action.disabled} onClick={action.run}>{action.label}</button> : null}
      </div>
    </article>
  );
}

const SLOT_LABEL: Record<SlotState, string> = { ok: "slot.ok", partial: "slot.partial", failed: "slot.failed", running: "slot.running", missed: "slot.missed", planned: "slot.planned" };

function Timeline({ t, locale, settings, now, version }: { t: TFunc; locale: string; settings: BackupSettings; now: number; version: string }) {
  const [jobs, setJobs] = useState<BackupJobPage["items"] | null>(null);
  const summaryId = useId();
  useEffect(() => {
    const since = new Date(Date.now() - 8 * 86_400_000).toISOString();
    let alive = true;
    browserApiFetch<BackupJobPage>(`/api/admin/backups?since=${encodeURIComponent(since)}&limit=200`)
      .then((page) => { if (alive) setJobs(page.items); })
      .catch(() => { if (alive) setJobs([]); });
    return () => { alive = false; };
  }, [version]);
  const days: TimelineDay[] = useMemo(() => buildTimeline(jobs ?? [], settings, now), [jobs, settings, now]);
  const total = days.reduce((sum, day) => sum + day.slots.filter((slot) => slot.state !== "planned").length, 0);
  const bad = days.reduce((sum, day) => sum + day.counts.failed + day.counts.missed, 0);
  const partial = days.reduce((sum, day) => sum + day.counts.partial, 0);
  const summaryText = t("timeline.summary", { total, bad, partial });
  return (
    <section className="card backup-timeline" aria-labelledby="backup-timeline-title">
      <div className="backup-timeline-head">
        <h2 id="backup-timeline-title" className="backup-section-title">{t("timeline.title")}</h2>
        <ul className="backup-legend" aria-label={t("timeline.legend")}>
          {(["ok", "partial", "failed", "missed", "planned"] as SlotState[]).map((state) => (
            <li key={state}><span className={`backup-slot backup-slot-${state} backup-legend-swatch`} aria-hidden="true" />{t(SLOT_LABEL[state])}</li>
          ))}
          <li><span className="backup-mark" aria-hidden="true" />{t("timeline.markLegend")}</li>
        </ul>
      </div>
      <p id={summaryId} className="visually-hidden">{summaryText}</p>
      {jobs === null ? <p className="muted">{t("timeline.loading")}</p> : (
        <div className="backup-days" aria-describedby={summaryId}>
          {days.map((day, index) => (
            <div key={day.day} className="backup-day">
              <div className="backup-day-head">
                <span className={index === days.length - 1 ? "backup-day-name backup-day-today" : "backup-day-name"}>{dayLabels(day.day, locale).weekday}</span>
                <span className="muted backup-small">{dayLabels(day.day, locale).date}</span>
              </div>
              {day.summary ? (
                <div className={`backup-slot backup-slot-${day.worst ?? "planned"} backup-day-summary`} role="img"
                  aria-label={t("timeline.daySummary", { ok: day.counts.ok, failed: day.counts.failed + day.counts.missed, partial: day.counts.partial })}>
                  <span>{t("timeline.dayCount", { ok: day.counts.ok, total: day.slots.length - day.counts.planned })}</span>
                </div>
              ) : day.slots.length ? (
                <div className="backup-day-slots" style={{ gridTemplateColumns: `repeat(${day.slots.length}, minmax(0, 1fr))` }}>
                  {day.slots.map((slot) => (
                    <span key={slot.at} role="img" className={`backup-slot backup-slot-${slot.state}`}
                      aria-label={t("timeline.slotLabel", { time: formatTime(new Date(slot.at).toISOString(), locale), state: t(SLOT_LABEL[slot.state]) })}
                      title={t("timeline.slotLabel", { time: formatTime(new Date(slot.at).toISOString(), locale), state: t(SLOT_LABEL[slot.state]) })} />
                  ))}
                </div>
              ) : <div className="backup-day-empty muted backup-small">{t("timeline.noSlots")}</div>}
              <div className="backup-day-marks">
                {day.marks.map((mark) => (
                  <span key={`${mark.kind}-${mark.at}`} className="backup-day-mark" title={t("timeline.markLabel", { kind: t(`timeline.mark.${mark.kind}`), time: formatTime(new Date(mark.at).toISOString(), locale), state: t(`state.${mark.state}`) })}>
                    <span className="backup-mark" aria-hidden="true" />{t(`timeline.markShort.${mark.kind}`)}
                    <span className="visually-hidden">{t("timeline.markLabel", { kind: t(`timeline.mark.${mark.kind}`), time: formatTime(new Date(mark.at).toISOString(), locale), state: t(`state.${mark.state}`) })}</span>
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
      <p className="muted backup-small">{settings.schedule_enabled ? t("timeline.schedule", { interval: settings.interval_hours }) : t("timeline.scheduleOff")}</p>
      {jobs !== null ? (
        <details className="storage-events">
          <summary>{t("timeline.asTable")}</summary>
          <div className="table-shell">
            <table className="data-table">
              <thead><tr><th scope="col">{t("timeline.colDay")}</th><th scope="col">{t("slot.ok")}</th><th scope="col">{t("slot.partial")}</th><th scope="col">{t("slot.failed")}</th><th scope="col">{t("slot.missed")}</th><th scope="col">{t("timeline.colMarks")}</th></tr></thead>
              <tbody>
                {days.map((day) => (
                  <tr key={day.day}>
                    <td>{formatWeekdayDate(day.day, locale)}</td>
                    <td>{day.counts.ok}</td><td>{day.counts.partial}</td><td>{day.counts.failed}</td><td>{day.counts.missed}</td>
                    <td>{day.marks.map((mark) => t(`timeline.mark.${mark.kind}`)).join(", ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}
    </section>
  );
}

function StorageCard({ t, status }: { t: TFunc; status: BackupStatus }) {
  const repo = status.repository;
  const used = repo.used_percent;
  const savings = savingsPercent(repo.original_bytes, repo.stored_bytes);
  const files = status.latest_object_bytes ?? 0;
  const db = status.latest_db_bytes ?? 0;
  const total = Math.max(files + db, 1);
  return (
    <section className="card backup-card" aria-labelledby="backup-storage-title">
      <div className="backup-card-head">
        <h2 id="backup-storage-title" className="backup-section-title">{t("storage.title")}</h2>
        <span className="muted backup-small">{t("hero.pointsLine", { count: status.restore_point_count, protected: status.protected_count })}</span>
      </div>
      <div className="backup-stack">
        <div className="backup-row-between">
          <span className="muted">{t("storage.used")}</span>
          <span><strong className="backup-big">{repo.stored_bytes !== null ? formatFileSize(repo.stored_bytes) : "—"}</strong>{" "}
            {repo.quota_bytes ? <span className="muted backup-small">{t("storage.ofQuota", { quota: formatFileSize(repo.quota_bytes) })}</span> : null}</span>
        </div>
        {used !== null ? (
          <div className="backup-meter backup-meter-lg" role="meter" aria-label={t("storage.used")} aria-valuemin={0} aria-valuemax={100} aria-valuenow={used}>
            <span className={`backup-meter-fill ${used >= 95 ? "backup-meter-danger" : used >= 85 ? "backup-meter-warning" : "backup-meter-accent"}`} style={{ width: `${Math.max(1, used)}%` }} />
          </div>
        ) : null}
        <span className="muted backup-small">{used !== null ? t("storage.usedPercent", { percent: used }) : t("overview.quotaUnknown")}</span>
      </div>
      <div className="backup-stack">
        <span className="backup-label">{t("storage.dedupTitle")}</span>
        <div className="backup-dedup">
          <div className="backup-dedup-box">
            <span className="muted backup-small">{t("storage.allPoints")}</span>
            <strong>{repo.original_bytes !== null ? formatFileSize(repo.original_bytes) : "—"}</strong>
          </div>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true" className="backup-dedup-arrow"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
          <div className="backup-dedup-box backup-dedup-result">
            <span className="backup-small">{t("storage.actual")}</span>
            <strong>{repo.stored_bytes !== null ? formatFileSize(repo.stored_bytes) : "—"} {savings !== null ? <span className="backup-text-success backup-small">{t("storage.savings", { percent: savings })}</span> : null}</strong>
          </div>
        </div>
        <span className="muted backup-small">{t("storage.dedupHelp")}</span>
      </div>
      <div className="backup-stack backup-divided">
        <span className="backup-label">{t("storage.lastPoint")}</span>
        <div className="backup-split" aria-hidden="true">
          <span className="backup-split-files" style={{ width: `${(files / total) * 100}%` }} />
          <span className="backup-split-db" style={{ width: `${Math.max((db / total) * 100, db ? 0.6 : 0)}%` }} />
        </div>
        <div className="backup-split-legend">
          <span><span className="backup-swatch backup-split-files" aria-hidden="true" />{t("storage.files")} <strong>{status.latest_object_bytes !== null ? formatFileSize(files) : "—"}</strong>
            {status.last_success ? <span className="muted"> · {t("storage.objects", { count: status.last_success.object_count })}</span> : null}</span>
          <span><span className="backup-swatch backup-split-db" aria-hidden="true" />{t("storage.database")} <strong>{status.latest_db_bytes !== null ? formatFileSize(db) : "—"}</strong></span>
        </div>
      </div>
    </section>
  );
}

type InfraRow = { key: string; label: string; sub: string; state: string; variant: BadgeVariant };

function InfraCard({ t, locale, status, settings, navigate }: { t: TFunc; locale: string; status: BackupStatus; settings: BackupSettings; navigate: BackupNavigate }) {
  const repo = status.repository;
  const config = settings.worker_config;
  const running = status.current_job !== null || status.current_restore !== null;
  const rows: InfraRow[] = [
    { key: "box", label: t("infra.box"), sub: repo.checked_at ? t("repository.checkedAt", { time: formatDateTime(repo.checked_at, locale) }) : t("repository.unknown"),
      state: repo.ok ? t("repository.reachable") : repo.ok === false ? t("repository.unreachable") : t("repository.unknown"), variant: repo.ok ? "success" : repo.ok === false ? "danger" : "neutral" },
    { key: "worker", label: t("overview.worker"), sub: status.worker_heartbeat_at ? t("infra.lastSignal", { time: formatDateTime(status.worker_heartbeat_at, locale) }) : "—",
      state: !status.worker_alive ? t("overview.workerDown") : running ? t("infra.working") : t("overview.workerAlive"), variant: !status.worker_alive ? "danger" : running ? "info" : "success" },
    { key: "encryption", label: t("settings.encryption"), sub: repo.encryption ? t("infra.encryptionSub", { mode: repo.encryption }) : "—",
      state: repo.encryption && repo.encryption !== "none" ? t("infra.active") : t("repository.unknown"), variant: repo.encryption && repo.encryption !== "none" ? "success" : "neutral" },
    { key: "pin", label: t("infra.pinned"), sub: t("infra.pinnedSub"),
      state: config.repository_id_pinned && config.host_key_pinned ? t("settings.pinned") : t("settings.notPinned"), variant: config.repository_id_pinned && config.host_key_pinned ? "success" : "warning" },
    { key: "maintenance", label: t("settings.maintenanceKey"), sub: config.maintenance_key_present ? t("settings.maintenanceKeyPresent") : t("settings.maintenanceKeyAbsent"),
      state: config.maintenance_key_present ? t("infra.onServer") : t("infra.offline"), variant: config.maintenance_key_present ? "warning" : "success" },
    { key: "ntfy", label: t("settings.ntfy"), sub: t(`infra.notify.${settings.success_notification}`),
      state: settings.ntfy_configured ? t("infra.configured") : t("infra.missing"), variant: settings.ntfy_configured ? "success" : "warning" },
  ];
  return (
    <section className="card backup-card" aria-labelledby="backup-infra-title">
      <div className="backup-card-head">
        <h2 id="backup-infra-title" className="backup-section-title">{t("infra.title")}</h2>
        <button type="button" className="button-ghost" onClick={() => navigate({ tab: "settings" })}>{t("infra.showConnection")}</button>
      </div>
      <ul className="backup-infra">
        {rows.map((row) => (
          <li key={row.key}>
            <div className="backup-infra-text"><strong>{row.label}</strong><span className="muted backup-small">{row.sub}</span></div>
            <Badge variant={row.variant} dot>{row.state}</Badge>
          </li>
        ))}
      </ul>
    </section>
  );
}
