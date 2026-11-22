"use client";

// Aktionsmenü «···» einer Datei im Dateien-Tab - in Liste und Kacheln dasselbe (Design «Dateien v2»).
// Die PDF-Ansicht steht vorne (fileDisplay), das Original bleibt als eigener Eintrag erreichbar.
import { useTranslations } from "next-intl";

import type { ActionMenuItem } from "@/components/ui/action-menu";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { fileDisplay } from "@/lib/files/display";
import type { FileOverviewItem } from "@/types/api";

export function openInNewTab(url: string) {
  window.open(`${browserApiBaseUrl}${url}`, "_blank", "noopener,noreferrer");
}

export function downloadUrl(url: string) {
  const link = document.createElement("a");
  link.href = `${browserApiBaseUrl}${url}`;
  link.download = "";
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

export function useFileActions({
  onOpenDetail,
  onShare,
  onChanged,
  onTrash,
}: {
  onOpenDetail: (item: FileOverviewItem) => void;
  /** Fehlt ohne sharing.public bzw. Abo «Fotos teilen»: kein Menüeintrag «Teilen». */
  onShare?: (item: FileOverviewItem) => void;
  /** Nach «Erneut verarbeiten»: Liste neu laden. */
  onChanged?: () => void;
  /** «In den Papierkorb» - nur für Direkt-Uploads und mit files.manage (Papierkorb, Migration 0199). */
  onTrash?: (item: FileOverviewItem) => void;
}) {
  const t = useTranslations("files");
  const showToast = useToast();

  async function reprocess(item: FileOverviewItem) {
    if (!item.document) return;
    try {
      await browserApiFetch(`/api/documents/${item.document.id}/reprocess`, { method: "POST" });
      showToast(t("document.reprocessStarted"), "success");
      onChanged?.();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("document.reprocessError"), "error");
    }
  }

  return (item: FileOverviewItem): ActionMenuItem[] => {
    const display = fileDisplay(item);
    const document = item.document ?? null;
    const items: ActionMenuItem[] = [];
    if (document?.pdf_url) items.push({ label: t("table.openPdf"), onClick: () => openInNewTab(document.pdf_url!) });
    if (display.pdfDownloadUrl) items.push({ label: t("document.downloadPdf"), onClick: () => downloadUrl(display.pdfDownloadUrl!) });
    if (display.originalExtension !== "pdf" || !document?.pdf_url) {
      items.push({
        label: document ? t("menu.downloadOriginal", { ext: display.originalExtension.toUpperCase() }) : t("table.download"),
        onClick: () => downloadUrl(item.content_url),
      });
    }
    if (onShare) items.push({ label: t("table.share"), onClick: () => onShare(item) });
    items.push({ label: t("menu.details"), onClick: () => onOpenDetail(item) });
    if (document && document.version_count > 1) {
      items.push({ label: t("menu.versions", { count: document.version_count }), onClick: () => onOpenDetail(item) });
    }
    if (document && (document.status === "failed" || document.status === "partial")) {
      items.push({ label: t("document.reprocess"), onClick: () => void reprocess(item) });
    }
    if (onTrash && item.source === "gallery_upload") {
      items.push({ label: t("trash.moveLabel"), onClick: () => onTrash(item), danger: true });
    }
    return items;
  };
}
