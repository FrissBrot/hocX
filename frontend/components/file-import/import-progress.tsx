"use client";

import { type MutableRefObject, useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch, browserApiUpload } from "@/lib/api/client";
import {
  apiErrorCode,
  importProgress,
  normalizeImportPath,
  pathedFromInput,
  uploadBatches,
  type ImportJob,
  type PathedFile,
} from "@/lib/files/file-import";
import { formatFileSize, formatInteger } from "@/lib/utils/format";

const POLL_MS = 3000;
const BATCH_FILES = 20;
const BATCH_BYTES = 200 * 1024 * 1024;
const BUSY_RETRY_MS = 10_000;
const UPLOAD_TIMEOUT_MS = 30 * 60 * 1000;

type Props = {
  job: ImportJob;
  onJob: (job: ImportJob) => void;
  folderFiles: MutableRefObject<Map<string, File>>;
  onFiles: (files: PathedFile[]) => void;
};

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export function ImportProgress({ job, onJob, folderFiles, onFiles }: Props) {
  const t = useTranslations("fileImport");
  const locale = useLocale();
  const showToast = useToast();
  const confirm = useConfirm();
  const [uploading, setUploading] = useState(false);
  const [missing, setMissing] = useState(0);
  const [uploadedBytes, setUploadedBytes] = useState(0);
  const folderInput = useRef<HTMLInputElement>(null);
  const uploadRun = useRef(false);

  const needsUpload = job.source === "folder" && job.is_owner;

  useEffect(() => {
    let stopped = false;
    const tick = async () => {
      try {
        const next = await browserApiFetch<ImportJob>(`/api/cloud-import/jobs/${job.id}`);
        if (!stopped) onJob(next);
      } catch {
        // Nächster Versuch beim nächsten Takt
      }
    };
    const timer = window.setInterval(() => void tick(), POLL_MS);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [job.id, onJob]);

  const uploadPending = useCallback(async () => {
    if (uploadRun.current) return;
    uploadRun.current = true;
    setUploading(true);
    let notFound = 0;
    try {
      for (;;) {
        const page = await browserApiFetch<{ items: { path: string; size: number }[]; total: number }>(
          `/api/cloud-import/jobs/${job.id}/pending-uploads?offset=${notFound}&limit=500`,
        );
        if (!page.items.length) break;
        const ready: PathedFile[] = [];
        for (const item of page.items) {
          const file = folderFiles.current.get(item.path) ?? folderFiles.current.get(normalizeImportPath(item.path));
          if (file) ready.push({ path: item.path, file });
          else notFound += 1;
        }
        setMissing(notFound);
        if (!ready.length) {
          if (notFound >= page.total) break;
          continue;
        }
        for (const batch of uploadBatches(ready, BATCH_FILES, BATCH_BYTES)) {
          const body = new FormData();
          for (const entry of batch) body.append("files", entry.file, entry.file.name);
          body.append("paths", JSON.stringify(batch.map((entry) => entry.path)));
          for (;;) {
            try {
              await browserApiUpload(`/api/cloud-import/uploads/${job.id}/files`, body, { timeoutMs: UPLOAD_TIMEOUT_MS });
              setUploadedBytes((value) => value + batch.reduce((sum, entry) => sum + entry.file.size, 0));
              break;
            } catch (error) {
              // Zu viele gestagte Dateien: der Server importiert noch - kurz warten
              if (apiErrorCode(error) === "staging_busy") {
                await wait(BUSY_RETRY_MS);
                continue;
              }
              throw error;
            }
          }
        }
      }
    } catch (error) {
      const code = apiErrorCode(error);
      if (code !== "invalid_status") {
        showToast(code && t.has(`errors.${code}`) ? t(`errors.${code}`) : error instanceof Error ? error.message : t("errors.generic"), "error");
      }
    } finally {
      uploadRun.current = false;
      setUploading(false);
    }
  }, [folderFiles, job.id, showToast, t]);

  useEffect(() => {
    if (needsUpload && folderFiles.current.size && job.status !== "cancel_requested") void uploadPending();
    // Nur beim Öffnen bzw. nach neuer Ordnerwahl starten
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needsUpload, job.id]);

  async function handleCancel() {
    const ok = await confirm({ tone: "danger", message: t("cancel.runningConfirm"), confirmLabel: t("cancel.label") });
    if (!ok) return;
    try {
      onJob(await browserApiFetch<ImportJob>(`/api/cloud-import/jobs/${job.id}/cancel`, { method: "POST" }));
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("errors.generic"), "error");
    }
  }

  const percent = importProgress(job);
  const counts = job.counts;
  const waitingForBrowser = needsUpload && (counts.queued ?? 0) > 0;
  const lostFiles = waitingForBrowser && !uploading && (folderFiles.current.size === 0 || missing > 0);

  return (
    <section className="section-card file-import-card" aria-live="polite">
      <h2 className="section-title">{t("progress.title")}</h2>
      <p className="muted">{t(job.status === "cancel_requested" ? "progress.cancelling" : "progress.hint")}</p>
      <progress className="gallery-upload-progress" max={100} value={percent} aria-label={t("progress.title")} />
      <p className="file-import-stats">
        <span>{t("progress.percent", { percent })}</span>
        <span>{t("progress.imported", { count: counts.imported ?? 0 })}</span>
        <span>{t("progress.duplicates", { count: counts.duplicate ?? 0 })}</span>
        <span>{t("progress.failed", { count: counts.failed ?? 0 })}</span>
        <span>{t("progress.open", { count: (counts.queued ?? 0) + (counts.staged ?? 0) })}</span>
      </p>
      {needsUpload && uploading ? (
        <StatusBanner tone="neutral" message={t("progress.uploading", { size: formatFileSize(uploadedBytes, locale) })} />
      ) : null}
      {lostFiles ? (
        <div className="file-import-reselect">
          <StatusBanner tone="warning" message={t("progress.reselect", { count: formatInteger(counts.queued ?? 0, locale) })} />
          <input
            ref={folderInput}
            type="file"
            multiple
            hidden
            {...{ webkitdirectory: "" }}
            onChange={(event) => {
              if (event.target.files) {
                onFiles(pathedFromInput(event.target.files));
                setMissing(0);
                void uploadPending();
              }
              event.target.value = "";
            }}
          />
          <button type="button" className="button-secondary" onClick={() => folderInput.current?.click()}>
            {t("source.chooseFolder")}
          </button>
        </div>
      ) : null}
      {!needsUpload && job.source === "folder" && (counts.queued ?? 0) > 0 ? (
        <StatusBanner tone="neutral" message={t("progress.waitingForOwner")} />
      ) : null}
      {job.status === "cancel_requested" ? null : (
        <div className="modal-actions">
          <button type="button" className="button-danger" onClick={() => void handleCancel()}>{t("cancel.running")}</button>
        </div>
      )}
    </section>
  );
}
