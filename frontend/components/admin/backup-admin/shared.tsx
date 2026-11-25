"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { useVisibleInterval } from "@/lib/hooks/use-visible-interval";
import { formatDateTime, formatFileSize, formatTime } from "@/lib/utils/format";
import type { BackupEvent, BackupJob, BackupJobState, BackupSet, RestoreJob, RestoreJobState } from "@/types/api";

import { num } from "./backup-utils";

export type TFunc = ReturnType<typeof useTranslations>;

export const ACTIVE_POLL_MS = 4_000;
export const IDLE_POLL_MS = 30_000;

export const JOB_VARIANTS: Record<BackupJobState, BadgeVariant> = {
  queued: "neutral", preparing: "info", running: "info", verifying: "info", completed: "success", partial: "warning",
  failed: "danger", cancelled: "neutral", interrupted: "danger",
};
export const RESTORE_VARIANTS: Record<RestoreJobState, BadgeVariant> = {
  queued: "neutral", preparing: "info", running: "info", verifying: "info", cutover: "warning", completed: "success",
  failed: "danger", cancelled: "neutral", interrupted: "danger", rolled_back: "warning",
};
export const OPEN_RESTORE: RestoreJobState[] = ["queued", "preparing", "running", "verifying", "cutover"];

export function durationText(t: TFunc, seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 90) return t("duration.seconds", { seconds: Math.max(0, Math.round(seconds)) });
  const minutes = Math.round(seconds / 60);
  if (minutes < 120) return t("duration.minutes", { minutes });
  return t("duration.hours", { hours: Math.round(minutes / 6) / 10 });
}

/** Alter als «vor 3 h 12 min» / «vor 6 Tagen». */
export function ageText(t: TFunc, iso: string | null | undefined, now: number): string {
  if (!iso) return "—";
  const minutes = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60_000));
  if (minutes < 60) return t("age.minutes", { minutes });
  if (minutes < 48 * 60) return t("age.hours", { hours: Math.floor(minutes / 60), minutes: minutes % 60 });
  return t("age.days", { days: Math.floor(minutes / 1440) });
}

/** Restzeit bis zu einem Zeitpunkt als «2 h 27 min» / «3 Tagen». */
export function untilText(t: TFunc, iso: string, now: number): string {
  const minutes = Math.max(0, Math.round((new Date(iso).getTime() - now) / 60_000));
  if (minutes < 60) return t("until.minutes", { minutes });
  if (minutes < 48 * 60) return t("until.hours", { hours: Math.floor(minutes / 60), minutes: minutes % 60 });
  return t("until.days", { days: Math.floor(minutes / 1440) });
}

/** Übersetzter Fehler. Rohmeldungen bekommt nur Owner (Support: API liefert nur den Code). */
export function errorText(t: TFunc, code: string | null, message: string | null): string {
  if (code && t.has(`errors.${code}`)) return t(`errors.${code}`);
  return message ?? t("errors.unknown");
}

export function phaseText(t: TFunc, phase: unknown): string | null {
  if (typeof phase !== "string" || !phase) return null;
  return t.has(`phase.${phase}`) ? t(`phase.${phase}`) : phase;
}

export function eventLabel(t: TFunc, kind: string): string {
  return t.has(`event.${kind}`) ? t(`event.${kind}`) : kind;
}

/** Ein Idempotenzschlüssel je geöffneter Bestätigung: eine Wiederholung (z. B. nach einem
 * Netzwerkfehler) schickt denselben Schlüssel, der Server liefert dann den laufenden Auftrag. */
export function useIdempotencyKey() {
  const ref = useRef<string | null>(null);
  const get = useCallback((prefix: string) => {
    ref.current ??= `${prefix}-${crypto.randomUUID()}`;
    return ref.current;
  }, []);
  const reset = useCallback(() => {
    ref.current = null;
  }, []);
  return { get, reset };
}

/** Nachweis-Badges eines Sicherungspunkts (Ungeprüft / Geprüft / Restore getestet). */
export function VerificationBadges({ t, set, verifying = false }: { t: TFunc; set: BackupSet; verifying?: boolean }) {
  if (verifying) return <div className="backup-badges"><Badge variant="info" dot>{t("history.verifying")}</Badge></div>;
  return (
    <div className="backup-badges">
      <Badge variant={set.verify_state === "verified" ? "success" : set.verify_state === "failed" ? "danger" : "neutral"}>{t(`verify.${set.verify_state}`)}</Badge>
      {set.restore_test_state !== "untested" ? <Badge variant={set.restore_test_state === "passed" ? "success" : "danger"}>{t(`restoreTest.${set.restore_test_state}`)}</Badge> : null}
    </div>
  );
}

