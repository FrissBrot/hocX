"use client";

import { useEffect, useRef, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { TagInput } from "@/components/ui/tag-input";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate, formatFileSize } from "@/lib/utils/format";
import {
  CycleConfigSummary,
  EventSummary,
  FileOverviewItem,
  SubmissionAssignment,
  SubmissionElementStatusEntry,
} from "@/types/api";

const GALLERY_UPLOAD_ACCEPT = "image/jpeg,image/png,image/gif,image/webp,image/bmp,image/tiff,.zip";

export function GalleryUploadModal({
  tagSuggestions,
  onClose,
  onUploaded,
}: {
  tagSuggestions: string[];
  onClose: () => void;
  onUploaded: (items: FileOverviewItem[], errors: string[]) => void;
}) {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [tagsValue, setTagsValue] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Optional target picker: land this batch straight in its Termin's/Abgabe-Element's/
  // Zyklus' auto-album (see photo_album_service.py) instead of only the plain gallery.
  const [targetKind, setTargetKind] = useState<"none" | "event" | "submission_element" | "cycle">("none");
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
      const result = await browserApiFetch<{ items: FileOverviewItem[]; errors: string[] }>("/api/files/gallery-uploads", {
        method: "POST",
        body,
      });
      onUploaded(result?.items ?? [], result?.errors ?? []);
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
      description="Direkt in die Galerie hochladen - auch als ZIP-Archiv, dabei werden nur enthaltene Bilddateien übernommen. Jede Datei durchläuft die Virenprüfung."
      onClose={onClose}
      size="wide"
    >
      <div className="gallery-upload">
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
          <p>Bilder oder ZIP-Dateien hierher ziehen oder klicken zum Auswählen</p>
          <p className="muted">JPEG, PNG, GIF, WebP, BMP, TIFF - oder ein ZIP-Archiv mit Bildern darin</p>
        </div>

        {selectedFiles.length > 0 && (
          <ul className="gallery-upload-file-list">
            {selectedFiles.map((file, index) => (
              <li key={`${file.name}-${index}`}>
                <span className="gallery-upload-file-name" title={file.name}>{file.name}</span>
                <span className="muted">{formatFileSize(file.size)}</span>
                <button type="button" className="button-ghost button-inline" onClick={() => removeFile(index)}>
                  Entfernen
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="gallery-upload-tags">
          <span className="file-detail-tags-label">Tags für diesen Upload</span>
          <TagInput value={tagsValue} onChange={setTagsValue} suggestions={tagSuggestions} placeholder="Tag hinzufügen…" />
        </div>

        <div className="gallery-upload-tags">
          <span className="file-detail-tags-label">
            Bezug (optional) - landet zusätzlich im passenden Zyklus-/Abgabe-Album mit Best-of-Auswahl
          </span>
          <label><input type="radio" name="upload-target" checked={targetKind === "none"} onChange={() => setTargetKind("none")} /> Kein Bezug</label>
          <label><input type="radio" name="upload-target" checked={targetKind === "event"} onChange={() => setTargetKind("event")} /> Termin</label>
          {targetKind === "event" && (
            <select value={selectedEventId} onChange={(event) => setSelectedEventId(event.target.value)}>
              <option value="">Termin wählen…</option>
              {events.map((event) => (
                <option key={event.id} value={event.id}>{event.title} ({formatDate(event.event_date)})</option>
              ))}
            </select>
          )}
          <label>
            <input type="radio" name="upload-target" checked={targetKind === "submission_element"} onChange={() => setTargetKind("submission_element")} />
            {" "}Abgabe-Element
          </label>
          {targetKind === "submission_element" && (
            <>
              <select
                value={selectedAssignmentId}
                onChange={(event) => { setSelectedAssignmentId(event.target.value); setSelectedElementRef(""); }}
              >
                <option value="">Abgabe wählen…</option>
                {assignments.map((assignment) => (
                  <option key={assignment.id} value={assignment.id}>{assignment.title}</option>
                ))}
              </select>
              {selectedAssignmentId && (
                <select value={selectedElementRef} onChange={(event) => setSelectedElementRef(event.target.value)}>
                  <option value="">Element wählen…</option>
                  {elements.map((element) => (
                    <option key={element.element_ref} value={element.element_ref}>{element.label}</option>
                  ))}
                </select>
              )}
            </>
          )}
          <label><input type="radio" name="upload-target" checked={targetKind === "cycle"} onChange={() => setTargetKind("cycle")} /> Zyklus</label>
          {targetKind === "cycle" && (
            <select value={selectedCycleConfigId} onChange={(event) => setSelectedCycleConfigId(event.target.value)}>
              <option value="">Zyklus wählen…</option>
              {cycleConfigs.map((cycleConfig) => (
                <option key={cycleConfig.id} value={cycleConfig.id}>{cycleConfig.name}</option>
              ))}
            </select>
          )}
        </div>

        {error && <p className="form-error-banner">{error}</p>}

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
    </Modal>
  );
}
