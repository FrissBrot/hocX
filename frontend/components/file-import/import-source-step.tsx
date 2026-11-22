"use client";

import { useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Select } from "@/components/ui/select";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch, browserApiUpload, LONG_RUNNING_TIMEOUT_MS } from "@/lib/api/client";
import {
  apiErrorCode,
  chunk,
  pathedFromDataTransfer,
  pathedFromInput,
  type ImportJob,
  type ImportSource,
  type ImportTypeFilter,
  type PathedFile,
} from "@/lib/files/file-import";
import { formatFileSize, formatInteger } from "@/lib/utils/format";

const MANIFEST_CHUNK = 5000;
const MAX_FOLDER_FILES = 50_000;
// Ein ZIP-Upload kann bei 10 GB lange dauern - wie beim Galerie-Upload.
const ARCHIVE_TIMEOUT_MS = 6 * 60 * 60 * 1000;

type Props = {
  job: ImportJob | null;
  blocked: boolean;
  onJob: (job: ImportJob) => void;
  onFiles: (files: PathedFile[]) => void;
  onCancelled: () => void | Promise<void>;
};

export function ImportSourceStep({ job, blocked, onJob, onFiles, onCancelled }: Props) {
  const t = useTranslations("fileImport");
  const locale = useLocale();
  const showToast = useToast();
  const confirm = useConfirm();
  const [source, setSource] = useState<ImportSource>("zip");
  const [typeFilter, setTypeFilter] = useState<ImportTypeFilter>("all");
  const [includeGps, setIncludeGps] = useState(true);
  const [folderTags, setFolderTags] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const zipInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);

  function errorText(error: unknown): string {
    const code = apiErrorCode(error);
    return code && t.has(`errors.${code}`) ? t(`errors.${code}`) : error instanceof Error ? error.message : t("errors.generic");
  }

  async function createJob() {
    setBusy(true);
    try {
      const created = await browserApiFetch<ImportJob>("/api/cloud-import/jobs", {
        method: "POST",
        body: JSON.stringify({ source, type_filter: typeFilter, include_gps: includeGps, folder_tags: folderTags }),
      });
      onJob(created);
    } catch (error) {
      showToast(errorText(error), "error");
    } finally {
      setBusy(false);
    }
  }

  async function uploadArchives(files: File[]) {
    if (!job) return;
    const archives = files.filter((file) => file.name.toLowerCase().endsWith(".zip"));
    if (!archives.length) {
      showToast(t("errors.zip_invalid"), "error");
      return;
    }
    setBusy(true);
    let current = job;
    try {
      for (const archive of archives) {
        const body = new FormData();
        body.append("file", archive);
        setProgress(0);
        current = await browserApiUpload<ImportJob>(`/api/cloud-import/uploads/${current.id}/archive`, body, {
          timeoutMs: ARCHIVE_TIMEOUT_MS,
          onProgress: (loaded, total) => setProgress(total ? Math.round((loaded / total) * 100) : null),
        });
        onJob(current);
      }
      showToast(t("source.archiveAdded", { count: archives.length }), "success");
    } catch (error) {
      showToast(errorText(error), "error");
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }

  async function sendFolder(files: PathedFile[]) {
    if (!job || !files.length) return;
    if (files.length > MAX_FOLDER_FILES) {
      showToast(t("errors.too_many_files", { max: formatInteger(MAX_FOLDER_FILES, locale) }), "error");
      return;
    }
    setBusy(true);
    try {
      onFiles(files);
      const parts = chunk(files, MANIFEST_CHUNK);
      let current = job;
      for (const [index, part] of parts.entries()) {
        setProgress(Math.round((index / parts.length) * 100));
        current = await browserApiFetch<ImportJob>(`/api/cloud-import/jobs/${current.id}/manifest`, {
          method: "POST",
          timeoutMs: LONG_RUNNING_TIMEOUT_MS,
          body: JSON.stringify({
            entries: part.map((entry) => ({
              path: entry.path,
              size: entry.file.size,
              modified_at: entry.file.lastModified ? new Date(entry.file.lastModified).toISOString() : null,
            })),
          }),
        });
      }
      onJob(await finishListing(current));
    } catch (error) {
      showToast(errorText(error), "error");
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }

  async function finishListing(current: ImportJob): Promise<ImportJob> {
    return browserApiFetch<ImportJob>(`/api/cloud-import/jobs/${current.id}/finish-listing`, { method: "POST" });
  }

  async function handleContinue() {
    if (!job) return;
    setBusy(true);
    try {
      onJob(await finishListing(job));
    } catch (error) {
      showToast(errorText(error), "error");
    } finally {
      setBusy(false);
    }
  }

  async function handleCancel() {
    if (!job) return;
    const ok = await confirm({ tone: "danger", message: t("cancel.draftConfirm"), confirmLabel: t("cancel.label") });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/cloud-import/jobs/${job.id}/cancel`, { method: "POST" });
      await onCancelled();
    } catch (error) {
      showToast(errorText(error), "error");
    }
  }

  if (!job) {
    return (
      <section className="section-card file-import-card">
        <h2 className="section-title">{t("source.title")}</h2>
        {blocked ? <StatusBanner tone="warning" message={t("errors.import_active")} /> : null}
        <div className="file-import-source-tiles" role="radiogroup" aria-label={t("source.title")}>
          {(["zip", "folder"] as const).map((value) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={source === value}
              className={source === value ? "file-import-tile file-import-tile-selected" : "file-import-tile"}
              onClick={() => setSource(value)}
            >
              <span className="file-import-tile-title">{t(`source.${value}`)}</span>
              <span className="file-import-tile-text">{t(`source.${value}Hint`)}</span>
            </button>
          ))}
        </div>
        <p className="muted">{t("source.cloudHint")}</p>
        <div className="grid file-import-options">
          <label className="field-stack">
            <span className="field-label">{t("options.typeFilter")}</span>
            <Select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as ImportTypeFilter)}>
              <option value="all">{t("options.types.all")}</option>
              <option value="images">{t("options.types.images")}</option>
              <option value="documents">{t("options.types.documents")}</option>
            </Select>
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={includeGps} onChange={(event) => setIncludeGps(event.target.checked)} />
            {t("options.includeGps")}
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={folderTags} onChange={(event) => setFolderTags(event.target.checked)} />
            {t("options.folderTags")}
          </label>
        </div>
        <p className="field-help">{t("source.limits")}</p>
        <div className="modal-actions">
          <button type="button" className="button-primary" disabled={busy || blocked} onClick={() => void createJob()}>
            {t("source.next")}
          </button>
        </div>
      </section>
    );
  }

  const isZip = job.source === "zip";
  return (
    <section
      className="section-card file-import-card"
      onDragOver={(event) => { event.preventDefault(); setIsDragging(true); }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setIsDragging(false);
        if (busy) return;
        if (isZip) void uploadArchives(Array.from(event.dataTransfer.files));
        else void pathedFromDataTransfer(event.dataTransfer, MAX_FOLDER_FILES + 1).then(sendFolder);
      }}
    >
      <h2 className="section-title">{t(isZip ? "source.uploadZipTitle" : "source.uploadFolderTitle")}</h2>
      <p className="muted">{t(isZip ? "source.uploadZipHint" : "source.uploadFolderHint")}</p>
      <div className={isDragging ? "file-import-drop file-import-drop-active" : "file-import-drop"}>
        <p>{t(isZip ? "source.dropZip" : "source.dropFolder")}</p>
        <input
          ref={zipInput}
          type="file"
          accept=".zip,application/zip"
          multiple
          hidden
          onChange={(event) => {
            if (event.target.files) void uploadArchives(Array.from(event.target.files));
            event.target.value = "";
          }}
        />
        <input
          ref={folderInput}
          type="file"
          multiple
          hidden
          {...{ webkitdirectory: "" }}
          onChange={(event) => {
            if (event.target.files) void sendFolder(pathedFromInput(event.target.files));
            event.target.value = "";
          }}
        />
        <button
          type="button"
          className="button-secondary"
          disabled={busy}
          onClick={() => (isZip ? zipInput.current : folderInput.current)?.click()}
        >
          {t(isZip ? "source.chooseZip" : "source.chooseFolder")}
        </button>
      </div>
      {progress !== null ? (
        <progress className="gallery-upload-progress" max={100} value={progress} aria-label={t("source.progress")} />
      ) : busy ? (
        <progress className="gallery-upload-progress" aria-label={t("source.progress")} />
      ) : null}
      {job.total_items > 0 ? (
        <p className="file-import-listing-summary">
          {t("source.listed", {
            count: job.total_items,
            size: formatFileSize(job.total_bytes, locale),
            archives: job.archives,
          })}
          {job.takeout ? ` ${t("source.takeoutDetected")}` : null}
        </p>
      ) : null}
      <div className="modal-actions">
        <button type="button" className="button-ghost" disabled={busy} onClick={() => void handleCancel()}>
          {t("cancel.label")}
        </button>
        {isZip ? (
          <button type="button" className="button-primary" disabled={busy || job.total_items === 0} onClick={() => void handleContinue()}>
            {t("source.toRules")}
          </button>
        ) : null}
      </div>
    </section>
  );
}
