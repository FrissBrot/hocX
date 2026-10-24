"use client";

// Export Center: Historie der erzeugten PDFs mit Dokument-ID (Echtheitsprüfung), Version,
// Vorlage und Vorlagenrevision sowie Inhalts- und Design-Hash. Neue Exporte starten in den
// jeweiligen Bereichen (Protokoll, Aufgaben, Termine …) über denselben Exportdialog.

import { useCallback, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { DataTable } from "@/components/ui/data-table";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiBaseUrl } from "@/lib/api/client";
import { apiErrorMessage, DocumentExport, DocumentTypeInfo, listExports, studioApi } from "@/lib/documents/api";
import { formatDateTime } from "@/lib/utils/format";

const PAGE_SIZE = 25;

export function ExportHistory() {
  const t = useTranslations("documentStudio");
  const locale = useLocale();
  const [rows, setRows] = useState<DocumentExport[] | null>(null);
  const [types, setTypes] = useState<DocumentTypeInfo[]>([]);
  const [documentType, setDocumentType] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    listExports({ documentType: documentType || null, limit: PAGE_SIZE + 1, offset })
      .then((loaded) => {
        setRows(loaded ?? []);
        setError("");
      })
      .catch((reason) => setError(apiErrorMessage(reason, t("exports.loadFailed"))));
    // t/toast sind während der Lebensdauer der Komponente unveränderlich
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentType, offset]);

  useEffect(() => load(), [load]);
  useEffect(() => {
    void studioApi.catalog().then((catalog) => setTypes(catalog.document_types));
  }, []);

  const visible = (rows ?? []).slice(0, PAGE_SIZE);

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("exports.title")}</h1>
          <p className="muted">{t("exports.description")}</p>
        </div>
      </div>
      <div className="list-filter-row">
        <label className="field-stack">
          <span className="field-label">{t("exports.documentType")}</span>
          <select value={documentType} onChange={(event) => { setDocumentType(event.target.value); setOffset(0); }}>
            <option value="">{t("exports.allTypes")}</option>
            {types.map((type) => (
              <option key={type.key} value={type.key}>
                {t(`docType.${type.key}`)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && <StatusBanner tone="error" message={error} />}
      <DataTable
        columns={[
          { key: "created", label: t("exports.created") },
          { key: "title", label: t("exports.document") },
          { key: "template", label: t("exports.template") },
          { key: "id", label: t("exports.documentId") },
          { key: "file", label: t("exports.file") },
        ]}
        emptyMessage={rows === null ? t("common.loading") : t("exports.empty")}
      >
        {visible.map((row) => (
          <tr key={row.id}>
            <td>{formatDateTime(row.created_at, locale)}</td>
            <td>
              <strong>{row.title ?? t(`docType.${row.document_type}`)}</strong>
              <div className="field-help">
                {t(`docType.${row.document_type}`)}
                {row.version_label ? ` · ${row.version_label}` : ""}
                {row.language ? ` · ${row.language.toUpperCase()}` : ""}
              </div>
            </td>
            <td>
              {row.template_system_key ? t(`system.${row.template_system_key}.name`) : row.template_name ?? t("exports.legacyTemplate")}
              {row.template_revision ? <div className="field-help">{t("revisions.number", { revision: row.template_revision })}</div> : null}
            </td>
            <td>
              <a className="studio-link" href={row.verify_url} target="_blank" rel="noopener noreferrer">
                {row.short_id}
              </a>
              {row.design_hash && <div className="field-help studio-hash" title={t("exports.designHash")}>{row.design_hash.slice(0, 12)}</div>}
            </td>
            <td>
              {row.content_url ? (
                <a className="button-secondary" href={`${browserApiBaseUrl}${row.content_url}`} target="_blank" rel="noopener noreferrer">
                  {t("exports.open")}
                </a>
              ) : (
                <span className="muted">{t("exports.fileExpired")}</span>
              )}
            </td>
          </tr>
        ))}
      </DataTable>
      <div className="studio-pager">
        <button type="button" className="button-secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
          {t("exports.previous")}
        </button>
        <button type="button" className="button-secondary" disabled={!rows || rows.length <= PAGE_SIZE} onClick={() => setOffset(offset + PAGE_SIZE)}>
          {t("exports.next")}
        </button>
      </div>
    </div>
  );
}
