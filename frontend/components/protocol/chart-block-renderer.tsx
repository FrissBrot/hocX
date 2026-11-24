"use client";

import { useRef } from "react";

import { ChartBlock } from "@/components/protocol/chart-block";
import { useNearViewport } from "@/components/protocol/use-near-viewport";

// Diagramm erst einhängen, wenn es in die Nähe des Bildes kommt (L2): Recharts, Statistik-Abfrage
// und Polling laufen sonst für jedes Diagramm schon beim Öffnen des Protokolls. Bis dahin hält ein
// Platzhalter die Höhe, damit nichts springt.
export function ChartBlockRenderer({ config, editable, onSave }: {
  config: { chart_type?: string; cycle_key?: string };
  editable: boolean;
  onSave: (cfg: Record<string, unknown>) => void;
}) {
  const placeholderRef = useRef<HTMLDivElement | null>(null);
  const near = useNearViewport(placeholderRef);
  if (!near) return <div ref={placeholderRef} className="chart-block-placeholder" aria-hidden="true" />;
  return <ChartBlock config={config} editable={editable} onSave={onSave} />;
}
