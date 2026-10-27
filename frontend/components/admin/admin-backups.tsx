"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { ActionMenu } from "@/components/ui/action-menu";
import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { Pagination } from "@/components/ui/pagination";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { StatusBanner } from "@/components/ui/status-banner";
import { Tabs } from "@/components/ui/tabs";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateTime, formatFileSize } from "@/lib/utils/format";
import {
  BackupEvent,
  BackupJob,
  BackupJobDetail,
  BackupJobPage,
  BackupJobState,
  BackupSet,
  BackupSettings,
  BackupStatus,
  BackupTenant,
  RestoreJob,
  RestoreJobState,
  RestorePreview,
  StorageOverview,
} from "@/types/api";
import { Select } from "@/components/ui/select";

type TFunc = ReturnType<typeof useTranslations>;

const ACTIVE_POLL_MS = 4_000;
const IDLE_POLL_MS = 30_000;
const PAGE_SIZE = 25;

const JOB_VARIANTS: Record<BackupJobState, BadgeVariant> = {
  queued: "neutral", preparing: "info", running: "info", verifying: "info", completed: "success", partial: "warning",
  failed: "danger", cancelled: "neutral", interrupted: "danger",
};
const RESTORE_VARIANTS: Record<RestoreJobState, BadgeVariant> = {
  queued: "neutral", preparing: "info", running: "info", verifying: "info", cutover: "warning", completed: "success",
  failed: "danger", cancelled: "neutral", interrupted: "danger", rolled_back: "warning",
};
const OVERALL_VARIANTS: Record<BackupStatus["overall"], BadgeVariant> = { ok: "success", warning: "warning", critical: "danger", disabled: "neutral" };
const OPEN_RESTORE: RestoreJobState[] = ["queued", "preparing", "running", "verifying", "cutover"];

function durationText(t: TFunc, seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 90) return t("duration.seconds", { seconds: Math.max(0, Math.round(seconds)) });
  const minutes = Math.round(seconds / 60);
  if (minutes < 120) return t("duration.minutes", { minutes });
  return t("duration.hours", { hours: Math.round(minutes / 6) / 10 });
}

function errorText(t: TFunc, code: string | null, message: string | null): string {
  if (code && t.has(`errors.${code}`)) return t(`errors.${code}`);
  return message ?? t("errors.unknown");
}

function phaseText(t: TFunc, phase: unknown): string | null {
  if (typeof phase !== "string" || !phase) return null;
  return t.has(`phase.${phase}`) ? t(`phase.${phase}`) : phase;
}

function num(value: unknown): number {
  return typeof value === "number" ? value : 0;
}

export function AdminBackups({ initialStatus, initialSettings, isOwner }: { initialStatus: BackupStatus; initialSettings: BackupSettings; isOwner: boolean }) {
  const t = useTranslations("adminBackups");
  const locale = useLocale();
  const showToast = useToast();
  const [status, setStatus] = useState(initialStatus);
  const [settings, setSettings] = useState(initialSettings);
  const [tab, setTab] = useState("overview");
  const [busy, setBusy] = useState<string | null>(null);
  const [historyVersion, setHistoryVersion] = useState(0);
  const loadingRef = useRef(false);

  const reload = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    try {
      setStatus(await browserApiFetch<BackupStatus>("/api/admin/backups/status"));
    } catch {
      // Letzten Stand weiter zeigen.
    } finally {
      loadingRef.current = false;
    }
  }, []);

  const active = status.current_job !== null || status.current_restore !== null;
  useEffect(() => {
    const interval = setInterval(() => void reload(), active ? ACTIVE_POLL_MS : IDLE_POLL_MS);
    return () => clearInterval(interval);
  }, [active, reload]);

  async function start(kind: "backup" | "restoreTest") {
    setBusy(kind);
    try {
      const path = kind === "backup" ? "/api/admin/backups" : "/api/admin/backups/restore-test";
      await browserApiFetch<BackupJob>(path, { method: "POST", body: JSON.stringify({ idempotency_key: `${kind}-${Date.now()}` }) });
      showToast(kind === "backup" ? t("toast.backupQueued") : t("toast.restoreTestQueued"), "success");
      await reload();
      setHistoryVersion((value) => value + 1);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="grid">
      <DataToolbar
        title={t("title")}
        description={t("description")}
        actions={isOwner ? (
          <>
            <button type="button" className="button-secondary" disabled={busy !== null || !status.enabled} onClick={() => void start("restoreTest")}>
              {t("actions.restoreTest")}
            </button>
            <button type="button" className="button-primary" disabled={busy !== null || !status.enabled} onClick={() => void start("backup")}>
              {t("actions.backupNow")}
            </button>
          </>
        ) : null}
      />
      {!status.enabled ? <StatusBanner tone="neutral" message={t("banner.disabled")} /> : null}
      {status.enabled && !status.worker_alive ? <StatusBanner tone="error" message={t("banner.workerDown")} /> : null}
      <Tabs
        activeId={tab}
        onChange={setTab}
        tabs={[
          { id: "overview", label: t("tabs.overview"), content: <Overview t={t} locale={locale} status={status} isOwner={isOwner} onChanged={reload} /> },
          { id: "history", label: t("tabs.history"), content: <History key={historyVersion} t={t} locale={locale} isOwner={isOwner} /> },
          { id: "restore", label: t("tabs.restore"), content: <Restore t={t} locale={locale} isOwner={isOwner} status={status} onChanged={reload} /> },
          { id: "settings", label: t("tabs.settings"), content: <Settings t={t} locale={locale} settings={settings} isOwner={isOwner} onSaved={setSettings} /> },
        ]}
      />
    </div>
  );
}

// --- Übersicht ---------------------------------------------------------------------------------

