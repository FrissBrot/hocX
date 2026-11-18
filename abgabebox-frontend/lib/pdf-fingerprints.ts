// Prüfseite, zweiter Schritt: Ist eine Datei nicht byte-genau ein hocX-Original, liest der Browser
// daraus die Dokument-ID und je Seite einen Fingerabdruck des Texts. An den Server gehen nur diese
// Werte, nie die Datei oder ihr Text. pdf.js wird erst hier geladen (nur bei unbekanntem Hash).
//
// Gleiche Regel wie backend/app/documents/page_fingerprints.py - sonst stimmt keine Seite:
// Seitentext → NFKC → Kleinbuchstaben → nur Buchstaben und Ziffern → SHA-256 über
// «hocx-page-v1:<dokument-id>:<text>» → die ersten 16 Hex-Zeichen.

export const MAX_FINGERPRINT_PAGES = 150;
const VERSION = "hocx-page-v1";
const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const XMP_DOCUMENT_ID = new RegExp(`<hocx:documentId>\\s*(${UUID})\\s*</hocx:documentId>`, "i");
const LINK_DOCUMENT_ID = new RegExp(`[?&]id=(${UUID})`, "i");

export type PdfFingerprints = {
  /** Aus dem XMP (hocx:documentId) oder dem Prüf-Link des QR-Codes; null, wenn nicht lesbar. */
  documentId: string | null;
  /** Seiten der hochgeladenen Datei (auch über MAX_FINGERPRINT_PAGES hinaus). */
  pageCount: number;
  /** Je Seite ein Fingerabdruck (leer ohne Dokument-ID: ohne sie gibt es kein Salz). */
  fingerprints: string[];
};

export function normalizePageText(text: string): string {
  return Array.from(text.normalize("NFKC").toLowerCase())
    .filter((char) => /[\p{L}\p{N}]/u.test(char))
    .join("");
}

export async function pageFingerprint(documentId: string, text: string): Promise<string> {
  const data = new TextEncoder().encode(`${VERSION}:${documentId.toLowerCase()}:${normalizePageText(text)}`);
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", data));
  return Array.from(digest.slice(0, 8), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function documentIdFromXmp(xmp: string | null | undefined): string | null {
  const match = xmp ? XMP_DOCUMENT_ID.exec(xmp) : null;
  return match ? match[1].toLowerCase() : null;
}

export function documentIdFromLink(url: string | null | undefined): string | null {
  const match = url ? LINK_DOCUMENT_ID.exec(url) : null;
  return match ? match[1].toLowerCase() : null;
}

type TextItem = { str?: string };
type PdfPage = {
  getTextContent: () => Promise<{ items: TextItem[] }>;
  getAnnotations: () => Promise<Array<{ url?: string; unsafeUrl?: string }>>;
  cleanup: () => void;
};
type PdfDocument = {
  numPages: number;
  getPage: (index: number) => Promise<PdfPage>;
  getMetadata: () => Promise<{ metadata?: { getRaw?: () => string } | null }>;
};

async function loadPdfJs() {
  // «legacy»-Build: die öffentliche Prüfseite muss auch auf älteren Handys laufen (der moderne
  // Build setzt u. a. Uint8Array.toHex voraus). Worker im selben Thread (globalThis.pdfjsWorker):
  // kein Worker-Skript, keine CSP-Änderung.
  await import("pdfjs-dist/legacy/build/pdf.worker.min.mjs");
  return import("pdfjs-dist/legacy/build/pdf.mjs");
}

export async function readPdfFingerprints(data: ArrayBuffer, fallbackDocumentId: string | null): Promise<PdfFingerprints> {
  const pdfjs = await loadPdfJs();
  const task = pdfjs.getDocument({
    // Kopie: pdf.js übernimmt den Puffer
    data: new Uint8Array(data.slice(0)),
    disableFontFace: true,
    useSystemFonts: false,
    verbosity: 0,
  });
  const document = (await task.promise) as unknown as PdfDocument;
  try {
    let documentId: string | null = null;
    try {
      documentId = documentIdFromXmp((await document.getMetadata()).metadata?.getRaw?.());
    } catch {
      // Metadaten unlesbar: weiter mit dem Prüf-Link
    }
    const texts: string[] = [];
    const limit = Math.min(document.numPages, MAX_FINGERPRINT_PAGES);
    for (let index = 1; index <= limit; index += 1) {
      const page = await document.getPage(index);
      const content = await page.getTextContent();
      texts.push(content.items.map((item) => item.str ?? "").join(""));
      if (!documentId) {
        const annotations = await page.getAnnotations().catch(() => []);
        for (const annotation of annotations) {
          documentId = documentIdFromLink(annotation.url ?? annotation.unsafeUrl);
          if (documentId) break;
        }
      }
      page.cleanup();
    }
    documentId = documentId ?? fallbackDocumentId;
    const fingerprints = documentId ? await Promise.all(texts.map((text) => pageFingerprint(documentId!, text))) : [];
    return { documentId, pageCount: document.numPages, fingerprints };
  } finally {
    // Aufräumen über die Ladeaufgabe (gibt Dokument und Worker frei)
    await task.destroy();
  }
}
