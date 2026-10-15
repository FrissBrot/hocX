"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { AlbumReleaseNotice } from "./album-share-release";
import { findUploadRuleProblems, UploadTargetFields, useUploadTarget } from "@/components/files/upload-target-fields";
import { todayIso } from "@/components/mobile/mobile-utils";
import { DateInput } from "@/components/ui/date-input";
import { Modal } from "@/components/ui/modal";
import { TagInput } from "@/components/ui/tag-input";
import { browserApiFetch, browserApiUpload } from "@/lib/api/client";
import { FileAnalysis } from "@/lib/image-analysis/analyze";
import { analyzeFiles } from "@/lib/image-analysis/pool";
import { fileMetadataHints, needsUpload, precheckToFileResult, precheckUploads } from "@/lib/image-analysis/precheck";
import { filesFromDataTransfer, isGalleryCandidate } from "@/lib/utils/folder-files";
import { formatDateInputValue, formatFileSize } from "@/lib/utils/format";
import { isHeicName, isLiveClipName, pairLiveClips } from "@/lib/utils/live-photo";
import { photoUploadProblem, PHOTO_MAX_FILES, PHOTO_UPLOAD_TIMEOUT_MS, PHOTO_ZIP_MAX_BYTES } from "@/lib/utils/upload-limits";
import { splitIntoBatches } from "@/lib/utils/upload-results";
import { GalleryUploadJob, SharedTargetAlbum, UploadFileResult } from "@/types/api";

// Status einer Datei im Popup: vor dem Upload "ready", danach je nach Vorab-Abgleich bzw. Batch.
type FileUploadState = "ready" | "skipped" | "metadata_updated" | "waiting" | "uploading" | "uploaded" | "failed";

export type GalleryUploadSession = {
  // Alle in diesem Vorgang angelegten Upload-Aufträge (einer je Batch).
  jobIds: string[];
  // Dateien, die der Vorab-Abgleich bereits erledigt hat (nicht übertragen).
  precheckResults: UploadFileResult[];
};

// HEIC/HEIF (iPhone) und .mov (Live-Photo-Clip) stehen mit Endung da, weil Browser ausser Safari dafür
// keinen MIME-Typ melden. Der Clip wird nur zusammen mit dem gleichnamigen Bild angenommen.
const GALLERY_UPLOAD_ACCEPT = "image/jpeg,image/png,image/gif,image/webp,image/bmp,image/tiff,image/heic,image/heif,.heic,.heif,video/quicktime,.mov,.zip";

function UploadIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 16V5m0 0-4 4m4-4 4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5 15v2.5A1.5 1.5 0 0 0 6.5 19h11a1.5 1.5 0 0 0 1.5-1.5V15" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true" width="14" height="14">
      <path d="m4 4 8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function ClipIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" width="22" height="22">
      <rect x="3" y="5" width="18" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" />
      <path d="m10 9.5 4.5 2.5-4.5 2.5z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

function ZipIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" width="22" height="22">
      <rect x="4" y="3" width="16" height="18" rx="2" stroke="currentColor" strokeWidth="1.5" />
      <path d="M11 3v2M13 5v2M11 7v2M13 9v2M11 11v2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="12" cy="15.5" r="1.8" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