/** Ereignisse als Zeitleiste (Detail-Schublade, laufende Wiederherstellung). */
export function EventTimeline({ t, locale, events }: { t: TFunc; locale: string; events: BackupEvent[] }) {
  if (!events.length) return <p className="muted">{t("events.empty")}</p>;
  const ordered = [...events].sort((a, b) => a.id - b.id);
  return (
    <ol className="backup-events" aria-label={t("events.title", { count: events.length })}>
      {ordered.map((event) => (
        <li key={event.id} className={`backup-event backup-event-${event.level === "error" ? "error" : event.level === "warning" ? "warning" : "info"}`}>
          <span className="backup-event-dot" aria-hidden="true" />
          <div className="backup-event-body">
            <span>
              <strong>{eventLabel(t, event.kind)}</strong>
              {event.level === "error" || event.level === "warning" ? <span className="visually-hidden"> ({t(`eventLevel.${event.level}`)})</span> : null}
              {event.message ? <span className="muted"> {event.message}</span> : null}
            </span>
            <span className="backup-event-meta">
              <time dateTime={event.created_at} title={formatDateTime(event.created_at, locale)}>{formatTime(event.created_at, locale)}</time>
              {" · "}{event.actor_email ?? t("events.worker")}
            </span>
          </div>
        </li>
      ))}
    </ol>
  );
}

const JOB_STEPS: BackupJobState[] = ["queued", "preparing", "running", "verifying", "completed"];

/** Laufender Auftrag: Schrittleiste, Fortschritt, Abbrechen (Owner). */
export function JobPanel({ t, locale, job, isOwner, onChanged }: { t: TFunc; locale: string; job: BackupJob; isOwner: boolean; onChanged: () => Promise<void> }) {
  const confirm = useConfirm();
  const showToast = useToast();
  const progress = job.progress ?? {};
  const total = num(progress.objects_total);
  const done = num(progress.objects_done);
  const current = Math.max(0, JOB_STEPS.indexOf(job.state));
  async function cancel() {
    if (!(await confirm({ message: t("confirm.cancelJob"), tone: "danger", confirmLabel: t("actions.cancel") }))) return;
    try {
      await browserApiFetch(`/api/admin/backups/${job.id}/cancel`, { method: "POST" });
      showToast(t("toast.cancelRequested"), "success");
      await onChanged();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    }
  }
  const phase = phaseText(t, progress.phase);
  return (
    <section className="card backup-job" aria-live="polite" aria-labelledby={`backup-job-${job.id}`}>
      <div className="backup-job-head">
        <div className="backup-job-title">
          <h2 id={`backup-job-${job.id}`} className="backup-section-title"><span className="backup-pulse" aria-hidden="true" />{t("job.runningTitle", { kind: t(`kind.${job.kind}`) })}</h2>
          <span className="muted">
            {t("job.startedBy", { trigger: t(`trigger.${job.trigger}`), time: formatDateTime(job.started_at ?? job.created_at, locale) })}
            {job.requested_by_email ? ` · ${job.requested_by_email}` : ""}
            {phase ? ` · ${t("job.phase", { phase })}` : ""}
          </span>
        </div>
        {isOwner && !job.cancel_requested ? <button type="button" className="button-danger" onClick={() => void cancel()}>{t("actions.cancel")}</button> : null}
      </div>
      <ol className="backup-job-steps" aria-label={t("job.stepsLabel")}>
        {JOB_STEPS.map((step, index) => (
          <li key={step} className={index < current ? "backup-job-step backup-job-step-done" : index === current ? "backup-job-step backup-job-step-current" : "backup-job-step"}
            aria-current={index === current ? "step" : undefined}>
            <span className="backup-job-step-bar" aria-hidden="true" />
            <span>{t(`state.${step}`)}</span>
          </li>
        ))}
      </ol>
      {progress.waiting_for ? <StatusBanner tone="neutral" message={t.has(`waiting.${progress.waiting_for}`) ? t(`waiting.${progress.waiting_for}`) : String(progress.waiting_for)} /> : null}
      {total > 0 ? (
        <div className="storage-progress-block">
          <div className="backup-progress-line"><span>{t("job.objectsProgress", { done, total })}</span><span className="muted">{t("job.percent", { percent: Math.round((done / Math.max(total, 1)) * 100) })}</span></div>
          <progress className="storage-progress" max={Math.max(total, 1)} value={done} aria-label={t("job.progressAria")} />
          <span className="muted">{t("job.newData", { count: num(progress.new_objects), size: formatFileSize(num(progress.new_bytes)) })}</span>
        </div>
      ) : null}
      {!job.worker_active && job.state !== "queued" ? <StatusBanner tone="neutral" message={t("job.workerIdle")} /> : null}
    </section>
  );
}

