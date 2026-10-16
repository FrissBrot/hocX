// Brand-Werte für die angenäherte Darstellung im Designer (die verbindliche Darstellung
// liefert die Typst-Vorschau). Farben und Schriften sind Dokumentdaten aus dem Brand-Profil
// und werden als Laufzeitwerte gesetzt, nicht als UI-Farben.

import type { BrandOverrides, BrandTokens, Length } from "@/components/documents/designer/types";

export const MM_TO_PX = 96 / 25.4;

const FONT_FAMILIES: Record<string, string> = {
  inter: "Inter",
  liberation_sans: "Liberation Sans",
  liberation_serif: "Liberation Serif",
  noto_sans: "Noto Sans",
};

export type BrandView = {
  colors: Record<string, string>;
  custom: Record<string, string>;
  bodyFont: string;
  headingFont: string;
  tokens: BrandTokens;
};

export function brandView(tokens: BrandTokens, overrides?: BrandOverrides | null): BrandView {
  const colors: Record<string, string> = { ...tokens.colors } as unknown as Record<string, string>;
  delete colors.custom;
  for (const key of ["primary", "secondary", "accent", "heading"] as const) {
    const value = overrides?.[key];
    if (value) colors[key] = value;
  }
  const custom = Object.fromEntries(tokens.colors.custom.map((item) => [item.key, item.value]));
  const font = (choice: { builtin: string | null }, override?: string | null) => FONT_FAMILIES[override ?? choice.builtin ?? "inter"] ?? "Inter";
  return {
    colors,
    custom,
    bodyFont: font(tokens.typography.body, overrides?.body_font),
    headingFont: font(tokens.typography.heading, overrides?.heading_font),
    tokens: overrides?.base_size ? { ...tokens, typography: { ...tokens.typography, base_size: overrides.base_size } } : tokens,
  };
}

/** Farbreferenz ($brand.primary, $brand.custom.x, $brand.status.success, #RRGGBB) → CSS-Farbe. */
export function resolveColor(reference: string | null | undefined, view: BrandView): string | undefined {
  if (!reference) return undefined;
  if (reference.startsWith("#")) return reference;
  const parts = reference.split(".");
  if (parts[0] !== "$brand") return undefined;
  if (parts[1] === "custom") return view.custom[parts[2] ?? ""];
  if (parts[1] === "status") return view.colors[parts[2] ?? ""];
  return view.colors[parts[1] ?? ""];
}

export function resolveFont(reference: string | null | undefined, view: BrandView): string | undefined {
  if (!reference) return undefined;
  if (reference === "$brand.font.heading") return view.headingFont;
  if (reference.startsWith("$brand.font.")) return view.bodyFont;
  return reference;
}

/** Länge (auto | fill | 12mm | 50% | 1fr) → CSS-Breite. */
export function cssLength(value: Length | null | undefined, zoom: number): string | undefined {
  if (!value || value === "auto") return undefined;
  if (value === "fill") return "100%";
  const match = /^(\d+(?:\.\d+)?)(mm|%|fr)$/.exec(value);
  if (!match) return undefined;
  const number = Number(match[1]);
  if (match[2] === "mm") return `${number * MM_TO_PX * zoom}px`;
  if (match[2] === "%") return `${number}%`;
  return undefined;
}

/** Spaltenbreite für CSS-Grid (fr bleibt fr). */
export function gridTrack(value: Length | null | undefined, zoom: number): string {
  if (!value || value === "auto") return "auto";
  if (value === "fill") return "1fr";
  const match = /^(\d+(?:\.\d+)?)(mm|%|fr)$/.exec(value);
  if (!match) return "auto";
  const number = Number(match[1]);
  if (match[2] === "fr") return `${number}fr`;
  if (match[2] === "mm") return `${number * MM_TO_PX * zoom}px`;
  return `${number}%`;
}

export function mm(value: number | undefined | null, zoom: number): number {
  return (value ?? 0) * MM_TO_PX * zoom;
}
