import { describe, expect, it } from "vitest";

import type { FileOverviewItem } from "@/types/api";

import { fileDisplay } from "./display";

function item(name: string, pdf: string | null): FileOverviewItem {
  return {
    original_name: name,
    content_url: "/api/stored-files/x/content",
    document: pdf ? { pdf_url: pdf, pdf_download_url: `${pdf}?download=1` } : null,
  } as unknown as FileOverviewItem;
}

describe("fileDisplay", () => {
  it("zeigt bei einer Word-Datei mit PDF-Ansicht das PDF", () => {
    const display = fileDisplay(item("Vereinsreglement.docx", "/api/documents/1/pdf"));
    expect(display).toMatchObject({ name: "Vereinsreglement.pdf", extension: "pdf", originalExtension: "docx", showsGeneratedPdf: true, openUrl: "/api/documents/1/pdf" });
  });

  it("bleibt beim Original ohne PDF-Ansicht", () => {
    expect(fileDisplay(item("Kassenbericht.xlsx", null))).toMatchObject({ name: "Kassenbericht.xlsx", extension: "xlsx", showsGeneratedPdf: false, openUrl: "/api/stored-files/x/content" });
  });

  it("ein PDF bleibt ein PDF", () => {
    expect(fileDisplay(item("Statuten.pdf", "/api/documents/2/pdf"))).toMatchObject({ name: "Statuten.pdf", showsGeneratedPdf: false });
  });
});
