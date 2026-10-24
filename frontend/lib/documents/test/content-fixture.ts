// Testdaten für das Document Studio: eine kleine, gültige Vorlage (Layoutbaum) wie sie das
// Backend liefert. Nur für Tests (vitest), nicht im Export- oder UI-Pfad verwendet.

import type { TemplateContent, TemplateNode } from "@/lib/documents/layout";

export function text(id: string, value: string, extra: Partial<TemplateNode> = {}): TemplateNode {
  return { id, type: "text", role: "paragraph", content: { default: [{ t: "text", v: value }] }, ...extra };
}

export function contentFixture(): TemplateContent {
  return {
    schema_version: 1,
    page: { size: "A4", width: 210, height: 297, orientation: "portrait", margins: { top: 20, right: 18, bottom: 20, left: 18 }, columns: 1, column_gap: 6 },
    masters: [
      {
        id: "default",
        header: { id: "hdr", type: "header", children: [text("hdr-title", "Kopf")] },
        footer: { id: "ftr", type: "footer", children: [{ id: "pno", type: "page_number", format: "page_of" }] },
        background: [],
        orientation: null,
        margins: null,
      },
    ],
    title_page: { enabled: false, visible_if: null, master: null, background: null, children: [] },
    body: [
      text("intro", "Einleitung", { name: "Einleitung" }),
      {
        id: "sec",
        type: "section",
        title: { default: [{ t: "text", v: "Abschnitt" }] },
        children: [text("inner-1", "Eins"), text("inner-2", "Zwei")],
      },
      { id: "fixed", type: "verify_note", locked: true },
    ],
    settings: {
      first_page_master: null,
      default_master: "default",
      heading_numbering: null,
      justify: false,
      hyphenate: true,
      language: null,
      auto_verify_note: true,
      brand_overrides: { primary: null, secondary: null, accent: null, heading: null, logo_asset_id: null, body_font: null, heading_font: null },
    },
  };
}