function Overview({ t, locale, status, isOwner, onChanged }: { t: TFunc; locale: string; status: BackupStatus; isOwner: boolean; onChanged: () => Promise<void> }) {
  const repo = status.repository;
  const last = status.last_success;
  return (
    <div className="grid">
      <div className="stats-kpi-row">
        <div className="stats-card">
          <span className="stats-card-label">{t("overview.overall")}</span>
          <span className="stats-card-value"><Badge variant={OVERALL_VARIANTS[status.overall]} dot>{t(`overall.${status.overall}`)}</Badge></span>
          <span className="stats-card-sub">{t("overview.problemCount", { count: status.problems.length })}</span>
        </div>
        <div className="stats-card">
          <span className="stats-card-label">{t("overview.lastSuccess")}</span>
          <span className="stats-card-value backup-kpi-text">{last ? formatDateTime(last.snapshot_at, locale) : t("overview.never")}</span>
          <span className="stats-card-sub">{last ? t("overview.duration", { duration: durationText(t, last.duration_seconds) }) : "—"}</span>
        </div>
        <div className="stats-card">
          <span className="stats-card-label">{t("overview.nextBackup")}</span>
          <span className="stats-card-value backup-kpi-text">{status.next_backup_at ? formatDateTime(status.next_backup_at, locale) : "—"}</span>
          <span className="stats-card-sub">{t("overview.restorePoints", { count: status.restore_point_count, protected: status.protected_count })}</span>
        </div>
        <div className="stats-card">
          <span className="stats-card-label">{t("overview.storage")}</span>
          <span className="stats-card-value backup-kpi-text">{repo.stored_bytes !== null ? formatFileSize(repo.stored_bytes) : "—"}</span>
          <span className="stats-card-sub">
            {repo.used_percent !== null && repo.quota_bytes ? t("overview.quota", { percent: repo.used_percent, quota: formatFileSize(repo.quota_bytes) }) : t("overview.quotaUnknown")}
          </span>
        </div>
      </div>

      {status.problems.map((problem) => (
        <StatusBanner key={problem.code} tone={problem.severity === "critical" ? "error" : "neutral"}
          message={t.has(`problems.${problem.code}`) ? t(`problems.${problem.code}`, problem.params as Record<string, string | number>) : problem.code} />
      ))}

      {status.current_job ? <JobPanel t={t} locale={locale} job={status.current_job} isOwner={isOwner} onChanged={onChanged} /> : null}
      {status.current_restore ? <RestorePanel t={t} locale={locale} restoreId={status.current_restore.id} isOwner={isOwner} onChanged={onChanged} /> : null}

      <article className="card">
        <DataToolbar title={t("overview.levelsTitle")} description={t("overview.levelsDescription")} />
        <dl className="storage-facts">
          <dt>{t("overview.created")}</dt>
          <dd>{last ? <><Badge variant="success">{t("level.created")}</Badge> {formatDateTime(last.snapshot_at, locale)} · {last.archive_name}</> : <span className="muted">{t("overview.never")}</span>}</dd>
          <dt>{t("overview.verified")}</dt>
          <dd>{status.last_verified_at ? <><Badge variant="success">{t("level.verified")}</Badge> {formatDateTime(status.last_verified_at, locale)} · {status.last_verified_archive}</> : <span className="muted">{t("overview.neverVerified")}</span>}</dd>
          <dt>{t("overview.restoreTested")}</dt>
          <dd>{status.last_restore_test_at ? <><Badge variant="success">{t("level.restoreTested")}</Badge> {formatDateTime(status.last_restore_test_at, locale)} · {status.last_restore_test_archive}</> : <span className="muted">{t("overview.neverTested")}</span>}</dd>
        </dl>
      </article>

      <article className="card">
        <DataToolbar title={t("overview.dataTitle")} />
        <dl className="storage-facts">
          <dt>{t("overview.latestObjects")}</dt><dd>{status.latest_object_bytes !== null ? formatFileSize(status.latest_object_bytes) : "—"}</dd>
          <dt>{t("overview.latestDatabase")}</dt><dd>{status.latest_db_bytes !== null ? formatFileSize(status.latest_db_bytes) : "—"}</dd>
          <dt>{t("overview.repositoryOriginal")}</dt><dd>{repo.original_bytes !== null ? formatFileSize(repo.original_bytes) : "—"}</dd>
          <dt>{t("overview.repositoryStored")}</dt><dd>{repo.stored_bytes !== null ? formatFileSize(repo.stored_bytes) : "—"}</dd>
          <dt>{t("overview.repositoryState")}</dt>
          <dd>
            <Badge variant={repo.ok ? "success" : repo.ok === false ? "danger" : "neutral"}>{repo.ok ? t("repository.reachable") : repo.ok === false ? t("repository.unreachable") : t("repository.unknown")}</Badge>{" "}
            {repo.checked_at ? <span className="muted">{t("repository.checkedAt", { time: formatDateTime(repo.checked_at, locale) })}</span> : null}
          </dd>
          <dt>{t("overview.worker")}</dt>
          <dd>{status.worker_heartbeat_at ? formatDateTime(status.worker_heartbeat_at, locale) : "—"} {status.worker_alive ? <Badge variant="success">{t("overview.workerAlive")}</Badge> : <Badge variant="danger">{t("overview.workerDown")}</Badge>}</dd>
        </dl>
      </article>

      {status.last_failure ? (
        <article className="card">
          <DataToolbar title={t("overview.lastFailure")} />
          <StatusBanner tone="error" message={t("overview.failureLine", {
            time: formatDateTime(status.last_failure.finished_at ?? status.last_failure.created_at, locale),
            error: errorText(t, status.last_failure.error_code, status.last_failure.error_message),
          })} />
        </article>
      ) : null}
    </div>
  );
}

