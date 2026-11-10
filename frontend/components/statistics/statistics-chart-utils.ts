"use client";

import { createContext, useContext } from "react";

import { toIntlLocale } from "@/lib/utils/format";

// Gemeinsam fuer statistics-view.tsx und statistics-charts.tsx, bewusst ohne recharts-Import:
// die Diagramme werden per next/dynamic nachgeladen, Kontext und Formatierer braucht die
// Uebersicht aber sofort.

// true innerhalb der Vollbild-Ansicht einer Diagrammkarte (hoeheres Diagramm).
export const FullscreenCtx = createContext(false);
export function useChartHeight(normal: number, fs = 480) {
  return useContext(FullscreenCtx) ? fs : normal;
}

export function fmtMonth(m: string, locale: string): string {
  const [y, mo] = m.split("-");
  return new Date(Number(y), Number(mo) - 1, 1).toLocaleDateString(toIntlLocale(locale), { month: "short", year: "2-digit" });
}

export function fmtAmount(n: number, locale: string): string {
  return n.toLocaleString(toIntlLocale(locale), { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
