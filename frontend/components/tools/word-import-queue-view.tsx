"use client";

import { useRef, useState } from "react";

import { useConfirm } from "@/contexts/confirm-context";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { WordImportWizard } from "@/components/tools/word-import-wizard";
import {
  deleteWordImportDocument,
  ingestWordImportDocuments,
  listWordImportDocuments,
  WordImportDocumentSummary,
} from "@/lib/api/word-import";
import { formatDateTime } from "@/lib/utils/format";
import { ParticipantSummary, TemplateSummary } from "@/types/api";

type StatusFilter = "eingelesen" | "importiert" | "all";

type Props = {
  templates: TemplateSummary[];
  participants: ParticipantSummary[];
  initialDocuments: WordImportDocumentSummary[];
};

function UploadIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" width="22" height="22">
      <path d="M12 4v11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M7.5 10.5 12 15l4.5-4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5 19h14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function SpinnerIcon({ size = 14 }: { size?: number }) {
  return (
    <svg className="word-import-spinner" viewBox="0 0 24 24" fill="none" aria-hidden="true" width={size} height={size}>
      <circle cx="12" cy="12" r="9.5" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
      <path d="M21.5 12a9.5 9.5 0 0 0-9.5-9.5" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

type PendingUpload = {
  id: string;
  name: string;
};

export function WordImportQueueView({ templates, participants, initialDocuments }: Props) {
  const confirm = useConfirm();
  const [documents, setDocuments] = useState<WordImportDocumentSummary[]>(initialDocuments);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("eingelesen");
  const [openDocumentId, setOpenDocumentId] = useState<number | null>(null);
  const [uploadTemplateId, setUploadTemplateId] = useState<number | null>(templates[0]?.id ?? null);
  const [uploading, setUploading] = useState(false);
  const [pendingUploads, setPendingUploads] = useState<PendingUpload[]>([]);
  const [uploadErrors, setUploadErrors] = useState<string[]>([]);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [deleteErrors, setDeleteErrors] = useState<string[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function refresh() {
    const result = await listWordImportDocuments();
    setDocuments(result);
    setSelectedIds([]);
  }

  async function handleFilesSelected(fileList: FileList | null) {
    const files = Array.from(fileList ?? []).filter((file) => /\.(docx|pdf|zip)$/i.test(file.name));
    if (!files.length || !uploadTemplateId) return;
    const templateId = uploadTemplateId;
    const queue: PendingUpload[] = files.map((file) => ({ id: crypto.randomUUID(), name: file.name }));
    setPendingUploads((current) => [...queue, ...current]);
    setUploading(true);
    setUploadErrors([]);
    setStatusFilter("eingelesen");
    try {
      // Ein Request pro Datei statt Batch, damit jede Datei sofort mit Spinner in der
      // Tabelle erscheint und dort einzeln zu ihrem Ergebnis wechselt, statt dass die
      // ganze Auswahl erst nach Abschluss aller Analysen sichtbar wird.
      for (let index = 0; index < files.length; index++) {
        const file = files[index];
        const placeholderId = queue[index].id;
        try {
          const result = await ingestWordImportDocuments(templateId, [file]);
          setDocuments((current) => [...result.documents, ...current]);
          if (result.errors.length) setUploadErrors((current) => [...current, ...result.errors]);
        } catch (err) {
          setUploadErrors((current) => [...current, `${file.name}: ${err instanceof Error ? err.message : "Upload fehlgeschlagen"}`]);
        } finally {
          setPendingUploads((current) => current.filter((pending) => pending.id !== placeholderId));
        }
      }
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleDelete(document: WordImportDocumentSummary) {
    if (!(await confirm({ message: `"${document.display_name}" aus der Warteschlange entfernen?`, tone: "danger", confirmLabel: "Entfernen" }))) return;
    setDeletingId(document.id);
    setDeleteErrors([]);
    try {
      // Real bug fixed here: this had no error handling at all - a rejection (e.g. the
      // document was imported by someone else in the meantime, which the backend
      // rejects, see word_import_queue_service.py's delete_document status guard) just
      // silently reset the spinner with no indication anything went wrong.
      await deleteWordImportDocument(document.id);
      setDocuments((current) => current.filter((doc) => doc.id !== document.id));
      setSelectedIds((current) => current.filter((id) => id !== document.id));
    } catch (err) {
      setDeleteErrors([`${document.display_name}: ${err instanceof Error ? err.message : "Entfernen fehlgeschlagen"}`]);
    } finally {
      setDeletingId(null);
    }
  }

  async function handleBulkDelete() {
    if (!selectedIds.length) return;
    if (!(await confirm({ message: `${selectedIds.length} Dokument(e) aus der Warteschlange entfernen?`, tone: "danger", confirmLabel: "Entfernen" }))) return;
    setBulkDeleting(true);
    setDeleteErrors([]);
    try {
      // Real bug fixed here: Promise.all rejects as a whole the moment ONE deletion
      // fails - since the others had already succeeded server-side by then, the table
      // kept showing all N selected rows as still present (setDocuments/setSelectedIds
      // never ran) until a manual reload. Promise.allSettled lets the successful ones
      // through and only reports the ones that actually failed.
      const results = await Promise.allSettled(selectedIds.map((id) => deleteWordImportDocument(id)));
      const failedIds = new Set<number>();
      const errors: string[] = [];
      results.forEach((result, index) => {
        if (result.status === "rejected") {
          const id = selectedIds[index];
          failedIds.add(id);
          const name = documents.find((doc) => doc.id === id)?.display_name ?? `Dokument #${id}`;
          errors.push(`${name}: ${result.reason instanceof Error ? result.reason.message : "Entfernen fehlgeschlagen"}`);
        }
      });
      setDocuments((current) => current.filter((doc) => !selectedIds.includes(doc.id) || failedIds.has(doc.id)));
      setSelectedIds((current) => current.filter((id) => failedIds.has(id)));
      setDeleteErrors(errors);
    } finally {
      setBulkDeleting(false);
    }
  }

  const counts = {
    eingelesen: documents.filter((doc) => doc.status === "eingelesen").length,
    importiert: documents.filter((doc) => doc.status === "importiert").length,
  };
  const filtered = documents.filter((doc) => statusFilter === "all" || doc.status === statusFilter);
  const allFilteredSelected = filtered.length > 0 && filtered.every((doc) => selectedIds.includes(doc.id));

  if (openDocumentId !== null) {
    return (
      <WordImportWizard
        templates={templates}
        participants={participants}
        documentId={openDocumentId}
        onExitQueueMode={() => {
          setOpenDocumentId(null);
          void refresh();
        }}
      />
    );
  }

  return (
    <div className="grid">
      <article className="card">
        <h2 style={{ margin: "0 0 0.35rem" }}>Dokumente einlesen</h2>
        <p className="muted" style={{ margin: "0 0 0.75rem" }}>
          Mehrere Word- oder PDF-Altprotokolle auf einmal hochladen — auch als ZIP gebündelt, dann werden nur die enthaltenen Word- und
          PDF-Dateien eingelesen, alles andere wird ignoriert. Die Dateien werden derselben Vorlage zugeteilt, sofort analysiert und
          landen als &quot;Eingelesen&quot; in der Tabelle unten.
        </p>
        <div className="word-import-narrow" style={{ display: "flex", gap: "0.75rem", alignItems: "flex-end", flexWrap: "wrap" }}>
          <label className="field-stack" style={{ flex: "0 0 auto", minWidth: "220px" }}>
            <span className="field-label">Vorlage</span>
            <select value={uploadTemplateId ?? ""} onChange={(event) => setUploadTemplateId(Number(event.target.value))}>
              {templates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field-stack" style={{ flex: "1 1 auto" }}>
            <span className="field-label">Word-, PDF- oder ZIP-Dateien (.docx, .pdf, .zip)</span>
            <label
              className={`word-import-dropzone word-import-dropzone-compact${isDragOver ? " is-dragover" : ""}`}
              onDragOver={(event) => {
                event.preventDefault();
                setIsDragOver(true);
              }}
              onDragLeave={() => setIsDragOver(false)}
              onDrop={(event) => {
                event.preventDefault();
                setIsDragOver(false);
                void handleFilesSelected(event.dataTransfer.files);
              }}
            >
              <span className="word-import-dropzone-icon">
                <UploadIcon />
              </span>
              <span>
                <span className="word-import-dropzone-link">Dateien auswählen</span> oder hierher ziehen
              </span>
              <input
                ref={fileInputRef}
                type="file"
                accept=".docx,.pdf,.zip"
                multiple
                disabled={uploading || !uploadTemplateId}
                onChange={(event) => void handleFilesSelected(event.target.files)}
                hidden
              />
            </label>
          </label>
          {uploading && <span className="muted">Lädt…</span>}
        </div>
        {uploadErrors.length > 0 && (
          <div className="form-error-banner" style={{ marginTop: "0.75rem" }}>
            {uploadErrors.map((message, index) => (
              <div key={index}>{message}</div>
            ))}
          </div>
        )}
      </article>

      <div className="list-filter-row">
        <FilterTabs<StatusFilter>
          options={[
            { value: "eingelesen", label: "Offen", count: counts.eingelesen || undefined },
            { value: "importiert", label: "Abgeschlossen", count: counts.importiert || undefined },
            { value: "all", label: "Alle" },
          ]}
          value={statusFilter}
          onChange={setStatusFilter}
        />
        {selectedIds.length > 0 && (
          <div className="table-toolbar-actions">
            <span className="pill">{selectedIds.length} ausgewählt</span>
            <button
              type="button"
              className="button-inline button-danger"
              disabled={bulkDeleting}
              onClick={() => void handleBulkDelete()}
            >
              Auswahl entfernen
            </button>
          </div>
        )}
      </div>

      {deleteErrors.length > 0 && (
        <div className="form-error-banner">
          {deleteErrors.map((message, index) => (
            <div key={index}>{message}</div>
          ))}
        </div>
      )}

      <DataTable
        className="data-table-lg"
        columns={[
          {
            key: "select",
            label: "",
            header: (
              <input
                type="checkbox"
                aria-label="Alle auswählen"
                checked={allFilteredSelected}
                onChange={(event) => setSelectedIds(event.target.checked ? filtered.map((doc) => doc.id) : [])}
              />
            ),
          },
          "Name",
          "Vorlage",
          "Hochgeladen am",
          "Status",
          "Aktionen",
        ]}
        emptyMessage="Keine Dokumente in dieser Ansicht."
      >
        {(statusFilter === "eingelesen" || statusFilter === "all") &&
          pendingUploads.map((pending) => (
            <tr key={pending.id} className="word-import-queue-pending-row">
              <td />
              <td>
                <strong>{pending.name}</strong>
              </td>
              <td>{templates.find((template) => template.id === uploadTemplateId)?.name ?? ""}</td>
              <td>&mdash;</td>
              <td>
                <span className="word-import-cell-with-spinner">
                  <SpinnerIcon size={12} /> Wird analysiert…
                </span>
              </td>
              <td />
            </tr>
          ))}
        {filtered.map((document) => (
          <tr key={document.id}>
            <td onClick={(event) => event.stopPropagation()}>
              <input
                type="checkbox"
                checked={selectedIds.includes(document.id)}
                onChange={(event) =>
                  setSelectedIds((current) =>
                    event.target.checked ? [...current, document.id] : current.filter((id) => id !== document.id)
                  )
                }
              />
            </td>
            <td>
              {document.status === "eingelesen" ? (
                <button type="button" className="row-text-action" onClick={() => setOpenDocumentId(document.id)}>
                  <strong>{document.display_name}</strong>
                </button>
              ) : (
                <strong>{document.display_name}</strong>
              )}
              <div className="muted">{document.original_filename}</div>
              {document.duplicates.length > 0 && (
                <div className="word-import-duplicate-hint">
                  <Badge variant="warning">Mögliches Duplikat</Badge>
                  <span className="muted">
                    gleiches Datum wie{" "}
                    {document.duplicates.map((duplicate, index) => (
                      <span key={duplicate.id}>
                        {index > 0 && ", "}
                        {duplicate.status === "importiert" && duplicate.protocol_id ? (
                          <a className="row-text-action" href={`/protocols/${duplicate.protocol_id}`}>
                            „{duplicate.display_name}“ (bereits importiert)
                          </a>
                        ) : (
                          <button
                            type="button"
                            className="row-text-action"
                            onClick={() => setOpenDocumentId(duplicate.id)}
                          >
                            „{duplicate.display_name}“ (noch offen)
                          </button>
                        )}
                      </span>
                    ))}
                  </span>
                </div>
              )}
            </td>
            <td>{document.template_name}</td>
            <td>{formatDateTime(document.created_at)}</td>
            <td>
              <Badge variant={document.status === "importiert" ? "success" : "info"}>
                {document.status === "importiert" ? "Importiert" : "Eingelesen"}
              </Badge>
            </td>
            <td>
              <div className="table-actions table-actions-start">
                {document.status === "eingelesen" ? (
                  <>
                    <button type="button" className="row-text-action" onClick={() => setOpenDocumentId(document.id)}>
                      Prüfen &amp; importieren
                    </button>
                    <button
                      type="button"
                      className="row-text-action row-text-action-danger"
                      disabled={deletingId === document.id}
                      onClick={() => void handleDelete(document)}
                    >
                      Entfernen
                    </button>
                  </>
                ) : (
                  <>
                    {document.protocol_id && (
                      <a className="row-text-action" href={`/protocols/${document.protocol_id}`}>
                        Protokoll öffnen
                      </a>
                    )}
                    <a className="row-text-action" href={`/api/stored-files/${document.stored_file_id}/content`}>
                      Original herunterladen
                    </a>
                  </>
                )}
              </div>
            </td>
          </tr>
        ))}
      </DataTable>
    </div>
  );
}
