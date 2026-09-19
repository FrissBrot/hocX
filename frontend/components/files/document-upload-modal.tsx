"use client";

import { useRef, useState } from "react";

import { findUploadRuleProblems, UploadTargetFields, useUploadTarget } from "./upload-target-fields";
import { Modal } from "@/components/ui/modal";
import { TagInput } from "@/components/ui/tag-input";
import { browserApiFetch } from "@/lib/api/client";
import { formatFileSize } from "@/lib/utils/format";
import { DocumentUploadResult } from "@/types/api";

// Mirrors DOCUMENT_UPLOAD_EXTENSIONS in backend/app/services/upload_pipeline.py - the backend
// re-checks every file's actual content, this list only spares a pointless round trip.
const DOCUMENT_EXTENSIONS = [
  ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp", ".rtf", ".txt", ".csv", ".md", ".zip",
];
const DOCUMENT_FORMATS = ["PDF", "Word", "Excel", "PowerPoint", "ODF", "RTF", "TXT", "CSV", "ZIP"];
const IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"];

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
}

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

function DocumentIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" width="22" height="22" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" />
      <path d="M14 3v5h5" />
    </svg>
  );
}

export function DocumentUploadModal({
  tagSuggestions,
  onClose,
  onUploaded,
}: {
  tagSuggestions: string[];
  onClose: () => void;
  // Fires once at least one file was saved. Unlike the photo upload there is no background
  // job (a document is scanned and stored inside the request itself), so `result` is final -
  // it can still carry per-file `errors` for the files that were rejected.
  onUploaded: (result: DocumentUploadResult) => void;
}) {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [tagsValue, setTagsValue] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const target = useUploadTarget();

  function addFiles(fileList: FileList | File[]) {
    // Copy now: an <input>'s FileList is live and gets emptied by the `value = ""` reset in
    // onChange, which runs before React invokes the state updater below.
    const candidates = Array.from(fileList);
    const accepted = candidates.filter((file) => DOCUMENT_EXTENSIONS.includes(extensionOf(file.name)));
    const rejected = candidates.filter((file) => !accepted.includes(file));
    setSelectedFiles((current) => [...current, ...accepted]);
    if (rejected.length === 0) {
      setError(null);
    } else if (rejected.every((file) => IMAGE_EXTENSIONS.includes(extensionOf(file.name)))) {
      setError("Bilder bitte über die Fotos-Seite hochladen.");
    } else {
      setError(`Nicht unterstützt: ${rejected.map((file) => file.name).join(", ")}`);
    }
  }

  function removeFile(index: number) {
    setSelectedFiles((current) => current.filter((_, i) => i !== index));
  }

  const totalBytes = selectedFiles.reduce((sum, file) => sum + file.size, 0);
  // Re-derived on every render (not only when a file is added) since the Abgabe - and with it
  // the rules - can also be picked after the files were queued.
  const ruleProblems = findUploadRuleProblems(selectedFiles, target.rules);
  const acceptedExtensions = target.rules?.allowedExtensions.length
    ? DOCUMENT_EXTENSIONS.filter((extension) => target.rules?.allowedExtensions.includes(extension.slice(1)))
    : DOCUMENT_EXTENSIONS;

  async function handleUpload() {
    if (selectedFiles.length === 0 || uploading || target.incomplete || ruleProblems.length > 0) return;
    setUploading(true);
    setError(null);
    try {
      const body = new FormData();
      selectedFiles.forEach((file) => body.append("files", file));
      body.append("tags", tagsValue);
      target.appendTo(body);
      const result = await browserApiFetch<DocumentUploadResult>("/api/files/document-uploads", {
        method: "POST",
        body,
        // browserApiFetch's default 15s timeout is too short for a batch of large documents
        // plus the virus scan - same fix as the photo upload's own request.
        signal: AbortSignal.timeout(300_000),
      });
      if (!result || result.items.length === 0) {
        // Nothing was saved: stay open so the reasons stay readable next to the queue.
        setError(result?.errors.join(" · ") || "Upload fehlgeschlagen");
        return;
      }
      onUploaded(result);
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
      title="Dateien hochladen"
      description="Die Dateien landen unter Dateien, werden beim Upload virengeprüft und lassen sich mit einem Termin, einer Abgabe oder einem Zyklus verknüpfen."
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
              accept={acceptedExtensions.join(",")}
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
              {isDragging ? "Zum Hochladen loslassen" : "Dateien hierher ziehen"}
            </p>
            <p className="muted">
              oder <span className="gallery-upload-browse">Dateien auswählen</span>
            </p>
            <div className="gallery-upload-formats" aria-label="Unterstützte Formate">
              {DOCUMENT_FORMATS.map((format) => (
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
                      <div className="gallery-upload-thumbnail-fallback">
                        <DocumentIcon />
                      </div>
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
            <span className="gallery-upload-label">Tags für alle Dateien</span>
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
                  ? `${selectedFiles.length} ${selectedFiles.length === 1 ? "Datei" : "Dateien"} hochladen`
                  : "Hochladen"}
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