function JobPanel({ t, locale, job, isOwner, onChanged }: { t: TFunc; locale: string; job: BackupJob; isOwner: boolean; onChanged: () => Promise<void> }) {
  const confirm = useConfirm();
  const showToast = useToast();
  const progress = job.progress ?? {};
  const total = num(progress.objects_total);
  const done = num(progress.objects_done);
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
  return (
    <article className="card storage-migration" aria-live="polite">
      <DataToolbar
        title={t("job.runningTitle", { kind: t(`kind.${job.kind}`) })}
        description={t("job.startedBy", { trigger: t(`trigger.${job.trigger}`), time: formatDateTime(job.started_at ?? job.created_at, locale) })}
        actions={<Badge variant={JOB_VARIANTS[job.state]} dot>{t(`state.${job.state}`)}</Badge>}
      />
      {phaseText(t, progress.phase) ? <p className="muted">{t("job.phase", { phase: phaseText(t, progress.phase) ?? "" })}</p> : null}
      {progress.waiting_for ? <StatusBanner tone="neutral" message={t.has(`waiting.${progress.waiting_for}`) ? t(`waiting.${progress.waiting_for}`) : String(progress.waiting_for)} /> : null}
      {total > 0 ? (
        <div className="storage-progress-block">
          <span>{t("job.objectsProgress", { done, total })}</span>
          <progress className="storage-progress" max={Math.max(total, 1)} value={done} aria-label={t("job.progressAria")} />
          <span className="muted">{t("job.newData", { count: num(progress.new_objects), size: formatFileSize(num(progress.new_bytes)) })}</span>
        </div>
      ) : null}
      {job.error_message ? <StatusBanner tone="error" message={errorText(t, job.error_code, job.error_message)} /> : null}
      {!job.worker_active && job.state !== "queued" ? <StatusBanner tone="neutral" message={t("job.workerIdle")} /> : null}
      {isOwner && !job.cancel_requested ? (
        <div className="table-actions"><button type="button" className="button-danger" onClick={() => void cancel()}>{t("actions.cancel")}</button></div>
      ) : null}
    </article>
  );
}

// --- Verlauf -----------------------------------------------------------------------------------

type HistoryFilter = "all" | "completed" | "partial" | "failed";

