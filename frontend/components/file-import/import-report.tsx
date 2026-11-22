"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Pagination } from "@/components/ui/pagination";
import { StatusBanner } from "@/components/ui/status-banner";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { apiErrorCode, type ImportItemStatus, type ImportJob, type ImportReportItem } from "@/lib/files/file-import";
import { formatDate, formatDateTime, formatFileSize, formatInteger } from "@/lib/utils/format";

const PAGE_SIZE = 50;
type ReportView = "all" | "imported" | "duplicate" | "skipped" | "failed";

const STATUS_VARIANT: Partial<Record<ImportItemStatus, BadgeVariant>> = {
  imported: "success",
  duplicate: "info",
  skipped: "neutral",
  failed: "danger",
  cancelled: "neutral",
};

export function ImportReport({ job, onJob }: { job: ImportJob; onJob: (job: ImportJob) => void }) {
  const t = useTranslations("fileImport");
  const locale = useLocale();
  const showToast = useToast();
  const [view, setView] = useState<ReportView>("all");
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<ImportReportItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const genericError = useRef(t("errors.generic"));

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const status = view === "all" ? "" : `&status=${view}`;
    browserApiFetch<{ items: ImportReportItem[]; total: number }>(`/api/cloud-import/jobs/${job.id}/items?offset=${offset}&limit=${PAGE_SIZE}${status}`)
      .then((result) => {
        if (cancelled) return;
        setItems(result.items);
        setTotal(result.total);
      })
      .catch((error) => showToast(error instanceof Error ? error.message : genericError.current, "error"))
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [job.id, offset, view, showToast]);

  async function handleResume() {
    try {
      onJob(await browserApiFetch<ImportJob>(`/api/cloud-import/jobs/${job.id}/resume`, { method: "POST" }));
    } catch (error) {
      const code = apiErrorCode(error);
      showToast(code && t.has(`errors.${code}`) ? t(`errors.${code}`) : error instanceof Error ? error.message : t("errors.generic"), "error");
    }
  }

  const counts = job.counts;
  const tone = job.status === "done" ? "success" : job.status === "failed" ? "error" : "neutral";
  const errorKey = job.error ? `errors.${job.error}` : null;

  return (
    <section className="section-card file-import-card">
      <h2 className="section-title">{t("report.title")}</h2>
      <StatusBanner
        tone={tone}
        message={t(`report.status.${job.status === "done" || job.status === "failed" ? job.status : "cancelled"}`, {
          when: formatDateTime(job.finished_at, locale),
        })}
      />
      {errorKey && t.has(errorKey) ? <p className="muted">{t(errorKey)}</p> : null}
      <p className="file-import-stats">
        <span>{t("progress.imported", { count: counts.imported ?? 0 })}</span>
        <span>{t("progress.duplicates", { count: counts.duplicate ?? 0 })}</span>
        <span>{t("preview.skipped", { count: counts.skipped ?? 0 })}</span>
        <span>{t("progress.failed", { count: counts.failed ?? 0 })}</span>
        {counts.cancelled ? <span>{t("report.cancelledCount", { count: counts.cancelled })}</span> : null}
      </p>
      {Object.keys(job.codes).length ? (
        <p className="muted">
          {Object.entries(job.codes)
            .map(([code, count]) => `${t.has(`codes.${code}`) ? t(`codes.${code}`) : code}: ${formatInteger(count, locale)}`)
            .join(" · ")}
        </p>
      ) : null}
      {job.albums.length ? (
        <ul className="file-import-album-report">
          {job.albums.map((album) => (
            <li key={album.name}>
              {album.reused
                ? t(album.candidates > 1 ? "report.albumReusedOldest" : "report.albumReused", { name: album.name, count: album.candidates })
                : t("report.albumCreated", { name: album.name })}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="field-help">{t("report.retention")}</p>
      {job.status === "failed" && job.is_owner ? (
        <div className="modal-actions">
          <button type="button" className="button-primary" onClick={() => void handleResume()}>{t("report.resume")}</button>
        </div>
      ) : null}

      <FilterTabs<ReportView>
        value={view}
        onChange={(value) => { setView(value); setOffset(0); }}
        options={[
          { value: "all", label: t("report.views.all") },
          { value: "imported", label: t("report.views.imported"), count: counts.imported ?? 0 },
          { value: "duplicate", label: t("report.views.duplicate"), count: counts.duplicate ?? 0 },
          { value: "skipped", label: t("report.views.skipped"), count: counts.skipped ?? 0 },
          { value: "failed", label: t("report.views.failed"), count: counts.failed ?? 0 },
        ]}
      />
      <DataTable
        columns={[t("preview.columns.path"), t("report.columns.status"), t("report.columns.reason"), t("preview.columns.tags"), t("preview.columns.date"), t("report.columns.size")]}
        emptyMessage={loading ? t("preview.loading") : t("report.empty")}
      >
        {items.map((item) => (
          <tr key={item.path}>
            <td className="file-import-path">
              {item.file_id ? (
                <a href={`${browserApiBaseUrl}/api/stored-files/${item.file_id}/content`} target="_blank" rel="noopener noreferrer">
                  {item.path}
                </a>
              ) : (
                item.path
              )}
            </td>
            <td><Badge variant={STATUS_VARIANT[item.status] ?? "neutral"}>{t(`itemStatus.${item.status}`)}</Badge></td>
            <td>{item.result_code && t.has(`codes.${item.result_code}`) ? t(`codes.${item.result_code}`) : item.result_code ?? ""}</td>
            <td>{item.tags.join(", ")}</td>
            <td>
              {item.estimated_date ? formatDate(item.estimated_date) : ""}
              {item.estimated_date && item.date_source === "takeout" ? <span className="muted"> ({t("preview.fromTakeout")})</span> : null}
            </td>
            <td>{formatFileSize(item.size, locale)}</td>
          </tr>
        ))}
      </DataTable>
      <Pagination offset={offset} limit={PAGE_SIZE} total={total} onOffsetChange={setOffset} />
    </section>
  );
}
