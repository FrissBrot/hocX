"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { StatTile } from "@/components/ui/stat-tile";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { stepUpFetch } from "@/lib/admin-step-up";
import { apiErrorCode } from "@/lib/files/file-import";
import { useVisibleInterval } from "@/lib/hooks/use-visible-interval";
import { formatDateTime, formatFileSize, formatInteger } from "@/lib/utils/format";

// Plattform-Admin: laufende Datei-Importe aller Mandanten (nur Zähler) und Kennzahlen der letzten
// Tage (Backend routes/admin_cloud_import.py). Notfall-Abbruch mit Rückfrage, auditiert.

export type AdminImport = {
  id: string;
  tenant_name: string;
  source: string;
  status: string;
  total_items: number;
  total_bytes: number;
  counts: Record<string, number>;
  error: string | null;
  created_at: string;
  started_at: string | null;
  last_progress_at: string | null;
  not_before: string | null;
};

export type AdminImportMetric = {
  day: string;
  source: string;
  jobs: number;
  failed_jobs: number;
  imported: number;
  bytes: number;
  failed_items: number;
};

export type AdminImportOverview = { active: AdminImport[]; metrics: AdminImportMetric[]; days: number };

const POLL_MS = 20_000;
const STATUS_VARIANT: Record<string, BadgeVariant> = {
  listing: "info",
  queued: "info",
  running: "info",
  needs_reauth: "warning",
  cancel_requested: "warning",
  draft: "neutral",
  ready: "neutral",
};

function isThrottled(job: AdminImport): boolean {
  return job.not_before !== null && new Date(job.not_before).getTime() > Date.now();
}

export function AdminCloudImports({ initialOverview }: { initialOverview: AdminImportOverview }) {
  const t = useTranslations("admin.cloudImports");
  const tImport = useTranslations("fileImport");
  const locale = useLocale();
  const confirm = useConfirm();
  const showToast = useToast();
  const [overview, setOverview] = useState(initialOverview);

  useVisibleInterval(async () => {
    try {
      setOverview(await browserApiFetch<AdminImportOverview>("/api/admin/cloud-imports"));
    } catch {
      // nächster Takt
    }
  }, POLL_MS);

  function sourceLabel(source: string): string {
    if (source === "zip" || source === "folder") return tImport(`source.${source}`);
    return tImport.has(`source.provider.${source}`) ? tImport(`source.provider.${source}`) : source;
  }

  async function cancel(job: AdminImport) {
    const ok = await confirm({ tone: "danger", message: t("cancelConfirm", { tenant: job.tenant_name }), confirmLabel: t("cancelImport") });
    if (!ok) return;
    try {
      // Passkey-Bestätigung je Abbruch (Backend require_step_up("cloud-import-cancel"))
      await stepUpFetch("cloud-import-cancel", `/api/admin/cloud-imports/${job.id}/cancel`, { method: "POST" });
      setOverview(await browserApiFetch<AdminImportOverview>("/api/admin/cloud-imports"));
      showToast(t("cancelled"), "success");
    } catch (error) {
      // Fachfehler als Code (not_found, invalid_status): Text aus fileImport.errors
      const code = apiErrorCode(error);
      showToast(code && tImport.has(`errors.${code}`) ? tImport(`errors.${code}`) : error instanceof Error ? error.message : t("cancelFailed"), "error");
    }
  }

  const totals = overview.metrics.reduce(
    (sum, row) => ({
      jobs: sum.jobs + row.jobs, failedJobs: sum.failedJobs + row.failed_jobs, imported: sum.imported + row.imported,
      bytes: sum.bytes + row.bytes, failedItems: sum.failedItems + row.failed_items,
    }),
    { jobs: 0, failedJobs: 0, imported: 0, bytes: 0, failedItems: 0 },
  );
  const errorRate = totals.imported + totals.failedItems ? Math.round((totals.failedItems / (totals.imported + totals.failedItems)) * 100) : 0;

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("title")}</h1>
          <p className="muted">{t("intro")}</p>
        </div>
      </div>
      <section className="admin-overview-kpis" aria-label={t("kpis.title", { days: overview.days })}>
        <StatTile label={t("kpis.active")} value={formatInteger(overview.active.length, locale)} />
        <StatTile label={t("kpis.jobs", { days: overview.days })} value={formatInteger(totals.jobs, locale)} hint={t("kpis.failedJobs", { count: totals.failedJobs })} />
        <StatTile label={t("kpis.files")} value={formatInteger(totals.imported, locale)} hint={formatFileSize(totals.bytes, locale)} />
        <StatTile label={t("kpis.errorRate")} value={t("kpis.percent", { value: errorRate })} hint={t("kpis.failedItems", { count: totals.failedItems })} />
      </section>

      <DataToolbar title={t("active.title")} />
      <DataTable
        columns={[t("columns.tenant"), t("columns.source"), t("columns.status"), t("columns.progress"), t("columns.lastProgress"), ""]}
        emptyMessage={t("active.empty")}
      >
        {overview.active.map((job) => {
          const done = (job.counts.imported ?? 0) + (job.counts.duplicate ?? 0) + (job.counts.failed ?? 0);
          return (
            <tr key={job.id}>
              <td>{job.tenant_name}</td>
              <td>{sourceLabel(job.source)}</td>
              <td>
                <Badge variant={STATUS_VARIANT[job.status] ?? "neutral"} dot>{tImport.has(`status.${job.status}`) ? tImport(`status.${job.status}`) : job.status}</Badge>
                {isThrottled(job) ? <span className="muted"> {t("throttled")}</span> : null}
              </td>
              <td>{t("progress", { done: formatInteger(done, locale), total: formatInteger(job.total_items, locale), size: formatFileSize(job.total_bytes, locale) })}</td>
              <td>{job.last_progress_at ? formatDateTime(job.last_progress_at, locale) : "–"}</td>
              <td>
                {job.status !== "cancel_requested" ? (
                  <button type="button" className="button-danger" onClick={() => void cancel(job)}>{t("cancel")}</button>
                ) : null}
              </td>
            </tr>
          );
        })}
      </DataTable>

      <DataToolbar title={t("metrics.title", { days: overview.days })} />
      <DataTable
        columns={[t("columns.day"), t("columns.source"), t("columns.jobs"), t("columns.imported"), t("columns.volume"), t("columns.failedItems")]}
        emptyMessage={t("metrics.empty")}
      >
        {overview.metrics.map((row) => (
          <tr key={`${row.day}-${row.source}`}>
            <td>{row.day}</td>
            <td>{sourceLabel(row.source)}</td>
            <td>{t("jobsCell", { jobs: row.jobs, failed: row.failed_jobs })}</td>
            <td>{formatInteger(row.imported, locale)}</td>
            <td>{formatFileSize(row.bytes, locale)}</td>
            <td>{formatInteger(row.failed_items, locale)}</td>
          </tr>
        ))}
      </DataTable>
    </div>
  );
}
