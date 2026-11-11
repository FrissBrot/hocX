"use client";

import { useEffect, useRef, useState } from "react";

import { browserApiFetch } from "@/lib/api/client";
import type { ProtocolElement, ProtocolImage, ProtocolTodo } from "@/types/api";

/** Gründe, warum Inhalt aus dem Editor nicht im PDF erscheint (backend/app/documents/export_coverage.py). */
export type PdfCoverageReason = "element_not_exported" | "session_notes" | "block_not_exported" | "omitted_by_layout" | "image_unavailable";
export type PdfCoverageEntry = { reason: PdfCoverageReason; count?: number };
export type PdfCoverage = { elements: Record<string, PdfCoverageEntry>; blocks: Record<string, PdfCoverageEntry> };
export const NO_PDF_COVERAGE: PdfCoverage = { elements: {}, blocks: {} };

type CoverageResponse = {
  elements: Array<{ id: string; reason: PdfCoverageReason }>;
  blocks: Array<{ id: string; reason: PdfCoverageReason; count?: number }>;
};

// Nach der letzten relevanten Änderung kurz warten: die Abfrage setzt die Protokoll-Vorlage
// (ohne PDF) zusammen und soll beim Tippen nicht laufend kommen.
const REFRESH_DELAY_MS = 4000;

export function toPdfCoverage(response: CoverageResponse): PdfCoverage {
  return {
    elements: Object.fromEntries(response.elements.map(({ id, reason }) => [id, { reason }])),
    blocks: Object.fromEntries(response.blocks.map(({ id, reason, count }) => [id, count == null ? { reason } : { reason, count }])),
  };
}

/** Was die Abdeckung ändern kann: Struktur, Exportschalter und ob ein Block leer ist. Der
 * Wortlaut eines Textes zählt nicht - ein Block mit Text bleibt gleich abgedeckt. */
export function pdfCoverageSignature(
  elements: ProtocolElement[],
  textDrafts: Record<string, string>,
  todosByBlock: Record<string, ProtocolTodo[]>,
  imagesByBlock: Record<string, ProtocolImage[]>,
): string {
  return elements
    .map((element) => {
      const blocks = element.blocks.map((block) => {
        const text = textDrafts[block.id] ?? block.text_content ?? "";
        const filled = text.trim() !== "" || (todosByBlock[block.id]?.length ?? 0) > 0 || (imagesByBlock[block.id]?.length ?? 0) > 0;
        return `${block.id}:${block.export_visible_snapshot ? 1 : 0}${block.is_visible_snapshot ? 1 : 0}${filled ? 1 : 0}:${imagesByBlock[block.id]?.length ?? 0}:${JSON.stringify(block.configuration_snapshot_json ?? {}).length}`;
      });
      return `${element.id}:${element.export_visible_snapshot ? 1 : 0}[${blocks.join(",")}]`;
    })
    .join("|");
}

/** Abdeckung des Protokolls für die Markierung «Nicht im PDF». Fehler sind still: ohne Antwort
 * markiert der Editor nichts (der Export selbst ist davon nicht betroffen). */
export function usePdfCoverage(protocolId: string, signature: string): PdfCoverage {
  const [coverage, setCoverage] = useState<PdfCoverage>(NO_PDF_COVERAGE);
  const firstRef = useRef(true);
  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      browserApiFetch<CoverageResponse>(`/api/protocols/${protocolId}/pdf-coverage`)
        .then((response) => {
          if (cancelled) return;
          const next = toPdfCoverage(response);
          // Unverändert: altes Objekt behalten, damit kein Punkt neu rendert
          setCoverage((current) => (JSON.stringify(current) === JSON.stringify(next) ? current : next));
        })
        .catch(() => undefined);
    }, firstRef.current ? 0 : REFRESH_DELAY_MS);
    firstRef.current = false;
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [protocolId, signature]);
  return coverage;
}
