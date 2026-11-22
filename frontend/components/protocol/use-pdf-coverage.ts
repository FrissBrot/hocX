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
// Spätestens so lange nach dem Laden kommt die erste Abfrage, auch ohne Leerlauf.
const FIRST_LOAD_TIMEOUT_MS = 3000;

export function toPdfCoverage(response: CoverageResponse): PdfCoverage {
  return {
    elements: Object.fromEntries(response.elements.map(({ id, reason }) => [id, { reason }])),
    blocks: Object.fromEntries(response.blocks.map(({ id, reason, count }) => [id, count == null ? { reason } : { reason, count }])),
  };
}

// Länge der serialisierten Blockkonfiguration je Konfigurationsobjekt. Die Signatur entsteht bei
// jedem Tastendruck neu; die Konfigurationen sind dabei unveränderte Objekte (Zustand wird nur
// ersetzt, nie verändert) - also je Objekt nur einmal serialisieren statt jedes Mal alle
// (Performance-Audit Protokoll-Editor 2026-11-22).
const configSizes = new WeakMap<object, number>();

function configSize(config: Record<string, unknown> | null | undefined): number {
  if (!config) return 2; // JSON.stringify({}).length
  let size = configSizes.get(config);
  if (size === undefined) {
    size = JSON.stringify(config).length;
    configSizes.set(config, size);
  }
  return size;
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
        // /\S/ bricht beim ersten Zeichen ab, trim() kopierte den ganzen Text
        const filled = /\S/.test(text) || (todosByBlock[block.id]?.length ?? 0) > 0 || (imagesByBlock[block.id]?.length ?? 0) > 0;
        return `${block.id}:${block.export_visible_snapshot ? 1 : 0}${block.is_visible_snapshot ? 1 : 0}${filled ? 1 : 0}:${imagesByBlock[block.id]?.length ?? 0}:${configSize(block.configuration_snapshot_json)}`;
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
    const load = () => {
      browserApiFetch<CoverageResponse>(`/api/protocols/${protocolId}/pdf-coverage`)
        .then((response) => {
          if (cancelled) return;
          const next = toPdfCoverage(response);
          // Unverändert: altes Objekt behalten, damit kein Punkt neu rendert
          setCoverage((current) => (JSON.stringify(current) === JSON.stringify(next) ? current : next));
        })
        .catch(() => undefined);
    };
    const first = firstRef.current;
    firstRef.current = false;
    // Erste Abfrage im Leerlauf nach dem Laden (B1): sie setzt die Protokoll-Vorlage zusammen
    // und konkurrierte sonst mit den Anfragen und dem Aufbau des Editors.
    const idleWindow = window as Window & {
      requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
      cancelIdleCallback?: (handle: number) => void;
    };
    if (first && idleWindow.requestIdleCallback) {
      const handle = idleWindow.requestIdleCallback(load, { timeout: FIRST_LOAD_TIMEOUT_MS });
      return () => {
        cancelled = true;
        idleWindow.cancelIdleCallback?.(handle);
      };
    }
    const timer = window.setTimeout(load, first ? 0 : REFRESH_DELAY_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [protocolId, signature]);
  return coverage;
}
