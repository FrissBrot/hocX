"use client";

// Kachelansicht des Dateien-Tabs (Design «Dateien v2»): Vorschau der ersten PDF-Seite, sonst ein
// Dateisymbol mit Hinweis (in Verarbeitung, fehlgeschlagen, keine PDF-Ansicht).
import { useState } from "react";
import { useTranslations } from "next-intl";

import { DOCUMENT_STATUS_VARIANT } from "./document-panel";
import { openInNewTab } from "./file-actions";
import { SOURCE_BADGE_VARIANT, SOURCE_KEY } from "./file-detail-modal";
import { FileTypeIcon } from "./file-type-icon";
import { ActionIcon } from "@/components/ui/action-icons";
import { ActionMenu, type ActionMenuItem } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { browserApiBaseUrl } from "@/lib/api/client";
import { fileDisplay } from "@/lib/files/display";
import { formatDate, formatFileSize } from "@/lib/utils/format";
import type { FileOverviewItem } from "@/types/api";

function TilePreview({ item }: { item: FileOverviewItem }) {
  const t = useTranslations("files");
  const [failed, setFailed] = useState(false);
  const display = fileDisplay(item);
  const document = item.document ?? null;
  const previewUrl = document?.preview_url ?? null;
  if (previewUrl && !failed) {
    return (
      <span className="files-tile-page">
        {/* eslint-disable-next-line @next/next/no-img-element -- Vorschau kommt authentifiziert von der API */}
        <img src={`${browserApiBaseUrl}${previewUrl}`} alt="" loading="lazy" onError={() => setFailed(true)} />
      </span>
    );
  }
  const status = document?.status;
  return (
    <span className="files-tile-placeholder">
      <FileTypeIcon name={item.original_name} extension={display.extension} />
      {status === "processing" ? (
        <span className="files-tile-note files-tile-note-busy" role="status">
          <span className="files-table-processing-spinner" aria-hidden="true" />
          {document?.processing_stage
            ? t("table.processingStage", { stage: t(`table.processingStages.${document.processing_stage}`) })
            : t("document.statusLabel.processing")}
        </span>
      ) : status === "failed" ? (
        <span className="files-tile-note files-tile-note-failed">{t("grid.noPdfFailed")}</span>
      ) : (
        <span className="files-tile-note">{t("grid.noPdf")}</span>
      )}
    </span>
  );
}

export function FilesGrid({
  items,
  onOpenDetail,
  actionsFor,
}: {
  items: FileOverviewItem[];
  onOpenDetail: (item: FileOverviewItem) => void;
  actionsFor: (item: FileOverviewItem) => ActionMenuItem[];
}) {
  const t = useTranslations("files");
  if (items.length === 0) return <p className="muted files-grid-empty">{t("table.empty")}</p>;
  return (
    <ul className="files-grid" aria-label={t("grid.label")}>
      {items.map((item) => {
        const display = fileDisplay(item);
        const document = item.document ?? null;
        const statusBadge = document && document.status !== "ready" && document.status !== "processing" ? document.status : null;
        return (
          <li key={item.id} className="files-tile">
            <button type="button" className="files-tile-open" onClick={() => onOpenDetail(item)} aria-label={t("grid.openDetails", { name: display.name })}>
              <span className="files-tile-preview">
                <TilePreview item={item} />
                <span className={`files-tile-ext files-tile-ext-${display.extension || "file"}`}>{(display.extension || "?").slice(0, 5).toUpperCase()}</span>
              </span>
              <span className="files-tile-name" title={display.showsGeneratedPdf ? t("grid.originalHint", { name: item.original_name }) : display.name}>
                {display.name}
              </span>
            </button>
            {statusBadge || (document && document.version_count > 1) ? (
              <span className="files-tile-badges">
                {statusBadge ? <Badge variant={DOCUMENT_STATUS_VARIANT[statusBadge]}>{t(`document.statusLabel.${statusBadge}`)}</Badge> : null}
                {document && document.version_count > 1 ? (
                  <Badge variant="neutral">{document.current_version_label ?? t("document.versionNumber", { number: document.current_version_number ?? 1 })}</Badge>
                ) : null}
              </span>
            ) : null}
            <span className="files-tile-meta">
              <Badge variant={SOURCE_BADGE_VARIANT[item.source]}>{t(`source.${SOURCE_KEY[item.source]}`)}</Badge>
              <span className="files-tile-date">
                {formatDate(item.created_at)}
                {item.file_size_bytes ? ` · ${formatFileSize(item.file_size_bytes)}` : ""}
              </span>
              <button
                type="button"
                className="button-icon-soft button-icon-soft-sm"
                aria-label={document?.pdf_url ? t("table.openPdf") : t("table.download")}
                title={document?.pdf_url ? t("table.openPdf") : t("table.download")}
                onClick={() => openInNewTab(display.openUrl)}
              >
                <ActionIcon name="download" />
              </button>
              <ActionMenu items={actionsFor(item)} ariaLabel={t("menu.more")} />
            </span>
          </li>
        );
      })}
    </ul>
  );
}