/** Laufende oder gewählte Wiederherstellung (bleibt aus der bisherigen Seite erhalten). */
export function RestorePanel({ t, locale, restoreId, isOwner, onChanged }: { t: TFunc; locale: string; restoreId: string; isOwner: boolean; onChanged: () => Promise<void> }) {
  const confirm = useConfirm();
  const showToast = useToast();
  const [job, setJob] = useState<RestoreJob | null>(null);
  const open = job === null || OPEN_RESTORE.includes(job.state);

  const load = useCallback(async () => {
    try {
      setJob(await browserApiFetch<RestoreJob>(`/api/admin/restores/${restoreId}`));
    } catch {
      // Während des Datenbanktauschs ist die API kurz nicht erreichbar - weiter versuchen.
    }
  }, [restoreId]);

  useEffect(() => {
    void load();
  }, [load]);
  useVisibleInterval(() => void load(), open ? ACTIVE_POLL_MS : null);

  useEffect(() => {
    if (job && !OPEN_RESTORE.includes(job.state)) void onChanged();
  }, [job, onChanged]);

  if (job === null) return null;
  const progress = job.progress ?? {};
  const result = (job.result ?? {}) as Record<string, unknown>;
  async function cancel() {
    if (!(await confirm({ message: t("confirm.cancelRestore"), tone: "danger", confirmLabel: t("actions.cancel") }))) return;
    try {
      await browserApiFetch(`/api/admin/restores/${restoreId}/cancel`, { method: "POST" });
      await load();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    }
  }
  return (
    <section className="card backup-job" aria-live="polite" aria-labelledby={`backup-restore-${job.id}`}>
      <div className="backup-job-head">
        <div className="backup-job-title">
          <h2 id={`backup-restore-${job.id}`} className="backup-section-title">
            {OPEN_RESTORE.includes(job.state) ? <span className="backup-pulse" aria-hidden="true" /> : null}
            {t(`restore.panelTitle.${job.kind}`)}
          </h2>
          <span className="muted backup-mono-wrap">{t("restore.panelDescription", { archive: job.archive_name, time: formatDateTime(job.created_at, locale) })}</span>
        </div>
        <Badge variant={RESTORE_VARIANTS[job.state]} dot>{t(`restoreState.${job.state}`)}</Badge>
      </div>
      {job.state === "cutover" ? <StatusBanner tone="neutral" message={t("restore.cutoverHint")} /> : null}
      {phaseText(t, progress.phase) ? <p className="muted">{t("job.phase", { phase: phaseText(t, progress.phase) ?? "" })}</p> : null}
      {progress.waiting_for ? <StatusBanner tone="neutral" message={t.has(`waiting.${progress.waiting_for}`) ? t(`waiting.${progress.waiting_for}`) : String(progress.waiting_for)} /> : null}
      {num(progress.objects_total) > 0 ? (
        <div className="storage-progress-block">
          <span>{t("restore.contentsProgress", { done: num(progress.contents_restored), size: formatFileSize(num(progress.bytes_restored)) })}</span>
          <progress className="storage-progress" max={Math.max(num(progress.objects_total), 1)} value={num(progress.contents_restored)} aria-label={t("job.progressAria")} />
        </div>
      ) : null}
      {job.state === "completed" && job.kind === "tenant_copy" ? (
        <StatusBanner tone="success" message={t("restore.tenantDone", { name: String(result.tenant_name ?? ""), files: Number(result.files_imported ?? 0) })} />
      ) : null}
      {job.state === "completed" && job.kind === "full" ? (
        <StatusBanner tone="success" message={t("restore.fullDone", { database: String(result.pre_restore_db ?? ""), generation: Number(result.generation ?? 0) })} />
      ) : null}
      {job.state === "rolled_back" ? <StatusBanner tone="error" message={t("restore.rolledBack")} /> : null}
      {(job.error_message || job.error_code) && job.state !== "rolled_back" && ["failed", "interrupted"].includes(job.state)
        ? <StatusBanner tone="error" message={errorText(t, job.error_code, job.error_message)} /> : null}
      {Array.isArray(result.warnings) && result.warnings.length ? (
        <details className="storage-events">
          <summary>{t("restore.importWarnings", { count: result.warnings.length })}</summary>
          <ul className="backup-list">{(result.warnings as string[]).map((warning, index) => <li key={index}>{warning}</li>)}</ul>
        </details>
      ) : null}
      {isOwner && ["queued", "preparing", "running", "verifying"].includes(job.state) && !job.cancel_requested ? (
        <div className="table-actions"><button type="button" className="button-danger" onClick={() => void cancel()}>{t("actions.cancel")}</button></div>
      ) : null}
      <details className="storage-events">
        <summary>{t("events.title", { count: job.events.length })}</summary>
        <EventTimeline t={t} locale={locale} events={job.events} />
      </details>
    </section>
  );
}
