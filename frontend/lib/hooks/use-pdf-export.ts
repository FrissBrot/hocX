"use client";

import { useRef, useState } from "react";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";

export type PdfExportResult = {
  content_url?: string | null;
  status: string;
  export_format: string;
  version_major?: number | null;
  version_minor?: number | null;
};

/** Öffnet eine PDF aus dem aktuellen gespeicherten Stand, in Liste und Detailansicht. */
export function usePdfExport() {
  const showToast = useToast();
  const [busyByProtocol, setBusyByProtocol] = useState<Record<string, boolean>>({});
  const pendingProtocols = useRef(new Set<string>());

  async function openOrGeneratePdf(
    protocol: { id: string; protocol_number: string; latest_pdf_url?: string | null },
    onExported?: (result: PdfExportResult) => void
  ) {
    const protocolId = protocol.id;
    if (pendingProtocols.current.has(protocolId)) return;
    pendingProtocols.current.add(protocolId);
    setBusyByProtocol((current) => ({ ...current, [protocolId]: true }));

    // Noch innerhalb des Klicks öffnen, damit der Browser den Tab nicht blockiert.
    // Gespeicherte Datei-URLs sind Momentaufnahmen und können bereits veraltet sein.
    let pdfWindow: Window | null = null;
    try {
      pdfWindow = window.open("about:blank", "_blank");
      if (pdfWindow) pdfWindow.opener = null;

      const result = await browserApiFetch<PdfExportResult>(`/api/protocols/${protocolId}/exports/pdf`, {
        method: "POST",
      });
      if (!result.content_url) {
        throw new Error("Die PDF konnte nicht bereitgestellt werden.");
      }
      onExported?.(result);
      const pdfUrl = `${browserApiBaseUrl}${result.content_url}`;
      if (pdfWindow && !pdfWindow.closed) {
        pdfWindow.location.replace(pdfUrl);
      } else {
        showToast("PDF bereit – hier klicken zum Öffnen", "success", {
          onMessageClick: () => window.open(pdfUrl, "_blank", "noopener,noreferrer"),
        });
      }
    } catch (error) {
      pdfWindow?.close();
      showToast(error instanceof Error ? error.message : "PDF-Export fehlgeschlagen", "error");
    } finally {
      pendingProtocols.current.delete(protocolId);
      setBusyByProtocol((current) => ({ ...current, [protocolId]: false }));
    }
  }

  return { busyByProtocol, openOrGeneratePdf };
}