function History({ t, locale, isOwner }: { t: TFunc; locale: string; isOwner: boolean }) {
  const showToast = useToast();
  const [filter, setFilter] = useState<HistoryFilter>("all");
  const [kind, setKind] = useState<"backup" | "verify" | "restore_test" | "retention" | "">("backup");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<BackupJobPage | null>(null);
  const [detail, setDetail] = useState<BackupJobDetail | null>(null);

  const load = useCallback(async () => {
    const params = new URLSearchParams({ offset: String(offset), limit: String(PAGE_SIZE) });
    if (filter !== "all") params.set("state", filter);
    if (kind) params.set("kind", kind);
    try {
      setPage(await browserApiFetch<BackupJobPage>(`/api/admin/backups?${params.toString()}`));
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    }
  }, [filter, kind, offset, showToast, t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function openDetail(job: BackupJob) {
    try {
      setDetail(await browserApiFetch<BackupJobDetail>(`/api/admin/backups/${job.id}`));
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    }
  }

  async function verify(job: BackupJob) {
    try {
      await browserApiFetch(`/api/admin/backups/${job.id}/verify`, { method: "POST", body: JSON.stringify({ idempotency_key: `verify-${job.id}-${Date.now()}` }) });
      showToast(t("toast.verifyQueued"), "success");
      await load();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    }
  }

  return (
    <article className="card">
      <DataToolbar title={t("history.title")} description={t("history.description")} />
      <div className="list-filter-row">
        <FilterTabs<HistoryFilter>
          value={filter}
          onChange={(value) => { setFilter(value); setOffset(0); }}
          options={[
            { value: "all", label: t("history.filterAll") },
            { value: "completed", label: t("state.completed") },
            { value: "partial", label: t("state.partial") },
            { value: "failed", label: t("state.failed") },
          ]}
        />
        <Select className="input backup-kind-select" value={kind} aria-label={t("history.kind")} onChange={(event) => { setKind(event.target.value as typeof kind); setOffset(0); }}>
          <option value="">{t("history.allKinds")}</option>
          {(["backup", "verify", "restore_test", "retention"] as const).map((value) => <option key={value} value={value}>{t(`kind.${value}`)}</option>)}
        </Select>
      </div>
      <DataTable
        columns={[t("columns.time"), t("columns.id"), t("columns.kind"), t("columns.state"), t("columns.duration"), t("columns.database"), t("columns.objects"),
          t("columns.newData"), t("columns.stored"), t("columns.verification"), t("columns.error"), t("columns.actions")]}
        emptyMessage={t("history.empty")}
      >
        {(page?.items ?? []).map((job) => {
          const set = job.backup_set;
          return (
            <tr key={job.id}>
              <td>{formatDateTime(set?.snapshot_at ?? job.created_at, locale)}</td>
              <td className="muted backup-id" title={set?.archive_name ?? job.id}>{job.id.slice(0, 8)}</td>
              <td>{t(`kind.${job.kind}`)}<div className="muted">{t(`trigger.${job.trigger}`)}</div></td>
              <td>
                <div className="storage-badges">
                  <Badge variant={JOB_VARIANTS[job.state]}>{t(`state.${job.state}`)}</Badge>
                  {set?.protected ? <Badge variant="info">{t("history.protected")}</Badge> : null}
                </div>
              </td>
              <td>{durationText(t, job.duration_seconds)}</td>
              <td>{set?.db_dump_bytes ? formatFileSize(set.db_dump_bytes) : "—"}</td>
              <td>{set ? set.object_count.toLocaleString(locale) : "—"}</td>
              <td>{set ? t("history.newData", { count: set.new_object_count, size: formatFileSize(set.new_object_bytes) }) : "—"}</td>
              <td>{set?.deduplicated_bytes !== null && set?.deduplicated_bytes !== undefined ? formatFileSize(set.deduplicated_bytes) : "—"}</td>
              <td>{set ? <VerificationBadges t={t} set={set} /> : "—"}</td>
              <td className="backup-error-cell">{job.state === "failed" || job.state === "interrupted" || job.state === "partial"
                ? (job.state === "partial" ? t("history.partialDetail", { count: Number(set?.warnings.find((w) => w.code === "missing_objects")?.count ?? 0) }) : errorText(t, job.error_code, job.error_message))
                : ""}</td>
              <td>
                <ActionMenu items={[
                  { label: t("actions.details"), onClick: () => void openDetail(job) },
                  ...(isOwner && set && job.kind === "backup" ? [{ label: t("actions.verify"), onClick: () => void verify(job) }] : []),
                ]} />
              </td>
            </tr>
          );
        })}
      </DataTable>
      {page ? <Pagination offset={page.offset} limit={page.limit} total={page.total} onOffsetChange={setOffset} /> : null}
      {detail ? <JobDetailModal t={t} locale={locale} detail={detail} onClose={() => setDetail(null)} /> : null}
    </article>
  );
}

function VerificationBadges({ t, set }: { t: TFunc; set: BackupSet }) {
  return (
    <div className="storage-badges">
      <Badge variant={set.verify_state === "verified" ? "success" : set.verify_state === "failed" ? "danger" : "neutral"}>{t(`verify.${set.verify_state}`)}</Badge>
      {set.restore_test_state !== "untested" ? <Badge variant={set.restore_test_state === "passed" ? "success" : "danger"}>{t(`restoreTest.${set.restore_test_state}`)}</Badge> : null}
    </div>
  );
}

function EventsTable({ t, locale, events }: { t: TFunc; locale: string; events: BackupEvent[] }) {
  return (
    <details className="storage-events">
      <summary>{t("events.title", { count: events.length })}</summary>
      <DataTable columns={[t("columns.time"), t("columns.event"), t("columns.actor")]} emptyMessage={t("events.empty")}>
        {events.map((event) => (
          <tr key={event.id}>
            <td>{formatDateTime(event.created_at, locale)}</td>
            <td><Badge variant={event.level === "error" ? "danger" : event.level === "warning" ? "warning" : "neutral"}>{t.has(`event.${event.kind}`) ? t(`event.${event.kind}`) : event.kind}</Badge> {event.message ?? ""}</td>
            <td className="muted">{event.actor_email ?? t("events.worker")}</td>
          </tr>
        ))}
      </DataTable>
    </details>
  );
}

function JobDetailModal({ t, locale, detail, onClose }: { t: TFunc; locale: string; detail: BackupJobDetail; onClose: () => void }) {
  const set = detail.backup_set;
  return (
    <Modal open title={t("detail.title", { kind: t(`kind.${detail.kind}`) })} onClose={onClose} size="wide">
      <div className="grid">
        <dl className="storage-facts">
          <dt>{t("detail.state")}</dt><dd><Badge variant={JOB_VARIANTS[detail.state]}>{t(`state.${detail.state}`)}</Badge></dd>
          <dt>{t("detail.created")}</dt><dd>{formatDateTime(detail.created_at, locale)}{detail.requested_by_email ? ` · ${detail.requested_by_email}` : ""}</dd>
          <dt>{t("detail.duration")}</dt><dd>{durationText(t, detail.duration_seconds)}</dd>
          {set ? (
            <>
              <dt>{t("detail.archive")}</dt><dd className="backup-id">{set.archive_name}</dd>
              <dt>{t("detail.snapshot")}</dt><dd>{formatDateTime(set.snapshot_at, locale)}</dd>
              <dt>{t("detail.version")}</dt><dd>{t("detail.versionValue", { app: set.app_version ?? "—", schema: set.alembic_revision ?? "—" })}</dd>
              <dt>{t("detail.storageSource")}</dt><dd>{t("detail.storageValue", { profile: set.profile_name ?? "—", generation: set.generation ?? 0 })}</dd>
              <dt>{t("detail.objects")}</dt><dd>{t("detail.objectsValue", { count: set.object_count, size: formatFileSize(set.object_bytes) })}</dd>
              <dt>{t("detail.verification")}</dt><dd><VerificationBadges t={t} set={set} /></dd>
            </>
          ) : null}
        </dl>
        {detail.error_message ? <StatusBanner tone="error" message={errorText(t, detail.error_code, detail.error_message)} /> : null}
        {set?.warnings.map((warning) => (
          <StatusBanner key={warning.code} tone="neutral" message={t.has(`warning.${warning.code}`) ? t(`warning.${warning.code}`, { count: Number(warning.count ?? 0) }) : warning.code} />
        ))}
        {detail.tenants.length ? (
          <DataTable columns={[t("columns.tenant"), t("columns.users"), t("columns.objects"), t("columns.size")]} emptyMessage={t("restore.noTenants")}>
            {detail.tenants.map((tenant) => (
              <tr key={tenant.id}><td>{tenant.name}</td><td>{tenant.users}</td><td>{tenant.objects}</td><td>{formatFileSize(tenant.bytes)}</td></tr>
            ))}
          </DataTable>
        ) : null}
        <EventsTable t={t} locale={locale} events={detail.events} />
      </div>
    </Modal>
  );
}

// --- Wiederherstellung -------------------------------------------------------------------------

function RestorePanel({ t, locale, restoreId, isOwner, onChanged }: { t: TFunc; locale: string; restoreId: string; isOwner: boolean; onChanged: () => Promise<void> }) {
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
    if (!open) return;
    const interval = setInterval(() => void load(), ACTIVE_POLL_MS);
    return () => clearInterval(interval);
  }, [load, open]);

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
    <article className="card storage-migration" aria-live="polite">
      <DataToolbar
        title={t(`restore.panelTitle.${job.kind}`)}
        description={t("restore.panelDescription", { archive: job.archive_name, time: formatDateTime(job.created_at, locale) })}
        actions={<Badge variant={RESTORE_VARIANTS[job.state]} dot>{t(`restoreState.${job.state}`)}</Badge>}
      />
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
      {job.error_message && job.state !== "rolled_back" ? <StatusBanner tone="error" message={errorText(t, job.error_code, job.error_message)} /> : null}
      {Array.isArray(result.warnings) && result.warnings.length ? (
        <details className="storage-events">
          <summary>{t("restore.importWarnings", { count: result.warnings.length })}</summary>
          <ul className="backup-list">{(result.warnings as string[]).map((warning, index) => <li key={index}>{warning}</li>)}</ul>
        </details>
      ) : null}
      {isOwner && ["queued", "preparing", "running", "verifying"].includes(job.state) && !job.cancel_requested ? (
        <div className="table-actions"><button type="button" className="button-danger" onClick={() => void cancel()}>{t("actions.cancel")}</button></div>
      ) : null}
      <EventsTable t={t} locale={locale} events={job.events} />
    </article>
  );
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

