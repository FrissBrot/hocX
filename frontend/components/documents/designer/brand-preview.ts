// Brand-Werte für die angenäherte Darstellung im Designer (die verbindliche Darstellung
// liefert die Typst-Vorschau). Farben und Schriften sind Dokumentdaten aus dem Brand-Profil
// und werden als Laufzeitwerte gesetzt, nicht als UI-Farben.

import type { BrandOverrides, BrandTokens, Length } from "@/components/documents/designer/types";
import type { DocumentAsset, ResolvedBrand } from "@/lib/documents/api";

export const MM_TO_PX = 96 / 25.4;
export const PT_TO_PX = 96 / 72;

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
  // Werte, die der Typst-Compile tatsächlich verwendet (aus der Arbeitsflächen-Antwort, sonst
  // aus den Tokens abgeleitet)
  weights: { body: number; heading: number };
  headingLook: { variant: string; radius: number };
};

const WEIGHTS: Record<string, number> = { regular: 400, medium: 500, bold: 700 };

/** CSS-Schriftstapel aus Typst-Familiennamen (erste vorhandene gewinnt, wie im Compile). */
export function fontStack(families: string[]): string {
  return [...families.map((name) => `"${name.replace(/"/g, "")}"`), "sans-serif"].join(", ");
}

export function brandView(tokens: BrandTokens, overrides?: BrandOverrides | null): BrandView {
  const colors: Record<string, string> = { ...tokens.colors } as unknown as Record<string, string>;
  delete colors.custom;
  for (const key of ["primary", "secondary", "accent", "heading"] as const) {
    const value = overrides?.[key];
    if (value) colors[key] = value;
  }
  const custom = Object.fromEntries(tokens.colors.custom.map((item) => [item.key, item.value]));
  const font = (choice: { builtin: string | null }, override?: string | null) => FONT_FAMILIES[override ?? choice.builtin ?? "inter"] ?? "Inter";
  const heading = tokens.appearance?.elements?.heading;
  return {
    colors,
    custom,
    bodyFont: fontStack([font(tokens.typography.body, overrides?.body_font)]),
    headingFont: fontStack([font(tokens.typography.heading, overrides?.heading_font)]),
    tokens: overrides?.base_size ? { ...tokens, typography: { ...tokens.typography, base_size: overrides.base_size } } : tokens,
    weights: { body: WEIGHTS[tokens.typography.weight_body] ?? 400, heading: WEIGHTS[tokens.typography.weight_heading] ?? 700 },
    headingLook: { variant: heading?.variant ?? tokens.layout.heading_style, radius: tokens.layout.radius },
  };
}

/** Brand-Werte des Compiles (inkl. Vorlagen-Übersteuerungen) über die Token-Ansicht legen. */
export function resolvedBrandView(resolved: ResolvedBrand, fallback: BrandView): BrandView {
  const { weight_body, weight_heading, ...typography } = resolved.typography;
  const heading = resolved.appearance.heading;
  return {
    colors: { ...fallback.colors, ...resolved.colors },
    custom: { ...fallback.custom, ...resolved.custom_colors },
    bodyFont: fontStack(resolved.fonts.body),
    headingFont: fontStack(resolved.fonts.heading),
    tokens: {
      ...fallback.tokens,
      typography: { ...fallback.tokens.typography, ...typography },
      layout: { ...fallback.tokens.layout, ...(resolved.layout as Partial<BrandTokens["layout"]>) },
    },
    weights: { body: weight_body, heading: weight_heading },
    headingLook: { variant: heading?.variant ?? resolved.layout.heading_style, radius: heading?.radius ?? resolved.layout.radius },
  };
}

// Mitgelieferte Schriften der Dokument-Engine (backend/app/documents/fonts), geladen über
// /api/document-studio/fonts, damit Zeilenumbrüche und Breiten denen im PDF entsprechen.
const BUILTIN_FONT_FILES: Record<string, string> = {
  Inter: "Inter",
  "Liberation Sans": "LiberationSans",
  "Liberation Serif": "LiberationSerif",
  "Noto Sans": "NotoSans",
};
const FONT_VARIANTS = [
  { file: "Regular", weight: "400", style: "normal" },
  { file: "Bold", weight: "700", style: "normal" },
  { file: "Italic", weight: "400", style: "italic" },
  { file: "BoldItalic", weight: "700", style: "italic" },
];
const registeredFonts = new Set<string>();

/** Schriften für die Arbeitsfläche registrieren (einmal je Familie und Sitzung). */
export function registerDocumentFonts(families: string[], assets: DocumentAsset[]) {
  if (typeof document === "undefined" || typeof FontFace === "undefined" || !document.fonts) return;
  for (const family of families) {
    if (registeredFonts.has(family)) continue;
    const prefix = BUILTIN_FONT_FILES[family];
    const uploads = assets.filter((asset) => asset.kind === "font" && asset.font_family === family);
    if (!prefix && uploads.length === 0) continue;
    registeredFonts.add(family);
    const faces = prefix
      ? FONT_VARIANTS.map((variant) => new FontFace(family, `url(/api/document-studio/fonts/${prefix}-${variant.file}.ttf)`, { weight: variant.weight, style: variant.style }))
      : uploads.map((asset) => new FontFace(family, `url(${asset.content_url})`));
    for (const face of faces) {
      document.fonts.add(face);
      face.load().catch(() => {
        // Schrift nicht ladbar: die Arbeitsfläche fällt auf die nächste Schrift im Stapel zurück
      });
    }
  }
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
