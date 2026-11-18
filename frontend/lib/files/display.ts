// Welche Fassung einer Datei der Dateien-Tab zeigt: Gibt es zu einem Dokument (z. B. Word-Datei)
// eine automatisch erzeugte PDF-Ansicht, steht überall diese im Vordergrund - Name mit «.pdf»,
// PDF-Symbol, Öffnen öffnet das PDF. Das Original bleibt in Menü und Details erreichbar.
import type { FileOverviewItem } from "@/types/api";

export type FileDisplay = {
  /** Angezeigter Name: bei PDF-Ansicht mit Endung .pdf statt der Originalendung. */
  name: string;
  /** Endung für Symbol und Kennzeichen (klein), z. B. «pdf», «docx». */
  extension: string;
  /** Endung der hochgeladenen Originaldatei. */
  originalExtension: string;
  /** true: eine erzeugte PDF-Ansicht ersetzt in der Anzeige ein Nicht-PDF-Original. */
  showsGeneratedPdf: boolean;
  /** Was «Öffnen» öffnet: PDF-Ansicht, sonst die Originaldatei. */
  openUrl: string;
  pdfDownloadUrl: string | null;
};

export function fileExtension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : "";
}

export function fileDisplay(item: FileOverviewItem): FileDisplay {
  const originalExtension = fileExtension(item.original_name);
  const pdfUrl = item.document?.pdf_url ?? null;
  const showsGeneratedPdf = Boolean(pdfUrl) && originalExtension !== "pdf";
  const base = originalExtension ? item.original_name.slice(0, -(originalExtension.length + 1)) : item.original_name;
  return {
    name: showsGeneratedPdf ? `${base}.pdf` : item.original_name,
    extension: pdfUrl ? "pdf" : originalExtension,
    originalExtension,
    showsGeneratedPdf,
    openUrl: pdfUrl ?? item.content_url,
    pdfDownloadUrl: item.document?.pdf_download_url ?? null,
  };
}
