"use client";

import { useEffect, useRef, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { TagInput } from "@/components/ui/tag-input";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate, formatFileSize } from "@/lib/utils/format";
import {
  CycleConfigSummary,
  EventSummary,
  GalleryUploadJob,
  SubmissionAssignment,
  SubmissionElementStatusEntry,
} from "@/types/api";

const GALLERY_UPLOAD_ACCEPT = "image/jpeg,image/png,image/gif,image/webp,image/bmp,image/tiff,.zip";

type TargetCategory = "none" | "event" | "submission_element" | "cycle";

const TARGET_CATEGORY_OPTIONS: { id: TargetCategory; label: string }[] = [
  { id: "none", label: "Kein Bezug" },
  { id: "event", label: "Termin" },
  { id: "submission_element", label: "Abgabe-Element" },
  { id: "cycle", label: "Zyklus" },
];

function ImageIcon() {
  return (
    <svg className="gallery-upload-image-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="3" y="4" width="18" height="16" rx="3" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="9" cy="10" r="1.8" stroke="currentColor" strokeWidth="1.6" />
      <path d="M4.5 17.5 9 12.5l3 3.2 3.5-4.2 4 5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ZipIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" width="20" height="20">
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
  // Zyklus' auto-album (see photo_album_service.py) instead of only the plain gallery.
  const [targetKind, setTargetKind] = useState<TargetCategory>("none");
  const [events, setEvents] = useState<EventSummary[]>([]);
  const [assignments, setAssignments] = useState<SubmissionAssignment[]>([]);
  const [cycleConfigs, setCycleConfigs] = useState<CycleConfigSummary[]>([]);
  const [selectedEventId, setSelectedEventId] = useState("");
  const [selectedAssignmentId, setSelectedAssignmentId] = useState("");
  const [elements, setElements] = useState<SubmissionElementStatusEntry[]>([]);
  const [selectedElementRef, setSelectedElementRef] = useState("");
  const [selectedCycleConfigId, setSelectedCycleConfigId] = useState("");

  useEffect(() => {
    browserApiFetch<EventSummary[]>("/api/events").then((data) => setEvents(data ?? [])).catch(() => {});
    browserApiFetch<SubmissionAssignment[]>("/api/submission-assignments").then((data) => setAssignments(data ?? [])).catch(() => {});
    browserApiFetch<CycleConfigSummary[]>("/api/cycle-configs").then((data) => setCycleConfigs(data ?? [])).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedAssignmentId) {
      setElements([]);
      return;
    }
    browserApiFetch<SubmissionElementStatusEntry[]>(`/api/submission-assignments/${selectedAssignmentId}/elements`)
      .then((data) => setElements(data ?? []))
      .catch(() => setElements([]));
  }, [selectedAssignmentId]);

  function addFiles(fileList: FileList | File[]) {
    setSelectedFiles((current) => [...current, ...Array.from(fileList)]);
    setError(null);
  }

  function removeFile(index: number) {
    setSelectedFiles((current) => current.filter((_, i) => i !== index));
  }

  const targetIncomplete =
    (targetKind === "event" && !selectedEventId) ||
    (targetKind === "submission_element" && (!selectedAssignmentId || !selectedElementRef)) ||
    (targetKind === "cycle" && !selectedCycleConfigId);

  const totalBytes = selectedFiles.reduce((sum, file) => sum + file.size, 0);

  async function handleUpload() {
    if (selectedFiles.length === 0 || uploading || targetIncomplete) return;
    setUploading(true);
    setError(null);
    try {
      const body = new FormData();
      selectedFiles.forEach((file) => body.append("files", file));
      body.append("tags", tagsValue);
      if (targetKind === "event") body.append("event_id", selectedEventId);
      if (targetKind === "submission_element") {
        body.append("submission_assignment_id", selectedAssignmentId);
        body.append("submission_element_ref", selectedElementRef);
      }
      if (targetKind === "cycle") body.append("cycle_config_id", selectedCycleConfigId);
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
          <div className="gallery-upload-fields">
            <label>
              Bezug
              <SearchableSelect
                options={TARGET_CATEGORY_OPTIONS}
                getId={(option) => option.id}
                getLabel={(option) => option.label}
                value={targetKind}
                onChange={(option) => setTargetKind(option?.id ?? "none")}
              />
            </label>
            {targetKind === "event" && (
              <label>
                Termin
                <SearchableSelect
                  options={events}
                  getId={(event) => event.id}
                  getLabel={(event) => `${event.title} (${formatDate(event.event_date)})`}
                  value={selectedEventId || null}
                  onChange={(event) => setSelectedEventId(event?.id ?? "")}
                  placeholder="Termin wählen…"
                />
              </label>
            )}
            {targetKind === "submission_element" && (
              <label>
                Abgabe
                <SearchableSelect
                  options={assignments}
                  getId={(assignment) => assignment.id}
                  getLabel={(assignment) => assignment.title}
                  value={selectedAssignmentId || null}
                  onChange={(assignment) => { setSelectedAssignmentId(assignment?.id ?? ""); setSelectedElementRef(""); }}
                  placeholder="Abgabe wählen…"
                />
              </label>
            )}
            {targetKind === "cycle" && (
              <label>
                Zyklus
                <SearchableSelect
                  options={cycleConfigs}
                  getId={(cycleConfig) => cycleConfig.id}
                  getLabel={(cycleConfig) => cycleConfig.name}
                  value={selectedCycleConfigId || null}
                  onChange={(cycleConfig) => setSelectedCycleConfigId(cycleConfig?.id ?? "")}
                  placeholder="Zyklus wählen…"
                />
              </label>
            )}
          </div>
          {targetKind === "submission_element" && selectedAssignmentId && (
            <label className="gallery-upload-tags">
              <span className="gallery-upload-label">Abgabe-Element</span>
              <SearchableSelect
                options={elements}
                getId={(element) => element.element_ref}
                getLabel={(element) => element.label}
                value={selectedElementRef || null}
                onChange={(element) => setSelectedElementRef(element?.element_ref ?? "")}
                placeholder="Element wählen…"
              />
            </label>
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
            <ImageIcon />
            <p>Bilder hierher ziehen oder Dateien wählen</p>
            <p className="muted">JPG, PNG, GIF, WebP, BMP, TIFF · ZIP-Archive</p>
          </div>

          <div>
            <div className="gallery-upload-queue-heading">
              <span>Warteschlange</span>
              <span>
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
                        <div style={{ display: "grid", placeItems: "center", height: "100%" }}>
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
                      ×
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
              disabled={uploading || selectedFiles.length === 0 || targetIncomplete}
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
