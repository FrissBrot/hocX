"use client";

import { useEffect, useRef, useState } from "react";

import { findUploadRuleProblems, UploadTargetFields, useUploadTarget } from "@/components/files/upload-target-fields";
import { Modal } from "@/components/ui/modal";
import { TagInput } from "@/components/ui/tag-input";
import { browserApiFetch } from "@/lib/api/client";
import { formatFileSize } from "@/lib/utils/format";
import { GalleryUploadJob } from "@/types/api";

const GALLERY_UPLOAD_ACCEPT = "image/jpeg,image/png,image/gif,image/webp,image/bmp,image/tiff,.zip";

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
// generic archive icon for those instead, see ZipIcon above).
function useFilePreviews(files: File[]): (string | null)[] {
  const [previews, setPreviews] = useState<(string | null)[]>([]);

  useEffect(() => {
    const urls = files.map((file) => (file.type.startsWith("image/") ? URL.createObjectURL(file) : null));
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
  onClose,
  onQueued,
}: {
  tagSuggestions: string[];
  onClose: () => void;
  // Fires as soon as the raw upload is safely staged and a gallery_upload_job is queued -
  // scanning/thumbnailing/import happen afterwards, in the background (see
  // gallery-upload-progress.tsx), so this is not the final result.
  onQueued: (job: GalleryUploadJob) => void;
}) {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const previews = useFilePreviews(selectedFiles);
  const [tagsValue, setTagsValue] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Optional target picker: land this batch straight in its Termin's/Abgabe-Element's/
  // Zyklus' auto-album (see photo_album_service.py) instead of only the plain gallery. An
  // Abgabe-Element also brings that Abgabe's file rules along (target.rules).
  const target = useUploadTarget();

  function addFiles(fileList: FileList | File[]) {
    // Copy now: an <input>'s FileList is live and gets emptied by the `value = ""` reset in
    // onChange, which runs before React invokes the state updater below.
    const added = Array.from(fileList);
    setSelectedFiles((current) => [...current, ...added]);
    setError(null);
  }

  function removeFile(index: number) {
    setSelectedFiles((current) => current.filter((_, i) => i !== index));
  }

  // A ZIP is only a carrier for images - the backend judges its entries once it opens it.
  const ruleProblems = findUploadRuleProblems(selectedFiles, target.rules, true);

  const totalBytes = selectedFiles.reduce((sum, file) => sum + file.size, 0);

  async function handleUpload() {
    if (selectedFiles.length === 0 || uploading || target.incomplete || ruleProblems.length > 0) return;
    setUploading(true);
    setError(null);
    try {
      const body = new FormData();
      selectedFiles.forEach((file) => body.append("files", file));
      body.append("tags", tagsValue);
      target.appendTo(body);
      // Returns almost immediately once the upload is staged and a gallery_upload_job is
      // queued - scanning/import happen afterwards in the background (see
      // gallery-upload-progress.tsx), so this request only has to cover the raw byte
      // transfer, not the full processing time.
      const job = await browserApiFetch<GalleryUploadJob>("/api/files/gallery-uploads", {
        method: "POST",
        body,
        // browserApiFetch's default 15s timeout is far too short for a multi-GB ZIP
        // transfer - mirrors the same fix already applied to admin-tenant-management.tsx's
        // import upload.
        signal: AbortSignal.timeout(600_000),
      });
      if (job) onQueued(job);
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Upload fehlgeschlagen");
    } finally {
      setUploading(false);
    }
  }

  return (
    <Modal
      open
      title="Bilder hochladen"
      description="Die Bilder landen in der Galerie und werden beim Upload virengeprüft."
      onClose={onClose}
      className="gallery-upload-modal"
    >
      <div className="gallery-upload">
        <div className="gallery-upload-scroll">
          <UploadTargetFields target={target} />

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
              if (event.dataTransfer.files.length > 0) addFiles(event.dataTransfer.files);
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
              {isDragging ? "Zum Hochladen loslassen" : "Bilder hierher ziehen"}
            </p>
            <p className="muted">
              oder <span className="gallery-upload-browse">Dateien auswählen</span>
            </p>
            <div className="gallery-upload-formats" aria-label="Unterstützte Formate">
              {["JPG", "PNG", "GIF", "WebP", "BMP", "TIFF", "ZIP"].map((format) => (
                <span key={format}>{format}</span>
              ))}
            </div>
          </div>

          <div>
            <div className="gallery-upload-queue-heading">
              <span className="gallery-upload-label">Warteschlange</span>
              <span className="gallery-upload-count">
                {selectedFiles.length === 0
                  ? "Keine Datei gewählt"
                  : selectedFiles.length === 1
                    ? "1 Datei gewählt"
                    : `${selectedFiles.length} Dateien gewählt`}
              </span>
            </div>
            {selectedFiles.length === 0 ? (
              <p className="gallery-upload-empty">Noch keine Dateien ausgewählt.</p>
            ) : (
              <ul className="gallery-upload-file-list">
                {selectedFiles.map((file, index) => (
                  <li key={`${file.name}-${index}`}>
                    <div className="gallery-upload-thumbnail">
                      {previews[index] ? (
                        <img src={previews[index] ?? undefined} alt="" />
                      ) : (
                        <div className="gallery-upload-thumbnail-fallback">
                          <ZipIcon />
                        </div>
                      )}
                    </div>
                    <div className="gallery-upload-file-details">
                      <div className="gallery-upload-file-heading">
                        <span className="gallery-upload-file-name" title={file.name}>{file.name}</span>
                        <span className="muted">{formatFileSize(file.size)}</span>
                      </div>
                      <span className="gallery-upload-file-status">
                        {uploading ? "Wird hochgeladen…" : "Bereit zum Hochladen"}
                      </span>
                      {uploading && <progress className="gallery-upload-progress" />}
                    </div>
                    <button
                      type="button"
                      className="gallery-upload-remove"
                      onClick={() => removeFile(index)}
                      disabled={uploading}
                      aria-label={`${file.name} entfernen`}
                    >
                      <CloseIcon />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="gallery-upload-tags">
            <span className="gallery-upload-label">Tags für alle Bilder</span>
            <TagInput value={tagsValue} onChange={setTagsValue} suggestions={tagSuggestions} placeholder="Tag hinzufügen…" />
          </div>

          {ruleProblems.length > 0 && <p className="form-error-banner">{ruleProblems.join(" · ")}</p>}
          {error && <p className="form-error-banner">{error}</p>}
        </div>

        <div className="gallery-upload-footer">
          <span className="gallery-upload-summary">
            {selectedFiles.length} Datei{selectedFiles.length === 1 ? "" : "en"}
            {selectedFiles.length > 0 ? ` · ${formatFileSize(totalBytes)}` : ""}
          </span>
          <div className="gallery-upload-actions">
            <button type="button" className="button-ghost" onClick={onClose} disabled={uploading}>
              Abbrechen
            </button>
            <button
              type="button"
              className="button-inline"
              onClick={() => void handleUpload()}
              disabled={uploading || selectedFiles.length === 0 || target.incomplete || ruleProblems.length > 0}
            >
              {uploading
                ? "Lädt hoch…"
                : selectedFiles.length > 0
                  ? `${selectedFiles.length} ${selectedFiles.length === 1 ? "Bild" : "Bilder"} hochladen`
                  : "Hochladen"}
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
