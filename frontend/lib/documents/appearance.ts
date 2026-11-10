// Erscheinungsbild der Elemente (backend/app/documents/appearance.py): welche Darstellung eine
// Elementart erbt, wenn weder Brand-Profil noch Block sie übersteuern.

import type { AppearanceCatalog } from "@/lib/documents/api";
import type { AppearanceOverrides, BrandTokens } from "@/lib/documents/layout";

export const DEFAULT_APPEARANCE_BASE = "classic";

/** Variante aus dem Grundstil: Überschriften und Tabellen aus dem Seitenaufbau, der Rest aus dem Grundstil. */
export function baseVariant(tokens: BrandTokens, catalog: AppearanceCatalog, kind: string): string {
  if (kind === "heading") return tokens.layout.heading_style;
  if (kind === "table") return tokens.layout.table_style;
  const base = catalog.bases[tokens.appearance?.base ?? DEFAULT_APPEARANCE_BASE] ?? catalog.bases[DEFAULT_APPEARANCE_BASE];
  return base?.elements[kind] ?? catalog.variants[kind]?.[0] ?? "";
}

/** Variante, die ein Block im Designer erbt (Grundstil + Übersteuerung im Brand-Profil). */
export function brandVariant(tokens: BrandTokens, catalog: AppearanceCatalog, kind: string): string {
  return tokens.appearance?.elements[kind]?.variant ?? baseVariant(tokens, catalog, kind);
}

/** Übersteuerung setzen; leere Einträge fallen weg (wie im Backend). */
export function setAppearance(current: AppearanceOverrides | undefined, kind: string, patch: Partial<{ variant: string | null; corners: "square" | "rounded" | null }>): AppearanceOverrides {
  const next: AppearanceOverrides = { ...(current ?? {}) };
  const merged = { ...(next[kind] ?? {}), ...patch };
  if (!merged.variant && !merged.corners) delete next[kind];
  else next[kind] = { variant: merged.variant || null, corners: merged.corners || null };
  return next;
}
