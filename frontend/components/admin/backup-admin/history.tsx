"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal } from "@/components/ui/modal";
import { Pagination } from "@/components/ui/pagination";
import { Select } from "@/components/ui/select";
import { StatusBanner } from "@/components/ui/status-banner";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateTime, formatFileSize } from "@/lib/utils/format";
import type { BackupJob, BackupJobDetail, BackupJobKind, BackupJobPage, BackupStatus } from "@/types/api";

import type { BackupActions, BackupNavigate } from "./overview";
import { durationText, errorText, EventTimeline, JOB_VARIANTS, VerificationBadges, type TFunc } from "./shared";

export const HISTORY_FILTERS = ["all", "completed", "partial", "failed"] as const;
export type HistoryFilter = (typeof HISTORY_FILTERS)[number];
export const HISTORY_KINDS = ["backup", "verify", "restore_test", "retention"] as const;
const PAGE_SIZE = 25;

export function KindIcon({ kind }: { kind: BackupJobKind }) {
  const paths: Record<BackupJobKind, string> = {
    backup: "M3.5 4.5h17v4h-17zM5 8.5v11h14v-11M10 12.5h4",
    verify: "M12 3l7.5 3v5.5c0 4.6-3.1 8.1-7.5 9.5-4.4-1.4-7.5-4.9-7.5-9.5V6zM9 12l2 2 4-4",
    restore_test: "M9 3h6M10 3v6l-5 9a2 2 0 001.7 3h10.6a2 2 0 001.7-3l-5-9V3M7.5 14h9",
    retention: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13",
  };
  return (
    <span className={`backup-kind-icon backup-kind-${kind}`} aria-hidden="true">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d={paths[kind]} /></svg>
    </span>
  );
}

/** Inhalt einer Zeile: Objekte/DB beim Backup, Kurzfassung bei Prüfung, Restore-Test, Aufbewahrung. */
function contentCell(t: TFunc, locale: string, job: BackupJob): { main: string; sub: string } {
  const set = job.backup_set;
  const summary = job.summary ?? {};
  if (job.kind === "retention") {
    return typeof summary.removed === "number"
      ? { main: t("history.retentionRemoved", { count: summary.removed }), sub: typeof summary.kept === "number" ? t("history.retentionKept", { count: summary.kept }) : "" }
      : { main: "—", sub: "" };
  }
  if (job.kind === "verify" || job.kind === "restore_test") {
    const checked = typeof summary.contents_checked === "number" ? t("history.contentsChecked", { count: summary.contents_checked }) : "—";
    const sub = job.kind === "restore_test" && typeof summary.application_ok === "boolean"
      ? (summary.application_ok ? t("history.applicationOk") : t("history.applicationFailed")) : summary.deep ? t("history.deep") : "";
    return { main: checked, sub };
  }
  if (!set) return { main: "—", sub: "" };
  return { main: t("history.objects", { count: set.object_count }), sub: set.db_dump_bytes ? t("history.database", { size: formatFileSize(set.db_dump_bytes, locale) }) : "" };
}

