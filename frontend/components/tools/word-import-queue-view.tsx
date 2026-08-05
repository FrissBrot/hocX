"use client";

import { useRef, useState } from "react";

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

export function WordImportQueueView({ templates, participants, initialDocuments }: Props) {
  const [documents, setDocuments] = useState<WordImportDocumentSummary[]>(initialDocuments);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("eingelesen");
  const [openDocumentId, setOpenDocumentId] = useState<number | null>(null);
  const [uploadTemplateId, setUploadTemplateId] = useState<number | null>(templates[0]?.id ?? null);
  const [uploading, setUploading] = useState(false);
  const [uploadErrors, setUploadErrors] = useState<string[]>([]);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function refresh() {
    const result = await listWordImportDocuments();
    setDocuments(result);
  }

  async function handleFilesSelected(fileList: FileList | null) {
    const files = Array.from(fileList ?? []).filter((file) => file.name.toLowerCase().endsWith(".docx"));
    if (!files.length || !uploadTemplateId) return;
    setUploading(true);
    setUploadErrors([]);
    try {
      const result = await ingestWordImportDocuments(uploadTemplateId, files);
      setDocuments((current) => [...result.documents, ...current]);
      setUploadErrors(result.errors);
      setStatusFilter("eingelesen");
    } catch (err) {
      setUploadErrors([err instanceof Error ? err.message : "Upload fehlgeschlagen"]);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleDelete(document: WordImportDocumentSummary) {
    if (!confirm(`"${document.display_name}" aus der Warteschlange entfernen?`)) return;
    setDeletingId(document.id);
    try {
      await deleteWordImportDocument(document.id);
      setDocuments((current) => current.filter((doc) => doc.id !== document.id));
    } finally {
      setDeletingId(null);
    }
  }

  const counts = {
    eingelesen: documents.filter((doc) => doc.status === "eingelesen").length,
    importiert: documents.filter((doc) => doc.status === "importiert").length,
  };
  const filtered = documents.filter((doc) => statusFilter === "all" || doc.status === statusFilter);

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
          Mehrere .docx-Altprotokolle auf einmal hochladen — sie werden derselben Vorlage zugeteilt, sofort analysiert und
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
            <span className="field-label">Word-Dateien (.docx)</span>
            <input
              ref={fileInputRef}
              type="file"
              accept=".docx"
              multiple
              disabled={uploading || !uploadTemplateId}
              onChange={(event) => void handleFilesSelected(event.target.files)}
            />
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
      </div>

      <DataTable
        className="data-table-lg"
        columns={["Name", "Vorlage", "Hochgeladen am", "Status", "Aktionen"]}
        emptyMessage="Keine Dokumente in dieser Ansicht."
      >
        {filtered.map((document) => (
          <tr key={document.id}>
            <td>
              {document.status === "eingelesen" ? (
                <button type="button" className="row-text-action" onClick={() => setOpenDocumentId(document.id)}>
                  <strong>{document.display_name}</strong>
                </button>
              ) : (
                <strong>{document.display_name}</strong>
              )}
              <div className="muted">{document.original_filename}</div>
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
