"use client";

import { useState } from "react";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";

export type PdfExportResult = {
  content_url?: string | null;
  status: string;
  export_format: string;
  version_major?: number | null;
  version_minor?: number | null;
};

/** Shared "generate/open protocol PDF" logic, used by both the protocol list and the protocol detail header. */
export function usePdfExport() {
  const showToast = useToast();
  const [busyByProtocol, setBusyByProtocol] = useState<Record<string, boolean>>({});

  async function generatePdf(
    protocolId: string,
    protocolNumber: string,
    onExported?: (result: PdfExportResult) => void
  ) {
    setBusyByProtocol((current) => ({ ...current, [protocolId]: true }));
    try {
      const result = await browserApiFetch<PdfExportResult>(`/api/protocols/${protocolId}/exports/pdf`, {
        method: "POST",
      });
      onExported?.(result);
      if (result.content_url) {
        const pdfUrl = `${browserApiBaseUrl}${result.content_url}`;
        showToast(`PDF bereit – hier klicken zum Öffnen`, "success", {
          onMessageClick: () => window.open(pdfUrl, "_blank", "noopener,noreferrer"),
        });
      } else {
        showToast(`PDF für ${protocolNumber} bereit`, "success");
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : "PDF-Export fehlgeschlagen", "error");
    } finally {
      setBusyByProtocol((current) => ({ ...current, [protocolId]: false }));
    }
  }

  /** Opens the already-generated PDF if one exists, otherwise generates a fresh one. */
  function openOrGeneratePdf(
    protocol: { id: string; protocol_number: string; latest_pdf_url?: string | null },
    onExported?: (result: PdfExportResult) => void
  ) {
    if (protocol.latest_pdf_url) {
      window.open(`${browserApiBaseUrl}${protocol.latest_pdf_url}`, "_blank", "noopener,noreferrer");
      return;
    }
    void generatePdf(protocol.id, protocol.protocol_number, onExported);
  }

  return { busyByProtocol, generatePdf, openOrGeneratePdf };
}