function Restore({ t, locale, isOwner, status, onChanged }: { t: TFunc; locale: string; isOwner: boolean; status: BackupStatus; onChanged: () => Promise<void> }) {
  const showToast = useToast();
  const confirm = useConfirm();
  const [sets, setSets] = useState<BackupSet[]>([]);
  const [profiles, setProfiles] = useState<StorageOverview["profiles"]>([]);
  const [history, setHistory] = useState<RestoreJob[]>([]);
  const [kind, setKind] = useState<"full" | "tenant_copy">("tenant_copy");
  const [setId, setSetId] = useState<string | null>(null);
  const [tenants, setTenants] = useState<BackupTenant[]>([]);
  const [tenantId, setTenantId] = useState<number | null>(null);
  const [newName, setNewName] = useState("");
  const [profileId, setProfileId] = useState<string | null>(null);
  const [preview, setPreview] = useState<RestorePreview | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [totp, setTotp] = useState("");
  const [skipRescue, setSkipRescue] = useState(false);
  const [skipReason, setSkipReason] = useState("");
  const [replayErasures, setReplayErasures] = useState(true);
  const [replayReason, setReplayReason] = useState("");
  const [working, setWorking] = useState(false);
  const [watching, setWatching] = useState<string | null>(status.current_restore?.id ?? null);
  const { get: restoreKeyFor, reset: resetRestoreKey } = useIdempotencyKey();

  const loadHistory = useCallback(async () => {
    try {
      setHistory(await browserApiFetch<RestoreJob[]>("/api/admin/restores?limit=10"));
    } catch {
      // Verlauf ist optional.
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        setSets(await browserApiFetch<BackupSet[]>("/api/admin/backups/sets"));
        const overview = await browserApiFetch<StorageOverview>("/api/admin/storage/overview");
        setProfiles(overview.profiles.filter((profile) => profile.provider !== "filesystem" && profile.is_enabled));
      } catch {
        // Ohne Liste bleibt der Assistent leer, Fehler zeigt die Vorschau.
      }
    })();
    void loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    setTenantId(null);
    setTenants([]);
    setPreview(null);
    if (!setId) return;
    void browserApiFetch<BackupTenant[]>(`/api/admin/backups/sets/${setId}/tenants`).then(setTenants).catch(() => setTenants([]));
  }, [setId]);

  useEffect(() => {
    setPreview(null);
    setConfirmation("");
  }, [kind, tenantId, newName, profileId]);

  // Neue Vorschau = neue Bestätigung = neuer Schlüssel.
  useEffect(() => {
    resetRestoreKey();
  }, [preview, resetRestoreKey]);

  async function loadPreview() {
    if (!setId) return;
    setWorking(true);
    try {
      setPreview(await browserApiFetch<RestorePreview>("/api/admin/restores/preview", {
        method: "POST",
        body: JSON.stringify({ backup_set_id: setId, kind, target_profile_id: kind === "full" ? profileId : null,
          source_tenant_id: kind === "tenant_copy" ? tenantId : null, new_name: kind === "tenant_copy" ? newName : null }),
      }));
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    } finally {
      setWorking(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!preview || !setId) return;
    if (kind === "full" && !(await confirm({ message: t("confirm.fullRestore"), tone: "danger", confirmLabel: t("actions.startRestore") }))) return;
    setWorking(true);
    try {
      const job = await browserApiFetch<RestoreJob>("/api/admin/restores", {
        method: "POST",
        body: JSON.stringify({
          backup_set_id: setId, kind, target_profile_id: kind === "full" ? profileId : null, source_tenant_id: kind === "tenant_copy" ? tenantId : null,
          new_name: kind === "tenant_copy" ? newName : null, confirmation, totp_code: totp.replace(/\s/g, ""),
          skip_rescue_backup: kind === "full" ? skipRescue : false, skip_rescue_reason: skipRescue ? skipReason : null,
          replay_erasures: replayErasures, replay_erasures_reason: replayErasures ? null : replayReason,
          idempotency_key: restoreKeyFor(`restore-${setId}`),
        }),
      });
      showToast(t("toast.restoreQueued"), "success");
      setWatching(job.id);
      setPreview(null);
      setTotp("");
      setConfirmation("");
      await onChanged();
      await loadHistory();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    } finally {
      setWorking(false);
    }
  }

  const selectedSet = sets.find((item) => item.id === setId) ?? null;
  const canPreview = setId !== null && (kind === "full" || (tenantId !== null && newName.trim() !== ""));
  const canSubmit = preview !== null && preview.blockers.length === 0 && confirmation.trim() === preview.confirmation_phrase && totp.replace(/\s/g, "").length >= 6
    && (!skipRescue || skipReason.trim() !== "") && (replayErasures || replayReason.trim() !== "");

  return (
    <div className="grid">
      {watching ? <RestorePanel t={t} locale={locale} restoreId={watching} isOwner={isOwner} onChanged={async () => { await onChanged(); await loadHistory(); }} /> : null}
      {isOwner ? (
        <article className="card">
          <DataToolbar title={t("restore.wizardTitle")} description={t("restore.wizardDescription")} />
          <ModalSaveForm className="grid" onSubmit={submit}>
            <h4 className="backup-step">{t("restore.step1")}</h4>
            <FilterTabs<"full" | "tenant_copy">
              value={kind}
              onChange={setKind}
              options={[{ value: "tenant_copy", label: t("restore.kindTenant") }, { value: "full", label: t("restore.kindFull") }]}
            />
            <p className="muted">{kind === "full" ? t("restore.kindFullHelp") : t("restore.kindTenantHelp")}</p>
            <label className="field-stack">
              <span className="field-label">{t("restore.backupPoint")}</span>
              <SearchableSelect<BackupSet, string>
                options={sets}
                value={setId}
                getId={(item) => item.id}
                getLabel={(item) => t("restore.setLabel", { time: formatDateTime(item.snapshot_at, locale), state: t(`setState.${item.state}`),
                  objects: item.object_count, verified: item.verify_state === "verified" ? t("verify.verified") : t("verify.unverified") })}
                onChange={(item) => setSetId(item?.id ?? null)}
                placeholder={t("restore.backupPointPlaceholder")}
                emptyLabel={t("restore.noBackups")}
              />
            </label>

            <h4 className="backup-step">{t("restore.step2")}</h4>
            {kind === "tenant_copy" ? (
              <div className="two-col">
                <label className="field-stack">
                  <span className="field-label">{t("restore.tenant")}</span>
                  <SearchableSelect<BackupTenant, number>
                    options={tenants}
                    value={tenantId}
                    getId={(item) => item.id}
                    getLabel={(item) => t("restore.tenantLabel", { name: item.name, users: item.users, size: formatFileSize(item.bytes) })}
                    onChange={(item) => { setTenantId(item?.id ?? null); if (item && !newName) setNewName(t("restore.copyName", { name: item.name })); }}
                    placeholder={t("restore.tenantPlaceholder")}
                    emptyLabel={t("restore.noTenants")}
                    disabled={!setId}
                  />
                </label>
                <label className="field-stack">
                  <span className="field-label">{t("restore.newName")}</span>
                  <input className="input" value={newName} maxLength={200} onChange={(event) => setNewName(event.target.value)} />
                  <span className="field-help">{t("restore.newNameHelp")}</span>
                </label>
              </div>
            ) : (
              <label className="field-stack">
                <span className="field-label">{t("restore.targetProfile")}</span>
                <SearchableSelect<StorageOverview["profiles"][number], string>
                  options={profiles}
                  value={profileId}
                  getId={(item) => item.id}
                  getLabel={(item) => item.is_active ? t("restore.profileActive", { name: item.name }) : item.name}
                  onChange={(item) => setProfileId(item?.id ?? null)}
                  placeholder={t("restore.targetProfileDefault")}
                  nullLabel={t("restore.targetProfileDefault")}
                />
                <span className="field-help">{t("restore.targetProfileHelp")}</span>
              </label>
            )}

            <h4 className="backup-step">{t("restore.step3")}</h4>
            <div className="table-actions">
              <button type="button" className="button-secondary" disabled={!canPreview || working} onClick={() => void loadPreview()}>{t("actions.preview")}</button>
            </div>
            {preview ? <PreviewFacts t={t} locale={locale} preview={preview} selected={selectedSet} /> : <p className="muted">{t("restore.previewHint")}</p>}

            {preview && preview.blockers.length === 0 ? (
              <>
                <h4 className="backup-step">{t("restore.step4")}</h4>
                {kind === "full" ? (
                  <>
                    <label className="checkbox-row"><input type="checkbox" checked={skipRescue} onChange={(event) => setSkipRescue(event.target.checked)} /><span>{t("restore.skipRescue")}</span></label>
                    {skipRescue ? (
                      <label className="field-stack">
                        <span className="field-label">{t("restore.skipRescueReason")}</span>
                        <textarea className="input" rows={2} maxLength={500} value={skipReason} onChange={(event) => setSkipReason(event.target.value)} />
                      </label>
                    ) : null}
                  </>
                ) : null}
                {/* Löschjournal (Datenschutz-Audit PRIV-010): standardmässig an, aus nur mit Begründung */}
                <label className="checkbox-row"><input type="checkbox" checked={replayErasures} onChange={(event) => setReplayErasures(event.target.checked)} /><span>{t("restore.replayErasures")}</span></label>
                <p className="field-help">{t("restore.replayErasuresHint")}</p>
                {!replayErasures ? (
                  <label className="field-stack">
                    <span className="field-label">{t("restore.replayErasuresReason")}</span>
                    <textarea className="input" rows={2} maxLength={500} value={replayReason} onChange={(event) => setReplayReason(event.target.value)} />
                  </label>
                ) : null}
                <div className="two-col">
                  <label className="field-stack">
                    <span className="field-label">{t("restore.confirmationLabel", { phrase: preview.confirmation_phrase })}</span>
                    <input className="input" value={confirmation} autoComplete="off" onChange={(event) => setConfirmation(event.target.value)} />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">{t("restore.totp")}</span>
                    <input className="input" value={totp} inputMode="numeric" autoComplete="one-time-code" maxLength={10} onChange={(event) => setTotp(event.target.value)} />
                    <span className="field-help">{t("restore.totpHelp")}</span>
                  </label>
                </div>
                <div className="modal-actions">
                  <button type="submit" className={kind === "full" ? "button-danger" : "button-primary"} disabled={!canSubmit || working}>
                    {kind === "full" ? t("actions.startFullRestore") : t("actions.startTenantRestore")}
                  </button>
                </div>
              </>
            ) : null}
          </ModalSaveForm>
        </article>
      ) : <StatusBanner tone="neutral" message={t("restore.ownerOnly")} />}

      <article className="card">
        <DataToolbar title={t("restore.historyTitle")} />
        <DataTable columns={[t("columns.time"), t("columns.kind"), t("columns.state"), t("columns.archive"), t("columns.actor"), t("columns.actions")]} emptyMessage={t("restore.historyEmpty")}>
          {history.map((job) => (
            <tr key={job.id}>
              <td>{formatDateTime(job.created_at, locale)}</td>
              <td>{t(`restore.kindShort.${job.kind}`)}</td>
              <td><Badge variant={RESTORE_VARIANTS[job.state]}>{t(`restoreState.${job.state}`)}</Badge></td>
              <td className="muted backup-id">{job.archive_name}</td>
              <td className="muted">{job.requested_by_email ?? "—"}</td>
              <td><button type="button" className="button-secondary button-ghost" onClick={() => setWatching(job.id)}>{t("actions.details")}</button></td>
            </tr>
          ))}
        </DataTable>
      </article>
    </div>
  );
}

