import { getRuntimeConfig } from "@/lib/runtime-config";

/**
 * Seiten der Benutzer-Doku (docs-site/docs), auf die die App verlinkt. Pfad ohne Endung, wie
 * MkDocs ihn ausliefert. Neue Seite: hier eintragen, Anker in der Markdown-Datei mit `{#anker}`
 * festlegen (stabil, auch wenn sich die Überschrift ändert).
 */
export const DOCS_PAGES = {
  abgabebox: "benutzer/abgabebox/",
} as const;

export type DocsPage = keyof typeof DOCS_PAGES;

/** Adresse einer Doku-Seite (optional mit Abschnitt) oder null, wenn keine Doku-Domain gesetzt ist. */
export function docsUrl(page: DocsPage, anchor?: string, domain: string | null | undefined = getRuntimeConfig().docsDomain): string | null {
  const host = domain?.trim().replace(/^https?:\/\//i, "").replace(/\/+$/, "");
  if (!host) return null;
  return `https://${host}/${DOCS_PAGES[page]}${anchor ? `#${encodeURIComponent(anchor)}` : ""}`;
}
