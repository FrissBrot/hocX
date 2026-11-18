import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { documentIdFromLink, documentIdFromXmp, normalizePageText, pageFingerprint, readPdfFingerprints } from "./pdf-fingerprints";

// Gemeinsame Probe mit dem Backend (backend/tests/documents/test_page_verification.py): ein echtes
// hocX-PDF und die dort mit pypdfium2 berechneten Fingerabdrücke. Weicht pdf.js hier ab, meldet
// die Prüfseite bei jeder neu gespeicherten Datei falsche Seiten.
const FIXTURES = path.resolve(__dirname, "../test-fixtures");
const expected = JSON.parse(readFileSync(path.join(FIXTURES, "verify-fingerprints.json"), "utf8")) as {
  document_id: string;
  fingerprints: string[];
  normalized: string[];
};

function fixturePdf(): ArrayBuffer {
  const bytes = readFileSync(path.join(FIXTURES, "verify-sample.pdf"));
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
}

describe("Seiten-Fingerabdrücke", () => {
  it("normalisiert wie das Backend", () => {
    expect(normalizePageText("Seite 1 –\n Größe:  ﬁnal")).toBe("seite1größefinal");
    expect(normalizePageText("CHF 1'250.–")).toBe("chf1250");
  });

  it("salzt mit der Dokument-ID und kürzt auf 16 Zeichen", async () => {
    const a = await pageFingerprint("ID-A", "Text");
    expect(a).toHaveLength(16);
    expect(await pageFingerprint("id-a", " text ")).toBe(a);
    expect(await pageFingerprint("id-b", "Text")).not.toBe(a);
  });

  it("liest die Dokument-ID aus XMP oder Prüf-Link", () => {
    const id = "01a1ee3b-f683-7fc5-8505-2be4a3e42baf";
    expect(documentIdFromXmp(`<x><hocx:documentId>${id.toUpperCase()}</hocx:documentId></x>`)).toBe(id);
    expect(documentIdFromLink(`https://box.example/verify?id=${id}`)).toBe(id);
    expect(documentIdFromXmp("<x/>")).toBeNull();
  });

  it("berechnet für ein echtes hocX-PDF dieselben Werte wie das Backend", async () => {
    const read = await readPdfFingerprints(fixturePdf(), null);
    expect(read.documentId).toBe(expected.document_id);
    expect(read.idSource).toBe("file");
    expect(read.pageCount).toBe(expected.fingerprints.length);
    expect(read.fingerprints).toEqual(expected.fingerprints);
  }, 30_000);
});
