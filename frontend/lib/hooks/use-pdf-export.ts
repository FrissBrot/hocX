"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl } from "@/lib/api/client";
import { renderDocument } from "@/lib/documents/api";

export type PdfExportResult = {
  content_url?: string | null;
  version_major?: number | null;
  version_minor?: number | null;
  version_label?: string | null;
};

function parseVersion(label: string | null | undefined): { major: number | null; minor: number | null } {
  const match = /^v(\d+)\.(\d+)$/.exec(label ?? "");
  return match ? { major: Number(match[1]), minor: Number(match[2]) } : { major: null, minor: null };
}

/** Erzeugt das Protokoll-PDF (Dokument-Engine, im Dokumentenregister erfasst) aus dem aktuellen Stand und öffnet es.
 * Seit dem Concurrency-Audit (Paket 10) ein Auftrag für den job-worker: renderDocument fragt den
 * Stand ab; ist das PDF fertig, öffnet es sich im vorab geöffneten Tab und eine Meldung (auch nach
 * einem Seitenwechsel, der Toast-Provider lebt in der App-Shell) öffnet es per Klick. */
export function usePdfExport() {
  const t = useTranslations("documentStudio");
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

      const result = await renderDocument({ protocol_id: protocolId, document_type: "protocol" });
      if (!result?.content_url) {
        throw new Error(t("export.failed"));
      }
      const version = parseVersion(result.version_label);
      onExported?.({ content_url: result.content_url, version_label: result.version_label, version_major: version.major, version_minor: version.minor });
      const pdfUrl = `${browserApiBaseUrl}${result.content_url}`;
      if (pdfWindow && !pdfWindow.closed) pdfWindow.location.replace(pdfUrl);
      showToast(t("export.pdfReady"), "success", {
        onMessageClick: () => window.open(pdfUrl, "_blank", "noopener,noreferrer"),
      });
    } catch (error) {
      pdfWindow?.close();
      showToast(error instanceof Error && error.message ? error.message : t("export.failed"), "error");
    } finally {
      pendingProtocols.current.delete(protocolId);
      setBusyByProtocol((current) => ({ ...current, [protocolId]: false }));
    }
  }

  return { busyByProtocol, openOrGeneratePdf };
}
