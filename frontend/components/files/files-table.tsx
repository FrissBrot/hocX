"use client";

import { useTranslations } from "next-intl";

import { FileTypeIcon } from "./file-type-icon";
import { DOCUMENT_STATUS_VARIANT } from "./document-panel";
import { SOURCE_BADGE_VARIANT, SOURCE_KEY } from "./file-detail-modal";
import { ActionIcon } from "@/components/ui/action-icons";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { browserApiBaseUrl } from "@/lib/api/client";
import { formatDate, formatFileSize } from "@/lib/utils/format";
import { FileOverviewItem } from "@/types/api";

export function FilesTable({
  items,
  onOpenDetail,
  onNavigate,
  onShare,
}: {
  items: FileOverviewItem[];
  onOpenDetail: (item: FileOverviewItem) => void;
  onNavigate: (href: string) => void;
  onShare: (item: FileOverviewItem) => void;
}) {
  const t = useTranslations("files");
  return (
    <DataTable
      className="files-data-table"
      columns={[t("table.columnName"), t("table.columnSource"), t("table.columnReference"), t("table.columnUploaded"), t("table.columnSize"), ""]}
      emptyMessage={t("table.empty")}
    >
      {items.map((item) => {
        return (
          <tr key={item.id} className="table-row-clickable" onClick={() => onOpenDetail(item)}>
            <td>
              <span className="files-table-name">
                <FileTypeIcon name={item.original_name} />
                <span className="files-table-name-text">
                  <span className="files-table-name-line">
                    <span className="files-table-filename" title={item.original_name}>{item.original_name}</span>
                    {item.document && item.document.status !== "ready" && item.document.status !== "processing" ? (
                      <Badge variant={DOCUMENT_STATUS_VARIANT[item.document.status]}>{t(`document.statusLabel.${item.document.status}`)}</Badge>
                    ) : null}
                    {item.document && item.document.version_count > 1 ? (
                      <Badge variant="neutral">{item.document.current_version_label ?? t("document.versionNumber", { number: item.document.current_version_number ?? 1 })}</Badge>
                    ) : null}
                  </span>
                  {item.document?.status === "processing" ? (
                    <span className="files-table-processing" role="status">
                      <span className="files-table-processing-spinner" aria-hidden="true" />
                      {item.document.processing_stage
                        ? t("table.processingStage", { stage: t(`table.processingStages.${item.document.processing_stage}`) })
                        : t("document.statusLabel.processing")}
                    </span>
                  ) : null}
                </span>
              </span>
            </td>
            <td><Badge variant={SOURCE_BADGE_VARIANT[item.source]}>{t(`source.${SOURCE_KEY[item.source]}`)}</Badge></td>
            <td className="files-table-ref" onClick={(event) => item.ref_href && event.stopPropagation()}>
              {item.ref_label ? (
                item.ref_href ? (
                  <button type="button" className="file-card-ref" onClick={() => onNavigate(item.ref_href!)}>
                    {item.source === "protocol_image" ? t("table.protocolRef", { label: item.ref_label }) : item.ref_label}
                  </button>
                ) : (
                  <span className="muted">{item.ref_label}</span>
                )
              ) : (
                <span className="muted">–</span>
              )}
              {item.ref_date ? <span className="muted"> · {formatDate(item.ref_date)}</span> : null}
            </td>
            <td>{formatDate(item.created_at)}</td>
            <td>{item.file_size_bytes ? formatFileSize(item.file_size_bytes) : <span className="muted">–</span>}</td>
            <td className="files-table-actions" onClick={(event) => event.stopPropagation()}>
              {/* Bevorzugt die PDF-Darstellung; Originale gibt es in den Dokumentdetails. */}
              <a
                href={`${browserApiBaseUrl}${item.document?.pdf_url ?? item.content_url}`}
                target="_blank"
                rel="noreferrer"
                className="button-secondary button-icon"
                aria-label={item.document?.pdf_url ? t("table.openPdf") : t("table.download")}
                title={item.document?.pdf_url ? t("table.openPdf") : t("table.download")}
              >
                <ActionIcon name="download" />
              </a>
              <button
                type="button"
                className="button-secondary button-icon"
                aria-label={t("table.share")}
                title={t("table.share")}
                onClick={() => onShare(item)}
              >
                <ActionIcon name="link" />
              </button>
            </td>
          </tr>
        );
      })}
    </DataTable>
  );
}
