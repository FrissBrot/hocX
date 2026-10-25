"use client";

// Aufgelöste Werte für die Arbeitsfläche: dieselbe Kompilierung wie die Vorschau, aber statt
// ganzer Seiten Texte, Sichtbarkeiten, Wiederholungen, Brand-Werte und gerenderte Ausschnitte
// (Fachkomponenten, Tabellen). Entprellt, veraltete Anfragen werden abgebrochen; bis zur
// nächsten Antwort bleibt der letzte Stand stehen, damit die Fläche nicht springt.

import { useEffect, useRef, useState } from "react";

import { CanvasData, previewCanvas } from "@/lib/documents/api";
import type { TemplateContent } from "@/lib/documents/layout";

const DEBOUNCE_MS = 450;
const CACHE_SIZE = 20;

type Source = { content: TemplateContent; documentType: string; dataMode: "sample" | "data"; protocolId: string | null; brandId: string | null; needsProtocol: boolean };

export function useCanvasData({ content, documentType, dataMode, protocolId, brandId, needsProtocol }: Source): CanvasData | null {
  const [data, setData] = useState<CanvasData | null>(null);
  const cache = useRef(new Map<string, CanvasData>());
  const key = JSON.stringify([content, documentType, dataMode, protocolId, brandId]);

  useEffect(() => {
    // Echte Daten ohne Protokoll: Beispielwerte wären irreführend, die Fläche zeigt Platzhalter
    if (dataMode === "data" && needsProtocol && !protocolId) {
      setData(null);
      return;
    }
    const cached = cache.current.get(key);
    if (cached) {
      setData(cached);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      previewCanvas({ document_type: documentType, content, data_mode: dataMode, protocol_id: dataMode === "data" ? protocolId : null, brand_id: brandId }, controller.signal)
        .then((result) => {
          cache.current.set(key, result);
          if (cache.current.size > CACHE_SIZE) cache.current.delete(cache.current.keys().next().value as string);
          setData(result);
        })
        .catch(() => {
          // Fehler meldet die Vorschau; die Arbeitsfläche behält den letzten Stand bzw. zeigt
          // die Platzhalter der Bindungen
        });
    }, DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
    // Der Schlüssel fasst alle Eingaben zusammen
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return data;
}