// Per-file preview: an object URL for a real image, null for a ZIP (or anything else the
// browser can't thumbnail on its own without unpacking it first - the queue just shows a
// generic archive icon for those instead, see ZipIcon above). HEIC is skipped too: outside
// Safari the browser can't decode it, so the <img> would only show a broken-image icon.
function useFilePreviews(files: File[]): (string | null)[] {
  const [previews, setPreviews] = useState<(string | null)[]>([]);

  useEffect(() => {
    const urls = files.map((file) =>
      file.type.startsWith("image/") && !isHeicName(file.name) && !/^image\/hei[cf]/.test(file.type) ? URL.createObjectURL(file) : null,
    );
    setPreviews(urls);
    return () => {
      urls.forEach((url) => {
        if (url) URL.revokeObjectURL(url);
      });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files]);

  return previews;
}

export function GalleryUploadModal({
  tagSuggestions,
  initialFiles,
  onClose,
  onQueued,
  onSessionComplete,
}: {
  tagSuggestions: string[];
  // Files dropped onto the page before this dialog opened - they start out in the queue.
  initialFiles?: File[];
  onClose: () => void;
  // Fires as soon as the raw upload is safely staged and a gallery_upload_job is queued -
  // scanning/thumbnailing/import happen afterwards, in the background (see
  // gallery-upload-progress.tsx), so this is not the final result. Once per batch.
  onQueued: (job: GalleryUploadJob) => void;
  // Fires once per upload, after the last batch is queued (or right away when the precheck
  // found every file already present) - lets the page combine precheck and job results.
  onSessionComplete?: (session: GalleryUploadSession) => void;
}) {
  // "files"-Namespace: findUploadRuleProblems/UploadTargetFields liefern ihre Texte darüber
  // (siehe components/files/upload-target-fields.tsx), unabhängig vom restlichen "photos"-
  // Namespace dieser Datei.
  const t = useTranslations("photos.galleryUpload");
  const tFiles = useTranslations("files");
  const [selectedFiles, setSelectedFiles] = useState<File[]>(initialFiles ?? []);
  const previews = useFilePreviews(selectedFiles);
  const [tagsValue, setTagsValue] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  // Bytes of the multipart body sent so far (null until the browser reports the first chunk).
  const [progress, setProgress] = useState<{ loaded: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  // Lokale Analyse (SHA-256 + Metadaten) im Web Worker, sobald Dateien gewählt sind. Ergebnisse
  // hängen am File-Objekt, damit Hinzufügen/Entfernen nichts doppelt einliest.
  const analysisCache = useRef(new WeakMap<File, FileAnalysis>());
  const analysisRun = useRef<Promise<void> | null>(null);
  const [analysisVersion, setAnalysisVersion] = useState(0);
  const [analysisProgress, setAnalysisProgress] = useState<{ done: number; total: number } | null>(null);
  const [estimatedDate, setEstimatedDate] = useState("");
  const [checking, setChecking] = useState(false);
  const [fileStates, setFileStates] = useState<FileUploadState[]>([]);
  const [batchInfo, setBatchInfo] = useState<{ current: number; total: number; indexes: number[] } | null>(null);
  const uploadAbort = useRef<AbortController | null>(null);

  useEffect(() => {
    const pending = selectedFiles.filter((file) => !analysisCache.current.has(file));
    if (pending.length === 0) {
      setAnalysisProgress(null);
      return;
    }
    const controller = new AbortController();
    setAnalysisProgress({ done: 0, total: pending.length });
    const run = analyzeFiles(pending, {
      signal: controller.signal,
      onProgress: (progressValue) => setAnalysisProgress(progressValue),
      onResult: (index, result) => {
        analysisCache.current.set(pending[index], result);
        setAnalysisVersion((version) => version + 1);
      },
    })
      .then(() => setAnalysisProgress(null))
      .catch(() => {
        // Abgebrochen (Auswahl geändert/Popup geschlossen) - nicht analysierte Dateien gehen
        // ohne Vorab-Abgleich hoch.
      });
    analysisRun.current = run;
    return () => controller.abort();
  }, [selectedFiles]);

  const analyses = useMemo(
    () => selectedFiles.map((file) => analysisCache.current.get(file)),
    // analysisVersion: neu berechnen, sobald ein weiteres Ergebnis vorliegt.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selectedFiles, analysisVersion],
  );
  const analyzing = analysisProgress !== null;
  const imageAnalyses = analyses.filter((analysis) => analysis?.kind === "image");
  const missingDateCount = imageAnalyses.filter((analysis) => analysis?.captureDate === "missing").length;
  const uncheckedCount = imageAnalyses.filter((analysis) => analysis && analysis.captureDate === "unknown").length;
  const zipCount = selectedFiles.filter((file) => /\.zip$/i.test(file.name)).length;
  const showEstimate = missingDateCount > 0 || uncheckedCount > 0 || zipCount > 0;

  // Optional target picker: land this batch straight in its Termin's/Abgabe-Element's/
  // Zyklus' auto-album (see photo_album_service.py) instead of only the plain gallery. An
  // Abgabe-Element also brings that Abgabe's file rules along (target.rules).
  const target = useUploadTarget();

  // Fällt der gewählte Bezug in ein schon geteiltes Auto-Album, landen die Bilder dort ohne
  // Bestätigung nur vorgemerkt (erst nach Freigabe für die Partner sichtbar). Hier lässt sich
  // die Freigabe direkt mitgeben.
  const [sharedTargets, setSharedTargets] = useState<SharedTargetAlbum[]>([]);
  const [releaseShared, setReleaseShared] = useState(false);
  let targetQuery = "";
  if (target.targetKind !== "none" && !target.incomplete) {
    const fields = new FormData();
    target.appendTo(fields);
    const params = new URLSearchParams();
    fields.forEach((value, key) => params.append(key, String(value)));
    targetQuery = params.toString();
  }
  useEffect(() => {
    setReleaseShared(false);
    if (!targetQuery) {
      setSharedTargets([]);
      return;
    }
    let cancelled = false;
    browserApiFetch<SharedTargetAlbum[]>(`/api/files/upload-target-shared-albums?${targetQuery}`)
      .then((data) => {
        if (!cancelled) setSharedTargets(data ?? []);
      })
      .catch(() => {
        if (!cancelled) setSharedTargets([]);
      });
    return () => {
      cancelled = true;
    };
  }, [targetQuery]);

  function addFiles(fileList: FileList | File[], fromFolder = false) {
    // Copy now: an <input>'s FileList is live and gets emptied by the `value = ""` reset in
    // onChange, which runs before React invokes the state updater below.
    const added = Array.from(fileList).filter((file) => !fromFolder || isGalleryCandidate(file));
    setSelectedFiles((current) => [...current, ...added]);
    setFileStates([]);
    setError(null);
  }

  function removeFile(index: number) {
    setSelectedFiles((current) => current.filter((_, i) => i !== index));
    setFileStates([]);
  }

  // A ZIP is only a carrier for images - the backend judges its entries once it opens it.
  // A Live Photo's clip (IMG_1.MOV next to IMG_1.HEIC) is part of that photo, not a file of its own -
  // neither for the Abgabe's rules nor for the count on the button.
  const clipIndexes = useMemo(() => new Set(pairLiveClips(selectedFiles.map((file) => file.name)).values()), [selectedFiles]);
  const photoCount = selectedFiles.length - clipIndexes.size;
  const ruleProblems = findUploadRuleProblems(
    selectedFiles.filter((_, index) => !clipIndexes.has(index)),
    target.rules,
    tFiles,
    true,
  );

  const sizeProblem = photoUploadProblem(selectedFiles, clipIndexes);
  if (sizeProblem) ruleProblems.push(sizeProblem);

  const totalBytes = selectedFiles.reduce((sum, file) => sum + file.size, 0);
  const uploadPercent = progress && progress.total > 0 ? Math.min(100, Math.round((progress.loaded / progress.total) * 100)) : null;
  // All bytes are out, but the server is still staging the upload and queueing the job.
  const transferDone = progress !== null && progress.loaded >= progress.total;

  // The multipart body carries the batch's files back to back in queue order, so each file's
  // share of the transferred bytes follows from its offset within the current batch
  // (boundaries/headers are negligible next to it).
  function fileSentBytes(index: number): number {
    if (!progress || !batchInfo) return 0;
    const position = batchInfo.indexes.indexOf(index);
    if (position < 0) return 0;
    const offset = batchInfo.indexes.slice(0, position).reduce((sum, member) => sum + selectedFiles[member].size, 0);
    return Math.max(0, Math.min(selectedFiles[index].size, progress.loaded - offset));
  }

  function setStates(indexes: number[], state: FileUploadState) {
    setFileStates((current) => {
      const next = current.length === selectedFiles.length ? [...current] : selectedFiles.map((): FileUploadState => "ready");
      indexes.forEach((index) => { next[index] = state; });
      return next;
    });
  }

  async function handleUpload() {
    if (selectedFiles.length === 0 || uploading || checking || target.incomplete || ruleProblems.length > 0) return;
    setError(null);
    setChecking(true);
    const controller = new AbortController();
    uploadAbort.current = controller;
    const jobIds: string[] = [];
    const precheckResults: UploadFileResult[] = [];
    try {
      // 1. Laufende Analyse abwarten (bereits analysierte Dateien liegen im Cache).
      if (analysisRun.current) await analysisRun.current.catch(() => undefined);
      const fileAnalyses = selectedFiles.map((file) => analysisCache.current.get(file));
      const estimate = showEstimate && estimatedDate ? estimatedDate : null;

      // 2. Vorab-Abgleich: nur Hashes und Metadaten, keine Dateibytes.
      const clipOfImage = pairLiveClips(selectedFiles.map((file) => file.name));
      const entries = selectedFiles.flatMap((file, index) => {
        const analysis = fileAnalyses[index];
        return analysis?.sha256 && analysis.kind === "image" ? [{ index, file, analysis }] : [];
      });
      const precheck = entries.length
        ? await precheckUploads(entries, { context: "gallery", estimatedTakenOn: estimate, signal: controller.signal })
        : new Map();
      const skip = new Set<number>();
      for (const [index, result] of precheck ?? []) {
        if (needsUpload(result)) continue;
        skip.add(index);
        // Der Live-Clip eines vorhandenen Fotos wurde mit ihm gespeichert.
        const clip = clipOfImage.get(index);
        if (clip !== undefined) skip.add(clip);
        precheckResults.push(precheckToFileResult(selectedFiles[index].name, result));
      }
      setStates([...skip], "skipped");
      for (const [index, result] of precheck ?? []) {
        if (result.status === "metadata_updated") setStates([index], "metadata_updated");
      }
      setChecking(false);

      // 3. Verbleibende Dateien in Aufträgen zu je max. 50 Dateien übertragen.
      const uploadIndexes = selectedFiles.map((_, index) => index).filter((index) => !skip.has(index));
      if (uploadIndexes.length > 0) {
        setUploading(true);
        setStates(uploadIndexes, "waiting");
        const uploadFiles = uploadIndexes.map((index) => selectedFiles[index]);
        const batches = splitIntoBatches(uploadFiles, pairLiveClips(uploadFiles.map((file) => file.name)), PHOTO_MAX_FILES, PHOTO_ZIP_MAX_BYTES, (file) => file.size)
          .map((batch) => batch.map((position) => uploadIndexes[position]));
        for (const [batchNumber, batch] of batches.entries()) {
          setBatchInfo({ current: batchNumber + 1, total: batches.length, indexes: batch });
          setProgress(null);
          setStates(batch, "uploading");
          const body = new FormData();
          batch.forEach((index) => body.append("files", selectedFiles[index]));
          body.append("tags", tagsValue);
          target.appendTo(body);
          if (releaseShared && sharedTargets.length > 0) body.append("release_to_shared_albums", "true");
          if (estimate) body.append("estimated_taken_on", estimate);
          const hints = fileMetadataHints(batch.map((index) => fileAnalyses[index]).filter((analysis): analysis is FileAnalysis => Boolean(analysis)));
          if (hints) body.append("file_metadata", hints);
          // Returns almost immediately once the upload is staged and a gallery_upload_job is
          // queued - scanning/import happen afterwards in the background (see
          // gallery-upload-progress.tsx). XHR instead of browserApiFetch so the byte transfer
          // can report progress.
          const job = await browserApiUpload<GalleryUploadJob>("/api/files/gallery-uploads", body, {
            timeoutMs: PHOTO_UPLOAD_TIMEOUT_MS,
            onProgress: (loaded, total) => setProgress({ loaded, total }),
            signal: controller.signal,
          });
          setStates(batch, "uploaded");
          if (job) {
            jobIds.push(job.id);
            onQueued(job);
          }
        }
      }
      onSessionComplete?.({ jobIds, precheckResults });
      onClose();
    } catch (err: unknown) {
      const aborted = err instanceof DOMException && err.name === "AbortError";
      // Bereits angelegte Aufträge laufen weiter - ihr Ergebnis gehört trotzdem zu diesem Vorgang.
      if (jobIds.length || precheckResults.length) onSessionComplete?.({ jobIds, precheckResults });
      if (aborted) {
        onClose();
        return;
      }
      setError(err instanceof Error ? err.message : t("uploadFailed"));
      setFileStates((current) => current.map((state) => (state === "uploading" || state === "waiting" ? "failed" : state)));
    } finally {
      setChecking(false);
      setUploading(false);
      setProgress(null);
      setBatchInfo(null);
      uploadAbort.current = null;
    }
  }

  function handleCancel() {
    if (uploadAbort.current) {
      uploadAbort.current.abort();
      return;
    }
    onClose();
  }

  function fileStatusLabel(index: number, file: File): string {
    const state = fileStates[index] ?? "ready";
    if (state === "skipped") return t("statusSkipped");
    if (state === "metadata_updated") return t("statusMetadataUpdated");
    if (state === "waiting") return t("statusWaiting");
    if (state === "failed") return t("statusFailed");
    if (state === "uploaded") return t("statusUploaded");
    if (state === "uploading") {
      if (transferDone) return t("statusUploaded");
      return progress ? t("statusUploadingProgress", { sent: formatFileSize(fileSentBytes(index)), total: formatFileSize(file.size) }) : t("statusUploading");
    }
    if (clipIndexes.has(index)) return t("statusClip");
    const analysis = analyses[index];
    if (analysis?.kind === "image" && analysis.captureDate === "missing") return t("statusReadyNoDate");
    if (analysis?.kind === "image" && analysis.captureDate === "unknown") return t("statusReadyUnchecked");
    return t("statusReady");
  }

  const busy = uploading || checking;

  return (
    <Modal
      open
      title={t("title")}
      description={t("description")}
      onClose={handleCancel}
      onEscape={() => (busy ? undefined : selectedFiles.length ? handleUpload() : onClose())}
      className="gallery-upload-modal"
    >
      <div className="gallery-upload">
        <div className="gallery-upload-scroll">
          <UploadTargetFields target={target} />

          {sharedTargets.length > 0 && (
            <div className="gallery-upload-share-release">
              <AlbumReleaseNotice
                message={t("shareNotice", { albums: sharedTargets.map((album) => `„${album.album_name}“`).join(", ") })}
              />
              <label className="checkbox-row">
                <input type="checkbox" checked={releaseShared} onChange={(event) => setReleaseShared(event.target.checked)} disabled={uploading} />
                {t("releaseCheckboxLabel")}
              </label>
            </div>
          )}

          <div
            className={`gallery-upload-dropzone${isDragging ? " gallery-upload-dropzone-active" : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setIsDragging(false);
              const dataTransfer = event.dataTransfer;
              // Ordner werden rekursiv aufgeklappt (nur Bilder, HEIC, Live-Clips und ZIPs).
              void filesFromDataTransfer(dataTransfer).then((files) => {
                if (files.length > 0) addFiles(files, files.length !== dataTransfer.files.length);
              });
            }}
            onClick={() => inputRef.current?.click()}
            role="button"
            tabIndex={0}
          >
            <input
              ref={inputRef}
              type="file"
              multiple
              accept={GALLERY_UPLOAD_ACCEPT}
              hidden
              onChange={(event) => {
                if (event.target.files) addFiles(event.target.files);
                event.target.value = "";
              }}
            />
            <span className="gallery-upload-dropzone-badge">
              <UploadIcon />
            </span>
            <p className="gallery-upload-dropzone-title">
              {isDragging ? t("dropActive") : t("dropHint")}
            </p>
            <input
              ref={folderInputRef}
              type="file"
              multiple
              hidden
              {...{ webkitdirectory: "" }}
              onChange={(event) => {
                if (event.target.files) addFiles(event.target.files, true);
                event.target.value = "";
              }}
            />
            <p className="muted">
              {t("orText")} <span className="gallery-upload-browse">{t("browse")}</span>
              {" · "}
              <button
                type="button"
                className="gallery-upload-folder"
                onClick={(event) => {
                  event.stopPropagation();
                  folderInputRef.current?.click();
                }}
              >
                {t("browseFolder")}
              </button>
            </p>
            <div className="gallery-upload-formats" aria-label={t("formatsAriaLabel")}>
              {["JPG", "PNG", "GIF", "WebP", "BMP", "TIFF", "HEIC", "Live Photo", "ZIP"].map((format) => (
                <span key={format}>{format}</span>
              ))}
            </div>
          </div>

          <div>
            <div className="gallery-upload-queue-heading">
              <span className="gallery-upload-label">{t("queueHeading")}</span>
              <span className="gallery-upload-count">
                {t("queueCount", { count: selectedFiles.length })}
              </span>
            </div>
            {selectedFiles.length === 0 ? (
              <p className="gallery-upload-empty">{t("queueEmpty")}</p>
            ) : (
              <ul className="gallery-upload-file-list">
                {selectedFiles.map((file, index) => (
                  <li key={`${file.name}-${index}`}>
                    <div className="gallery-upload-thumbnail">
                      {previews[index] ? (
                        <img src={previews[index] ?? undefined} alt="" />
                      ) : (
                        <div className="gallery-upload-thumbnail-fallback">
                          {isLiveClipName(file.name) ? <ClipIcon /> : <ZipIcon />}
                        </div>
                      )}
                    </div>
                    <div className="gallery-upload-file-details">
                      <div className="gallery-upload-file-heading">
                        <span className="gallery-upload-file-name" title={file.name}>{file.name}</span>
                        <span className="muted">{formatFileSize(file.size)}</span>
                      </div>
                      <span className="gallery-upload-file-status">{fileStatusLabel(index, file)}</span>
                      {fileStates[index] === "uploading" && (progress && !transferDone
                        ? <progress className="gallery-upload-progress" value={fileSentBytes(index)} max={file.size || 1} />
                        : <progress className="gallery-upload-progress" />)}
                    </div>
                    <button
                      type="button"
                      className="gallery-upload-remove"
                      onClick={() => removeFile(index)}
                      disabled={busy}
                      aria-label={t("removeAriaLabel", { name: file.name })}
                    >
                      <CloseIcon />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {analyzing && analysisProgress && (
            <div className="gallery-upload-analysis" role="status">
              <span>{t("analysisProgress", { done: analysisProgress.done, total: analysisProgress.total })}</span>
              <progress className="gallery-upload-progress" value={analysisProgress.done} max={analysisProgress.total || 1} />
            </div>
          )}

          {showEstimate && (
            <div className="gallery-upload-estimate">
              {missingDateCount > 0 && <p className="gallery-upload-estimate-hint">{t("estimate.missingHint", { count: missingDateCount })}</p>}
              {uncheckedCount > 0 && <p className="gallery-upload-estimate-hint">{t("estimate.uncheckedHint", { count: uncheckedCount })}</p>}
              {zipCount > 0 && <p className="gallery-upload-estimate-hint">{t("estimate.zipHint")}</p>}
              <label className="field-stack">
                <span className="field-label">{t("estimate.label")}</span>
                <DateInput value={estimatedDate} onChange={setEstimatedDate} max={todayIso()} disabled={busy} />
                <span className="field-help">
                  {estimatedDate ? t("estimate.helpSet", { date: formatDateInputValue(estimatedDate) }) : t("estimate.help")}
                </span>
              </label>
            </div>
          )}

          <div className="gallery-upload-tags">
            <span className="gallery-upload-label">{t("tagsLabel")}</span>
            <TagInput value={tagsValue} onChange={setTagsValue} suggestions={tagSuggestions} placeholder={t("tagsPlaceholder")} />
          </div>

          {ruleProblems.length > 0 && <p className="form-error-banner">{ruleProblems.join(" · ")}</p>}
          {error && <p className="form-error-banner">{error}</p>}
        </div>

        <div className="gallery-upload-footer">
          <span className="gallery-upload-summary">
            {t("summaryCount", { count: selectedFiles.length })}
            {selectedFiles.length > 0
              ? progress && !transferDone
                ? ` · ${t("summaryProgress", { sent: formatFileSize(progress.loaded), total: formatFileSize(progress.total) })}`
                : ` · ${formatFileSize(totalBytes)}`
              : ""}
            {batchInfo && batchInfo.total > 1 ? ` · ${t("batchProgress", { current: batchInfo.current, total: batchInfo.total })}` : ""}
          </span>
          <div className="gallery-upload-actions">
            <button type="button" className="button-ghost" onClick={handleCancel}>
              {t("cancel")}
            </button>
            <button
              type="button"
              className="button-secondary"
              onClick={() => void handleUpload()}
              disabled={busy || selectedFiles.length === 0 || target.incomplete || ruleProblems.length > 0}
            >
              {checking
                ? t("checkingPlain")
                : uploading
                  ? uploadPercent !== null && !transferDone ? t("uploadingPercent", { percent: uploadPercent }) : t("uploadingPlain")
                  : selectedFiles.length > 0
                    ? t("uploadCount", { count: photoCount })
                    : t("uploadPlain")}
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