function PreviewFacts({ t, locale, preview, selected }: { t: TFunc; locale: string; preview: RestorePreview; selected: BackupSet | null }) {
  const set = preview.backup_set ?? selected;
  return (
    <div className="grid">
      <dl className="storage-facts">
        <dt>{t("detail.archive")}</dt><dd className="backup-id">{set?.archive_name}</dd>
        <dt>{t("detail.snapshot")}</dt><dd>{set ? formatDateTime(set.snapshot_at, locale) : "—"}</dd>
        <dt>{t("detail.version")}</dt><dd>{t("detail.versionValue", { app: set?.app_version ?? "—", schema: preview.schema_revision ?? "—" })}</dd>
        <dt>{t("preview.schema")}</dt><dd>{t(`schema.${preview.schema_state}`)}</dd>
        {preview.kind === "full" ? (<><dt>{t("preview.target")}</dt><dd>{preview.target_profile_name ?? "—"}</dd></>) : null}
        {preview.tenant ? (<><dt>{t("restore.tenant")}</dt><dd>{t("restore.tenantLabel", { name: preview.tenant.name, users: preview.tenant.users, size: formatFileSize(preview.tenant.bytes) })}</dd></>) : null}
        {preview.new_name ? (<><dt>{t("restore.newName")}</dt><dd>{preview.new_name}</dd></>) : null}
        <dt>{t("preview.size")}</dt><dd>{formatFileSize(preview.estimated_bytes)}</dd>
        <dt>{t("preview.steps")}</dt>
        <dd><ol className="backup-list">{preview.steps.map((step) => <li key={step}>{t.has(`step.${step}`) ? t(`step.${step}`) : step}</li>)}</ol></dd>
      </dl>
      {preview.blockers.map((code) => <StatusBanner key={code} tone="error" message={t.has(`blocker.${code}`) ? t(`blocker.${code}`) : code} />)}
      {preview.risks.map((code) => <StatusBanner key={code} tone="neutral" message={t.has(`risk.${code}`) ? t(`risk.${code}`) : code} />)}
    </div>
  );
}

