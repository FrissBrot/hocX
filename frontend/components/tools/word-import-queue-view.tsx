"use client";

import type { Route } from "next";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { useConfirm } from "@/contexts/confirm-context";
import { useRefreshOnRestore } from "@/lib/hooks/use-refresh-on-restore";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { SearchableSelect } from "@/components/ui/searchable-select";
import {
  deleteWordImportDocument,
  ingestWordImportDocuments,
  setLastWordImportTemplate,
  WordImportDocumentSummary,
} from "@/lib/api/word-import";
import { formatDateTime } from "@/lib/utils/format";
import { TemplateSummary } from "@/types/api";

type StatusFilter = "eingelesen" | "importiert" | "all";

type Props = {
  templates: TemplateSummary[];
  initialDocuments: WordImportDocumentSummary[];
  initialTemplateId: string | null;
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

export function WordImportQueueView({ templates, initialDocuments, initialTemplateId }: Props) {
  const t = useTranslations("tools.wordImport");
  const tCommon = useTranslations("common");
  const router = useRouter();
  const confirm = useConfirm();
  useRefreshOnRestore();
  const [documents, setDocuments] = useState<WordImportDocumentSummary[]>(initialDocuments);
  // Sync when router.refresh() / back-navigation delivers newer server data.
  useEffect(() => {
    setDocuments(initialDocuments);
  }, [initialDocuments]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("eingelesen");
  // Zuletzt gewählte Vorlage (tenant.last_word_import_template_id) wird vorausgewählt,
  // solange sie noch existiert/aktiv ist - sonst Fallback auf die erste verfügbare.
  const [uploadTemplateId, setUploadTemplateId] = useState<string | null>(
    (initialTemplateId && templates.some((template) => template.id === initialTemplateId) ? initialTemplateId : null) ??
      templates[0]?.id ??
      null
  );
  const [uploading, setUploading] = useState(false);
  const [pendingUploads, setPendingUploads] = useState<PendingUpload[]>([]);
  const [uploadErrors, setUploadErrors] = useState<string[]>([]);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [deleteErrors, setDeleteErrors] = useState<string[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

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
          setUploadErrors((current) => [...current, `${file.name}: ${err instanceof Error ? err.message : t("queueView.uploadFailed")}`]);
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
    if (!(await confirm({ message: t("queueView.deleteConfirm", { name: document.display_name }), tone: "danger", confirmLabel: t("queueView.removeLabel") }))) return;
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
      setDeleteErrors([`${document.display_name}: ${err instanceof Error ? err.message : t("queueView.removeFailed")}`]);
    } finally {
      setDeletingId(null);
    }
  }

  async function handleBulkDelete() {
    if (!selectedIds.length) return;
    if (!(await confirm({ message: t("queueView.bulkDeleteConfirm", { count: selectedIds.length }), tone: "danger", confirmLabel: t("queueView.removeLabel") }))) return;
    setBulkDeleting(true);
    setDeleteErrors([]);
    try {
      // Real bug fixed here: Promise.all rejects as a whole the moment ONE deletion
      // fails - since the others had already succeeded server-side by then, the table
      // kept showing all N selected rows as still present (setDocuments/setSelectedIds
      // never ran) until a manual reload. Promise.allSettled lets the successful ones
      // through and only reports the ones that actually failed.
      const results = await Promise.allSettled(selectedIds.map((id) => deleteWordImportDocument(id)));
      const failedIds = new Set<string>();
      const errors: string[] = [];
      results.forEach((result, index) => {
        if (result.status === "rejected") {
          const id = selectedIds[index];
          failedIds.add(id);
          const name = documents.find((doc) => doc.id === id)?.display_name ?? t("documentFallback");
          errors.push(`${name}: ${result.reason instanceof Error ? result.reason.message : t("queueView.removeFailed")}`);
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

  return (
    <div className="grid">
      <article className="card">
        <h2 style={{ margin: "0 0 0.35rem" }}>{t("queueView.heading")}</h2>
        <p className="muted" style={{ margin: "0 0 0.75rem" }}>
          {t("queueView.intro")}
        </p>
        <div className="word-import-narrow" style={{ display: "flex", gap: "0.75rem", alignItems: "flex-end", flexWrap: "wrap" }}>
          <label className="field-stack" style={{ flex: "0 0 auto", minWidth: "220px" }}>
            <span className="field-label">{t("templateLabel")}</span>
            <SearchableSelect
              options={templates}
              getId={(template) => template.id}
              getLabel={(template) => template.name}
              value={uploadTemplateId}
              onChange={(template) => {
                const templateId = template ? template.id : null;
                setUploadTemplateId(templateId);
                void setLastWordImportTemplate(templateId);
              }}
            />
          </label>
          <label className="field-stack" style={{ flex: "1 1 auto" }}>
            <span className="field-label">{t("queueView.fileFieldLabel")}</span>
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
                <span className="word-import-dropzone-link">{t("queueView.chooseFilesLink")}</span> {t("queueView.orDragHere")}
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
          {uploading && <span className="muted">{tCommon("loading")}</span>}
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
            { value: "eingelesen", label: t("queueView.filterOpen"), count: counts.eingelesen || undefined },
            { value: "importiert", label: t("queueView.filterDone"), count: counts.importiert || undefined },
            { value: "all", label: t("queueView.filterAll") },
          ]}
          value={statusFilter}
          onChange={setStatusFilter}
        />
        {selectedIds.length > 0 && (
          <div className="table-toolbar-actions">
            <span className="pill">{t("queueView.selectedCount", { count: selectedIds.length })}</span>
            <button
              type="button"
              className="button-secondary button-danger"
              disabled={bulkDeleting}
              onClick={() => void handleBulkDelete()}
            >
              {t("queueView.removeSelectionButton")}
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
                aria-label={t("queueView.selectAllAriaLabel")}
                checked={allFilteredSelected}
                onChange={(event) => setSelectedIds(event.target.checked ? filtered.map((doc) => doc.id) : [])}
              />
            ),
          },
          t("queueView.colName"),
          t("templateLabel"),
          t("queueView.colUploadedAt"),
          t("queueView.colStatus"),
          t("queueView.colActions"),
        ]}
        emptyMessage={t("queueView.emptyMessage")}
      >
        {(statusFilter === "eingelesen" || statusFilter === "all") &&
          pendingUploads.map((pending) => (
            <tr key={pending.id} className="word-import-queue-pending-row">
              <td />
              <td>
                <strong>{pending.name}</strong>
              </td>
              <td>{templates.find((template) => template.id === uploadTemplateId)?.name ?? ""}</td>
              <td>&mdash;</td> {/* i18n-ok: Platzhalter-Gedankenstrich, kein UI-Text */}
              <td>
                <span className="word-import-cell-with-spinner">
                  <SpinnerIcon size={12} /> {t("queueView.analyzingEllipsis")}
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
                <button type="button" className="row-text-action" onClick={() => router.push(`/tools/import/${document.id}` as Route)}>
                  <strong>{document.display_name}</strong>
                </button>
              ) : (
                <strong>{document.display_name}</strong>
              )}
              <div className="muted">{document.original_filename}</div>
              {document.duplicates.length > 0 && (
                <div className="word-import-duplicate-hint">
                  <Badge variant="warning">{t("queueView.possibleDuplicateBadge")}</Badge>
                  <span className="muted">
                    {t("queueView.sameDatePrefix")}{" "}
                    {document.duplicates.map((duplicate, index) => (
                      <span key={duplicate.id}>
                        {index > 0 && ", "}
                        {duplicate.status === "importiert" && duplicate.protocol_id ? (
                          <a className="row-text-action" href={`/protocols/${duplicate.protocol_id}`}>
                            {t("queueView.alreadyImportedNamed", { name: duplicate.display_name })}
                          </a>
                        ) : (
                          <button
                            type="button"
                            className="row-text-action"
                            onClick={() => router.push(`/tools/import/${duplicate.id}` as Route)}
                          >
                            {t("queueView.stillOpenNamed", { name: duplicate.display_name })}
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
                {document.status === "importiert" ? t("queueView.statusImported") : t("queueView.statusRead")}
              </Badge>
            </td>
            <td>
              <div className="table-actions table-actions-start">
                {document.status === "eingelesen" ? (
                  <>
                    <button type="button" className="row-text-action" onClick={() => router.push(`/tools/import/${document.id}` as Route)}>
                      {t("queueView.reviewAndImportButton")}
                    </button>
                    <button
                      type="button"
                      className="row-text-action row-text-action-danger"
                      disabled={deletingId === document.id}
                      onClick={() => void handleDelete(document)}
                    >
                      {t("queueView.removeLabel")}
                    </button>
                  </>
                ) : (
                  <>
                    {document.protocol_id && (
                      <a className="row-text-action" href={`/protocols/${document.protocol_id}`}>
                        {t("queueView.openProtocolButton")}
                      </a>
                    )}
                    <a className="row-text-action" href={`/api/stored-files/${document.stored_file_id}/content`}>
                      {t("queueView.downloadOriginalButton")}
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