export function History({ t, locale, isOwner, status, params, navigate, actions, version }: {
  t: TFunc; locale: string; isOwner: boolean; status: BackupStatus;
  params: { state: HistoryFilter; kind: BackupJobKind | ""; offset: number; job: string | null };
  navigate: BackupNavigate; actions: BackupActions; version: number;
}) {
  const showToast = useToast();
  const [page, setPage] = useState<BackupJobPage | null>(null);
  const [failed, setFailed] = useState(false);
  const { state, kind, offset } = params;

  const load = useCallback(async () => {
    const query = new URLSearchParams({ offset: String(offset), limit: String(PAGE_SIZE) });
    if (state !== "all") query.set("state", state);
    if (kind) query.set("kind", kind);
    try {
      setPage(await browserApiFetch<BackupJobPage>(`/api/admin/backups?${query.toString()}`));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [state, kind, offset]);

  useEffect(() => {
    void load();
  }, [load, version]);

  const counts = page?.counts ?? {};
  const countOf = (filter: HistoryFilter) => filter === "all" ? Object.values(counts).reduce((sum, value) => sum + (value ?? 0), 0)
    : filter === "failed" ? (counts.failed ?? 0) + (counts.interrupted ?? 0) : (counts[filter] ?? 0);
  const current = status.current_job;

  async function verify(job: BackupJob) {
    try {
      await actions.verifyJob(job.id);
      await load();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    }
  }

  return (
    <section className="card" aria-labelledby="backup-history-title">
      <div className="backup-section-head">
        <h2 id="backup-history-title" className="backup-section-title">{t("history.title")}</h2>
        <p className="muted">{t("history.description")}</p>
      </div>
      <div className="list-filter-row backup-history-filters">
        <FilterTabs<HistoryFilter>
          value={state}
          onChange={(value) => navigate({ state: value === "all" ? null : value, offset: null })}
          options={HISTORY_FILTERS.map((value) => ({ value, label: value === "all" ? t("history.filterAll") : t(`state.${value}`), count: page ? countOf(value) : undefined }))}
        />
        <label className="backup-inline-field">
          <span>{t("history.kind")}</span>
          <Select className="input backup-kind-select" value={kind} aria-label={t("history.kind")}
            onChange={(event) => navigate({ kind: event.target.value || null, offset: null })}>
            <option value="">{t("history.allKinds")}</option>
            {HISTORY_KINDS.map((value) => <option key={value} value={value}>{t(`kind.${value}`)}</option>)}
          </Select>
        </label>
      </div>
      {failed ? <StatusBanner tone="error" message={t("history.loadFailed")} /> : null}
      <DataTable
        columns={[t("columns.time"), t("columns.job"), t("columns.state"), t("columns.duration"), t("columns.content"), t("columns.newData"), t("columns.verification"), t("columns.actions")]}
        emptyMessage={page ? t("history.emptyFilter") : t("timeline.loading")}
      >
        {(page?.items ?? []).map((job) => {
          const set = job.backup_set;
          const content = contentCell(t, locale, job);
          const verifying = current !== null && current.kind === "verify" && !!set && current.backup_set?.id === set.id;
          const canVerify = isOwner && job.kind === "backup" && !!set && set.verify_state !== "verified" && !verifying;
          const problem = job.state === "partial"
            ? t("history.partialDetail", { count: Number(set?.warnings.find((w) => w.code === "missing_objects")?.count ?? 0) })
            : ["failed", "interrupted"].includes(job.state) ? errorText(t, job.error_code, job.error_message) : null;
          return (
            <tr key={job.id} className={job.state === "failed" || job.state === "interrupted" ? "backup-row-failed" : undefined}>
              <td className="backup-nowrap">
                <div className="backup-strong">{formatDateTime(set?.snapshot_at ?? job.created_at, locale)}</div>
                <div className="backup-mono muted" title={job.id}>{job.id.slice(0, 8)}</div>
              </td>
              <td>
                <div className="backup-job-cell">
                  <KindIcon kind={job.kind} />
                  <div><div className="backup-strong">{t(`kind.${job.kind}`)}</div><div className="muted backup-small">{t(`trigger.${job.trigger}`)}{job.requested_by_email && job.trigger === "manual" ? ` · ${job.requested_by_email}` : ""}</div></div>
                </div>
              </td>
              <td>
                <div className="backup-badges">
                  <Badge variant={JOB_VARIANTS[job.state]}>{t(`state.${job.state}`)}</Badge>
                  {set?.protected ? <Badge variant="info">{t("history.protected")}</Badge> : null}
                </div>
                {problem ? <div className={job.state === "partial" ? "backup-small backup-text-warning" : "backup-small backup-text-danger"}>{problem}</div> : null}
              </td>
              <td className="backup-num">{durationText(t, job.duration_seconds)}</td>
              <td className="backup-num"><div>{content.main}</div>{content.sub ? <div className="muted backup-small">{content.sub}</div> : null}</td>
              <td className="backup-num">
                {set && job.kind === "backup" ? (
                  <><div>{t("history.newData", { count: set.new_object_count, size: formatFileSize(set.new_object_bytes, locale) })}</div>
                    {set.deduplicated_bytes !== null ? <div className="muted backup-small">{t("history.stored", { size: formatFileSize(set.deduplicated_bytes, locale) })}</div> : null}</>
                ) : "—"}
              </td>
              <td>{set && job.kind === "backup" ? <VerificationBadges t={t} set={set} verifying={verifying} /> : "—"}</td>
              <td>
                <div className="table-actions backup-row-actions">
                  {canVerify ? <button type="button" className="button-secondary" disabled={actions.busy !== null} onClick={() => void verify(job)}>{t("actions.verify")}</button> : null}
                  <button type="button" className="button-secondary" onClick={() => navigate({ job: job.id })} aria-label={t("history.detailsFor", { kind: t(`kind.${job.kind}`), time: formatDateTime(job.created_at, locale) })}>{t("actions.details")}</button>
                </div>
              </td>
            </tr>
          );
        })}
      </DataTable>
      {page ? (
        <div className="backup-history-foot">
          <Pagination offset={page.offset} limit={page.limit} total={page.total} onOffsetChange={(value) => navigate({ offset: value ? String(value) : null })} />
        </div>
      ) : null}
      {params.job ? <JobDrawer t={t} locale={locale} jobId={params.job} onClose={() => navigate({ job: null })} /> : null}
    </section>
  );
}

/** Detail-Schublade eines Auftrags (rechts angedockter Dialog, Escape/Schliessen gibt den Fokus zurück). */
export function JobDrawer({ t, locale, jobId, onClose }: { t: TFunc; locale: string; jobId: string; onClose: () => void }) {
  const [detail, setDetail] = useState<BackupJobDetail | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    setDetail(null);
    setFailed(false);
    browserApiFetch<BackupJobDetail>(`/api/admin/backups/${encodeURIComponent(jobId)}`)
      .then((value) => { if (alive) setDetail(value); })
      .catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, [jobId]);
  const set = detail?.backup_set ?? null;
  const title = detail ? t("detail.title", { kind: t(`kind.${detail.kind}`) }) : t("detail.loadingTitle");
  return (
    <Modal open title={title} onClose={onClose} size="wide" className="backup-drawer"
      description={detail ? `${t(`trigger.${detail.trigger}`)} · ${detail.id.slice(0, 8)}` : undefined}>
      {failed ? <StatusBanner tone="error" message={t("detail.loadFailed")} /> : null}
      {!detail && !failed ? <p className="muted">{t("timeline.loading")}</p> : null}
      {detail ? (
        <div className="backup-drawer-body">
          <div className="backup-badges">
            <Badge variant={JOB_VARIANTS[detail.state]} dot>{t(`state.${detail.state}`)}</Badge>
            {set && detail.kind === "backup" ? <VerificationBadges t={t} set={set} /> : null}
            {set?.protected ? <Badge variant="info">{t("history.protected")}</Badge> : null}
          </div>
          {["failed", "interrupted"].includes(detail.state) ? <StatusBanner tone="error" message={errorText(t, detail.error_code, detail.error_message)} /> : null}
          {set?.warnings.map((warning) => (
            <StatusBanner key={warning.code} tone="neutral" message={t.has(`warning.${warning.code}`) ? t(`warning.${warning.code}`, { count: Number(warning.count ?? 0) }) : warning.code} />
          ))}
          <dl className="storage-facts">
            <dt>{t("detail.created")}</dt><dd>{formatDateTime(detail.created_at, locale)}{detail.requested_by_email ? ` · ${detail.requested_by_email}` : ""}</dd>
            <dt>{t("detail.duration")}</dt><dd>{durationText(t, detail.duration_seconds)}</dd>
            {set ? (
              <>
                <dt>{t("detail.archive")}</dt><dd className="backup-id">{set.archive_name}</dd>
                <dt>{t("detail.snapshot")}</dt><dd>{formatDateTime(set.snapshot_at, locale)}</dd>
                <dt>{t("detail.version")}</dt><dd>{t("detail.versionValue", { app: set.app_version ?? "—", schema: set.alembic_revision ?? "—" })}</dd>
                <dt>{t("detail.storageSource")}</dt><dd>{t("detail.storageValue", { profile: set.profile_name ?? "—", generation: set.generation ?? 0 })}</dd>
                <dt>{t("detail.objects")}</dt><dd>{t("detail.objectsValue", { count: set.object_count, size: formatFileSize(set.object_bytes, locale) })}</dd>
                {detail.kind === "backup" ? <><dt>{t("columns.newData")}</dt><dd>{t("history.newData", { count: set.new_object_count, size: formatFileSize(set.new_object_bytes, locale) })}</dd></> : null}
              </>
            ) : null}
          </dl>
          {detail.tenants.length ? (
            <div className="backup-stack">
              <h3 className="backup-subtitle">{t("detail.tenants")}</h3>
              <DataTable columns={[t("columns.tenant"), t("columns.users"), t("columns.objects"), t("columns.size")]} emptyMessage={t("restore.noTenants")}>
                {detail.tenants.map((tenant) => (
                  <tr key={tenant.id}><td>{tenant.name}</td><td>{tenant.users.toLocaleString(locale)}</td><td>{tenant.objects.toLocaleString(locale)}</td><td>{formatFileSize(tenant.bytes, locale)}</td></tr>
                ))}
              </DataTable>
            </div>
          ) : null}
          <div className="backup-stack">
            <h3 className="backup-subtitle">{t("detail.events")}</h3>
            <EventTimeline t={t} locale={locale} events={detail.events} />
          </div>
        </div>
      ) : null}
    </Modal>
  );
}
