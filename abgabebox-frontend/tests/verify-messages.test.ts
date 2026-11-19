// Die öffentliche Prüfseite benennt den Dokumenttyp eines geprüften PDFs (verify.docType). Fehlt
// eine Übersetzung, fällt VerifyResultCard auf den rohen Code zurück («agenda», «fines» …).
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { locales } from "@/i18n/locale-config.generated";

// Alle Dokumenttypen, die das Document Studio exportiert und ins Dokumentenregister schreibt
// (backend/app/documents/doc_types.py, DOCUMENT_TYPES) plus der ältere Protokollauszug.
// Neuer Typ im Backend → hier und in messages/<locale>/abgabebox.json (verify.docType) ergänzen.
const DOCUMENT_TYPES = [
  "protocol",
  "invitation",
  "agenda",
  "attendance",
  "attendance_sheet",
  "members",
  "todos",
  "events",
  "calendar",
  "finance",
  "transactions",
  "fines",
  "statistics",
  "list",
  "form",
  "custom",
  "protocol_excerpt",
];

function docTypes(locale: string): Record<string, string> {
  const file = path.join(__dirname, "..", "messages", locale, "abgabebox.json");
  return JSON.parse(fs.readFileSync(file, "utf-8")).verify.docType;
}

describe.each(locales)("verify document types (%s)", (locale) => {
  it("names every exported document type", () => {
    const labels = docTypes(locale);
    expect(DOCUMENT_TYPES.filter((type) => !labels[type])).toEqual([]);
  });
});