// --- Einstellungen -----------------------------------------------------------------------------

type SettingsForm = Omit<BackupSettings, "worker_config" | "repository" | "ntfy_configured" | "updated_at" | "updated_by_email">;

function Settings({ t, locale, settings, isOwner, onSaved }: { t: TFunc; locale: string; settings: BackupSettings; isOwner: boolean; onSaved: (value: BackupSettings) => void }) {
  const showToast = useToast();
  const [form, setForm] = useState<SettingsForm>({
    schedule_enabled: settings.schedule_enabled, interval_hours: settings.interval_hours, schedule_offset_minutes: settings.schedule_offset_minutes,
    keep_within_days: settings.keep_within_days, keep_daily: settings.keep_daily, keep_weekly: settings.keep_weekly, keep_monthly: settings.keep_monthly,
    verify_interval_hours: settings.verify_interval_hours, verify_sample_objects: settings.verify_sample_objects,
    restore_test_interval_days: settings.restore_test_interval_days, success_notification: settings.success_notification,
  });
  const [saving, setSaving] = useState(false);
  const update = <K extends keyof SettingsForm>(key: K, value: SettingsForm[K]) => setForm((current) => ({ ...current, [key]: value }));
  const config = settings.worker_config;
  const repo = settings.repository;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try {
      const saved = await browserApiFetch<BackupSettings>("/api/admin/backups/settings", { method: "PUT", body: JSON.stringify(form) });
      onSaved(saved);
      showToast(t("toast.settingsSaved"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    } finally {
      setSaving(false);
    }
  }

  const numberField = (key: keyof SettingsForm, label: string, min: number, max: number, help?: string) => (
    <label className="field-stack">
      <span className="field-label">{label}</span>
      <input className="input" type="number" min={min} max={max} value={Number(form[key])} disabled={!isOwner}
        onChange={(event) => update(key, Number(event.target.value) as never)} />
      {help ? <span className="field-help">{help}</span> : null}
    </label>
  );

  return (
    <div className="grid">
      <article className="card">
        <DataToolbar title={t("settings.connectionTitle")} description={t("settings.connectionDescription")} />
        <dl className="storage-facts">
          <dt>{t("settings.repository")}</dt><dd className="backup-id">{String(config.repository ?? "—")}</dd>
          <dt>{t("settings.connection")}</dt>
          <dd><Badge variant={repo.ok ? "success" : repo.ok === false ? "danger" : "neutral"}>{repo.ok ? t("repository.reachable") : repo.ok === false ? t("repository.unreachable") : t("repository.unknown")}</Badge>{" "}
            {repo.error_code ? <span className="muted">{errorText(t, `borg_${repo.error_code}`, repo.error)}</span> : null}</dd>
          <dt>{t("settings.encryption")}</dt><dd>{repo.encryption ?? "—"}</dd>
          <dt>{t("settings.repositoryId")}</dt><dd className="backup-id">{repo.repository_id ?? "—"} {config.repository_id_pinned ? <Badge variant="success">{t("settings.pinned")}</Badge> : <Badge variant="warning">{t("settings.notPinned")}</Badge>}</dd>
          <dt>{t("settings.hostKey")}</dt><dd>{config.host_key_pinned ? <Badge variant="success">{t("settings.pinned")}</Badge> : <Badge variant="danger">{t("settings.notPinned")}</Badge>}</dd>
          <dt>{t("settings.secrets")}</dt><dd>{t("settings.secretsValue", { key: config.ssh_key_configured ? t("settings.present") : t("settings.missing"), passphrase: config.passphrase_configured ? t("settings.present") : t("settings.missing") })}</dd>
          <dt>{t("settings.maintenanceKey")}</dt><dd>{config.maintenance_key_present ? <Badge variant="warning">{t("settings.maintenanceKeyPresent")}</Badge> : <span className="muted">{t("settings.maintenanceKeyAbsent")}</span>}</dd>
          <dt>{t("settings.borgVersion")}</dt><dd>{repo.borg_version ?? "—"}</dd>
          <dt>{t("settings.lastCheck")}</dt><dd>{repo.checked_at ? formatDateTime(repo.checked_at, locale) : "—"}</dd>
          <dt>{t("settings.staging")}</dt><dd>{t("settings.stagingValue", { budget: formatFileSize(Number(config.staging_max_bytes ?? 0)), free: repo.staging_free_bytes !== null ? formatFileSize(repo.staging_free_bytes) : "—" })}</dd>
          <dt>{t("settings.ntfy")}</dt><dd>{settings.ntfy_configured ? <Badge variant="success">{t("settings.ntfyConfigured")}</Badge> : <><Badge variant="warning">{t("settings.ntfyMissing")}</Badge> <a href="/admin/notifications">{t("settings.ntfyLink")}</a></>}</dd>
        </dl>
      </article>
      <article className="card">
        <DataToolbar title={t("settings.title")} description={isOwner ? t("settings.description") : t("settings.readOnly")} />
        <ModalSaveForm className="grid" onSubmit={submit}>
          <label className="checkbox-row"><input type="checkbox" checked={form.schedule_enabled} disabled={!isOwner} onChange={(event) => update("schedule_enabled", event.target.checked)} /><span>{t("settings.scheduleEnabled")}</span></label>
          <div className="two-col">
            {numberField("interval_hours", t("settings.interval"), 1, 168, t("settings.intervalHelp"))}
            {numberField("schedule_offset_minutes", t("settings.offset"), 0, 1439, t("settings.offsetHelp"))}
          </div>
          <h4 className="backup-step">{t("settings.retentionTitle")}</h4>
          <p className="muted">{t("settings.retentionHelp")}</p>
          <div className="two-col">
            {numberField("keep_within_days", t("settings.keepWithin"), 0, 3650)}
            {numberField("keep_daily", t("settings.keepDaily"), 0, 3650)}
          </div>
          <div className="two-col">
            {numberField("keep_weekly", t("settings.keepWeekly"), 0, 520)}
            {numberField("keep_monthly", t("settings.keepMonthly"), 0, 240)}
          </div>
          <h4 className="backup-step">{t("settings.checksTitle")}</h4>
          <div className="two-col">
            {numberField("verify_interval_hours", t("settings.verifyInterval"), 1, 8760)}
            {numberField("verify_sample_objects", t("settings.verifySample"), 0, 100000)}
          </div>
          <div className="two-col">
            {numberField("restore_test_interval_days", t("settings.restoreTestInterval"), 1, 365)}
            <label className="field-stack">
              <span className="field-label">{t("settings.successNotification")}</span>
              <Select className="input" value={form.success_notification} disabled={!isOwner} onChange={(event) => update("success_notification", event.target.value as SettingsForm["success_notification"])}>
                <option value="off">{t("settings.notifyOff")}</option>
                <option value="daily">{t("settings.notifyDaily")}</option>
                <option value="each">{t("settings.notifyEach")}</option>
              </Select>
            </label>
          </div>
          {settings.updated_by_email ? <p className="muted">{t("settings.updated", { email: settings.updated_by_email, time: formatDateTime(settings.updated_at, locale) })}</p> : null}
          {isOwner ? (
            <div className="modal-actions"><button type="submit" className="button-primary" disabled={saving}>{t("actions.save")}</button></div>
          ) : null}
        </ModalSaveForm>
      </article>
    </div>
  );
}
